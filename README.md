# ScanMET — Upgraded Prototype v2

## Added
- Working Google Vision OCR integration
- More label rules:
  - MRP
  - Net Quantity
  - Manufacturing/Packing/Shelf-life date
  - Batch/Lot
  - Manufacturer/Marketer/Importer
  - Consumer-care/contact
- Rule-based status: COMPLIANT / REVIEW REQUIRED
- Correction suggestions
- Persistent SQLite scan history
- Open any previous scan and view its full saved result
- Clear-history button
- Image preview before scanning
- Better error handling
- Working PDF export
- Mobile-friendly frontend
- Backend health endpoint
- Frontend API URL can be changed without editing code

## Important security rule
DO NOT put the Google Vision API key in `frontend/index.html` or commit it to GitHub.

Set the key only on the backend as an environment variable:

Windows PowerShell:
`$env:GOOGLE_VISION_KEY="YOUR_KEY"`

Windows CMD:
`set GOOGLE_VISION_KEY=YOUR_KEY`

Linux/macOS:
`export GOOGLE_VISION_KEY="YOUR_KEY"`

## Run backend locally

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open `frontend/index.html`.

## Using it from a phone

`127.0.0.1` means the same device only. For a phone on another network, the backend must be publicly deployed.

Recommended prototype architecture:

Phone/PC browser
       ↓
Vercel frontend
       ↓
Public FastAPI backend
       ↓
Google Vision OCR
       ↓
SQLite/database

For a real public deployment, replace the frontend's API URL with the public backend URL:

```js
localStorage.setItem("SCANMET_API","https://YOUR-BACKEND-URL")
```

You can also edit the `API` constant directly.

## Data persistence warning

SQLite keeps results while the backend machine/storage persists.

Some serverless hosts have ephemeral filesystems, so SQLite should NOT be treated as permanent production storage there. For a public prototype, use a persistent backend disk or a hosted database.

## Compliance disclaimer

These are prototype screening rules based on detectable label text. They are not a legal certification engine. Rules should be validated against the exact applicable Indian regulatory requirements before presenting ScanMET as a compliance authority.

## Files

- `backend/main.py` — FastAPI API, OCR, rules, database, PDF
- `backend/requirements.txt` — Python dependencies
- `frontend/index.html` — responsive web UI
