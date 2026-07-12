# IDMS Document Processing API (Python)

FastAPI reimplementation of IDMS Word document automation.

## Quick start

```bash
cd C:\Work\Integers.Ai\IDMSVer2Python
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open Swagger UI: http://localhost:8000/swagger

Swagger is configured with **Try it out** enabled by default, a filter box to search
endpoints, and self-explanatory descriptions on every route and request field.

## Phase 1 endpoints

All routes are under `/api/v1/documents/`:

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/toc` | Get table of contents |
| POST | `/placeholders` | Find `<PLACEHOLDER>` tokens |
| POST | `/merge` | Merge section (preserves destination formatting) |
| POST | `/paragraphs` | Insert plain text |
| POST | `/paragraphs/formatted` | Insert HTML text |
| POST | `/sections` | Insert heading + content |
| POST | `/sections/delete` | Delete sections by bookmarks |
| POST | `/images` | Insert image (multipart) |
| POST | `/coversheet` | Apply coversheet |
| POST | `/fields/update` | Mark caption fields dirty |
| POST | `/toc/update` | Mark TOC fields dirty |
| POST | `/replace` | Replace document after table match |
| POST | `/inserted-text/markers` | List editable markers |
| POST | `/inserted-text/content` | Get marker content |
| PUT | `/inserted-text` | Update marker content |
| POST | `/inserted-text/sections` | List editable sections |

## Merge behavior

Unlike a straight XML copy, the merge engine:

1. Clones the master template to the output path
2. Copies content between source bookmarks
3. Remaps list/bullet `numId` values to the **destination** numbering definitions
4. Remaps heading styles to the correct destination heading level
5. Strips orphan numbering from non-list paragraphs

## Auth

JWT validation is stubbed for Phase 1. Pass `X-User-Id` header for audit trail user attribution (defaults to `1`).
