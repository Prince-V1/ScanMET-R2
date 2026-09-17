from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import requests, re, os, sqlite3, base64
from reportlab.pdfgen import canvas

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

KEY = os.getenv("GOOGLE_VISION_KEY")
DB = "scanmet.db"

def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS scans
        (id INTEGER PRIMARY KEY, status TEXT, issues TEXT, ocr TEXT)""")
    con.commit()
    con.close()

init_db()

def check(text):
    patterns = {
        "MRP": r"(MRP|Maximum Retail Price)[^₹0-9]*₹?\s?[\d.]+",
        "Quantity": r"\b\d+(?:\.\d+)?\s?(g|kg|ml|l)\b",
        "Date": r"(MFD|PKD|Manufactured|Best Before|Expiry)",
        "Manufacturer/Importer":
            r"(Manufactured by|Marketed by|Importer)"
    }
    fields = {}
    for name, pattern in patterns.items():
        m = re.search(pattern, text, re.I)
        fields[name] = m.group(0) if m else "Not found"

    issues = [f"{k} declaration not detected"
              for k, v in fields.items() if v == "Not found"]
    return fields, issues

@app.post("/scan")
async def scan(file: UploadFile = File(...)):
    image = await file.read()
    data = {"requests": [{
        "image": {"content": base64.b64encode(image).decode()},
        "features": [{"type": "TEXT_DETECTION"}]
    }]}
    url = f"https://vision.googleapis.com/v1/images:annotate?key={KEY}"
    result = requests.post(url, json=data).json()
    text = result.get("responses", [{}])[0].get(
        "fullTextAnnotation", {}).get("text", "")
    fields, issues = check(text)
    status = "COMPLIANT" if not issues else "REVIEW REQUIRED"

    con = sqlite3.connect(DB)
    con.execute("INSERT INTO scans(status,issues,ocr) VALUES(?,?,?)",
                (status, "; ".join(issues), text))
    con.commit()
    con.close()
    return {"status": status, "fields": fields,
            "issues": issues, "ocr_text": text}

@app.get("/history")
def history():
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT id,status,issues FROM scans ORDER BY id DESC LIMIT 10"
    ).fetchall()
    con.close()
    return [{"id": r[0], "status": r[1], "issues": r[2]}
            for r in rows]

@app.post("/report")
async def report(data: dict):
    path = "ScanMET_Report.pdf"
    pdf = canvas.Canvas(path)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(50, 800, "ScanMET Compliance Report")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, 775, f"Status: {data.get('status')}")
    y = 745
    for k, v in data.get("fields", {}).items():
        pdf.drawString(50, y, f"{k}: {v}")
        y -= 22
    pdf.drawString(50, y, "Issues / Suggestions:")
    y -= 22
    for item in data.get("issues", ["None"]):
        pdf.drawString(60, y, "• " + item)
        y -= 20
    pdf.save()
    return FileResponse(path, filename=path)

@app.get("/")
def home():
    return {"app": "ScanMET", "message": "API is running"}
