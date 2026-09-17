from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import requests, re, os, sqlite3, base64, json, tempfile
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

app = FastAPI(title="ScanMET API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

KEY = os.getenv("GOOGLE_VISION_KEY")
DB = os.getenv("SCANMET_DB", "scanmet.db")

# Prototype rules for packaged-label screening.
# These are screening rules, not a legal certification.
RULES = {
    "MRP": {
        "pattern": r"(MRP|MAXIMUM\s+RETAIL\s+PRICE)[^₹0-9]{0,30}(?:₹|RS\.?|INR)?\s*[\d,]+(?:\.\d{1,2})?",
        "message": "MRP declaration was not detected."
    },
    "Net Quantity": {
        "pattern": r"\b(?:NET(?:\s+QUANTITY)?|NET\s+WT|NET\s+WEIGHT)\s*[:\-]?\s*\d+(?:\.\d+)?\s*(?:g|kg|mg|ml|l|L)\b|\b\d+(?:\.\d+)?\s*(?:g|kg|mg|ml|l|L)\b",
        "message": "Net quantity/weight declaration was not detected."
    },
    "Date": {
        "pattern": r"(?:MFD|MFG|PKD|PACKED|MANUFACTURED|DATE\s+OF\s+(?:MFG|MANUFACTURE|PACKING)|BEST\s+BEFORE|EXP(?:IRY|\.))",
        "message": "Manufacturing/packing or shelf-life date information was not detected."
    },
    "Batch/Lot": {
        "pattern": r"(?:BATCH|LOT)\s*(?:NO\.?|NUMBER)?\s*[:\-]?\s*[A-Z0-9][A-Z0-9\-\/]{1,}",
        "message": "Batch/Lot identification was not detected."
    },
    "Manufacturer/Importer": {
        "pattern": r"(?:MANUFACTURED\s+BY|MANUFACTURER|MFD\.?\s+BY|MARKETED\s+BY|IMPORTED\s+BY|IMPORTER)",
        "message": "Manufacturer/marketer/importer information was not detected."
    },
    "Consumer Care": {
        "pattern": r"(?:CONSUMER\s+CARE|CUSTOMER\s+CARE|CONSUMER\s+COMPLAINT|HELPLINE|TOLL\s*[- ]?FREE|CONTACT\s+US)",
        "message": "Consumer-care/contact information was not detected."
    },
}

def init_db():
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at TEXT NOT NULL,
            filename TEXT,
            status TEXT NOT NULL,
            fields TEXT NOT NULL,
            issues TEXT NOT NULL,
            suggestions TEXT NOT NULL,
            ocr TEXT
        )
    """)
    con.commit()
    con.close()

init_db()

def run_rules(text: str):
    fields = {}
    issues = []
    suggestions = []

    for name, rule in RULES.items():
        m = re.search(rule["pattern"], text or "", re.I)
        fields[name] = m.group(0).strip() if m else "Not found"
        if not m:
            issues.append(rule["message"])
            suggestions.append(f"Check the label for a clear {name} declaration.")

    # Extra sanity checks
    if text and not re.search(r"[A-Za-z]", text):
        issues.append("OCR text contains very little readable alphabetic content.")
        suggestions.append("Retake the image with better lighting, focus and a straight label.")

    status = "COMPLIANT" if not issues else "REVIEW REQUIRED"
    return fields, issues, suggestions, status

def save_scan(filename, status, fields, issues, suggestions, ocr):
    con = sqlite3.connect(DB)
    cur = con.execute(
        """INSERT INTO scans
        (scanned_at, filename, status, fields, issues, suggestions, ocr)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().isoformat(timespec="seconds"),
            filename,
            status,
            json.dumps(fields, ensure_ascii=False),
            json.dumps(issues, ensure_ascii=False),
            json.dumps(suggestions, ensure_ascii=False),
            ocr or "",
        ),
    )
    scan_id = cur.lastrowid
    con.commit()
    con.close()
    return scan_id

def get_google_ocr(image: bytes):
    if not KEY:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_VISION_KEY is not configured on the backend."
        )

    payload = {
        "requests": [{
            "image": {"content": base64.b64encode(image).decode("utf-8")},
            "features": [{"type": "TEXT_DETECTION"}]
        }]
    }
    url = f"https://vision.googleapis.com/v1/images:annotate?key={KEY}"
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Google OCR request failed: {exc}")

    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"].get("message", "Google OCR error"))

    item = result.get("responses", [{}])[0]
    return item.get("fullTextAnnotation", {}).get("text", "")

@app.get("/")
def home():
    return {
        "app": "ScanMET",
        "version": "2.0",
        "message": "API is running"
    }

@app.get("/health")
def health():
    return {"ok": True, "google_ocr_configured": bool(KEY)}

@app.post("/scan")
async def scan(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")

    image = await file.read()
    if not image:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")
    if len(image) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image is too large. Maximum size is 10 MB.")

    text = get_google_ocr(image)
    fields, issues, suggestions, status = run_rules(text)
    scan_id = save_scan(
        file.filename or "image",
        status, fields, issues, suggestions, text
    )

    return {
        "id": scan_id,
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "filename": file.filename,
        "status": status,
        "fields": fields,
        "issues": issues,
        "suggestions": suggestions,
        "ocr_text": text,
    }

@app.get("/history")
def history(limit: int = 25):
    limit = max(1, min(limit, 100))
    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT id, scanned_at, filename, status, fields, issues, suggestions, ocr
           FROM scans ORDER BY id DESC LIMIT ?""", (limit,)
    ).fetchall()
    con.close()

    output = []
    for r in rows:
        output.append({
            "id": r[0],
            "scanned_at": r[1],
            "filename": r[2],
            "status": r[3],
            "fields": json.loads(r[4] or "{}"),
            "issues": json.loads(r[5] or "[]"),
            "suggestions": json.loads(r[6] or "[]"),
            "ocr_text": r[7] or "",
        })
    return output

@app.get("/history/{scan_id}")
def history_item(scan_id: int):
    con = sqlite3.connect(DB)
    row = con.execute(
        """SELECT id, scanned_at, filename, status, fields, issues, suggestions, ocr
           FROM scans WHERE id=?""", (scan_id,)
    ).fetchone()
    con.close()

    if not row:
        raise HTTPException(status_code=404, detail="Scan not found.")

    return {
        "id": row[0],
        "scanned_at": row[1],
        "filename": row[2],
        "status": row[3],
        "fields": json.loads(row[4] or "{}"),
        "issues": json.loads(row[5] or "[]"),
        "suggestions": json.loads(row[6] or "[]"),
        "ocr_text": row[7] or "",
    }

@app.delete("/history")
def clear_history():
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM scans")
    con.commit()
    con.close()
    return {"ok": True, "message": "Scan history cleared."}

@app.post("/report")
async def report(data: dict):
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    pdf = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 55

    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(45, y, "ScanMET Compliance Report")
    y -= 30

    pdf.setFont("Helvetica", 10)
    pdf.drawString(45, y, f"Scan ID: {data.get('id', '-')}")
    y -= 16
    pdf.drawString(45, y, f"File: {data.get('filename', '-')}")
    y -= 16
    pdf.drawString(45, y, f"Status: {data.get('status', 'REVIEW REQUIRED')}")
    y -= 28

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(45, y, "Detected Fields")
    y -= 20
    pdf.setFont("Helvetica", 10)

    for k, v in data.get("fields", {}).items():
        pdf.drawString(55, y, f"{k}: {v}")
        y -= 16
        if y < 70:
            pdf.showPage()
            y = height - 55

    y -= 10
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(45, y, "Issues / Suggestions")
    y -= 20
    pdf.setFont("Helvetica", 10)

    items = data.get("suggestions") or data.get("issues") or ["No detected issues."]
    for item in items:
        text = "• " + str(item)
        # Basic wrapping for PDF
        while len(text) > 100:
            pdf.drawString(55, y, text[:100])
            text = text[100:]
            y -= 15
        pdf.drawString(55, y, text)
        y -= 16
        if y < 70:
            pdf.showPage()
            y = height - 55
            pdf.setFont("Helvetica", 10)

    pdf.save()
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"ScanMET_Report_{data.get('id', 'scan')}.pdf",
    )
