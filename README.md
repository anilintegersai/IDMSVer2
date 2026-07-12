# IDMS Ver2

Document automation platform for Word (.docx) processing — a Python/React reimplementation
of the IDMS document workflow.

## Repository layout

| Folder | Description |
|--------|-------------|
| [`IDMSVer2Python/`](IDMSVer2Python) | FastAPI backend — pure-OOXML `.docx` processing (TOC/outline, section merge with destination-formatting preservation, paragraph/section/image insertion, placeholders, inserted-text editing). No Microsoft Word required. |
| [`IDMSVer2UI/`](IDMSVer2UI) | React + TypeScript (Vite) front-end — Merge Templates (drag-and-drop section merge with live preview), with Insert Section / Insert Content to follow. |

See each folder's `README.md` for setup and run instructions.

## Quick start

```bash
# Backend  (http://localhost:8000, Swagger at /swagger)
cd IDMSVer2Python
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

# Front-end  (http://localhost:5173, proxies /api -> :8000)
cd IDMSVer2UI
npm install
npm run dev
```

## Configuration

Backend paths and secrets are read from environment variables (or a local, git-ignored `.env`);
see `IDMSVer2Python/.env.example`. Do not commit real credentials.
