# IDMS Document Automation — UI

React + TypeScript (Vite) front-end for the IDMS document API. Phase 1 implements
**Merge Templates**; *Insert Section* and *Insert Content* are stubbed for later.

## Features (Merge Templates)

- **Master** and **Associated** template dropdowns, both loaded from the source folder.
- Associated is disabled until a Master is chosen; the chosen Master is then removed
  from the Associated list.
- Each selection shows that document's **table of contents** (section number · title · page).
- **Drag** a section from the Associated TOC and **drop** it onto the Master TOC — the
  whole sub-tree (heading + children) travels together.
- On drop, the inserted section is renumbered to **continue from the drop location**, with
  its hierarchy preserved. Only one operation at a time — **Merge** to apply or **Cancel**
  to start over (the dropdowns lock until you do).
- **Merge** writes a *copy* of the master (originals are never modified) to the merged-output
  folder and previews the result inline with `docx-preview`.

## Prerequisites

- **Node.js 18+** (tested on 20.20).
- The **FastAPI backend** running — see `../IDMSVer2Python`.

## Run

**1. Start the backend** (from `C:\Work\Integers.Ai\IDMSVer2Python`):

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**2. Start the UI** (from this folder):

```powershell
npm install      # first time only
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` → `http://localhost:8000`, so no CORS setup
is needed.

## Configuration

Folders are configured on the **backend** (`app/config.py`, override via `.env`):

| Setting | Default | Purpose |
|---|---|---|
| `TEMPLATE_SOURCE_BASE_PATH` | `C:\Work\YokogawaSharedFolder\SourceTemplates` | Documents shown in both dropdowns |
| `MERGED_BASE_PATH` | `C:\Work\YokogawaSharedFolder\MergedTemplates` | Where merged documents are written |

## Backend endpoints used

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/v1/documents/list` | Populate the dropdowns |
| POST | `/api/v1/documents/toc` | Hierarchical TOC (section #, title, page, bookmark, level) |
| POST | `/api/v1/documents/merge-section` | Merge a heading + descendants into a copy of the master |
| GET | `/api/v1/documents/download?path=…` | Stream a .docx for the embedded viewer |

## Project layout

```
src/
  api.ts                 # typed API client
  tree.ts                # TOC tree helpers (clone, flatten, renumber, insert)
  components/
    Sidebar.tsx          # left navigation menu
    TocTree.tsx          # drag/drop-aware TOC tree
    DocViewer.tsx        # docx-preview wrapper
  pages/
    MergeTemplates.tsx   # the main two-panel merge page
    Placeholder.tsx      # Insert Section / Insert Content stubs
  styles.css             # design system
```
