import { useState, useEffect } from "react";
import { listDocuments, getTocFlat, type DocumentListItem } from "../api";

interface TocEntry {
  sl_no: number;
  item_text: string;
  page_ref: string;
  page_no: string;
  section_number: string;
  level: number;
}

export default function TocViewer() {
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<string>("");
  const [tocEntries, setTocEntries] = useState<TocEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    loadDocuments();
  }, []);

  const loadDocuments = async () => {
    setLoadingDocs(true);
    try {
      const docs = await listDocuments();
      setDocuments(docs);
    } catch (err) {
      setBanner({ kind: "err", text: "Could not reach the backend at /api. Is the FastAPI server running on :8000?" });
    } finally {
      setLoadingDocs(false);
    }
  };

  const handleDocumentChange = async (path: string) => {
    setSelectedDocument(path);
    setTocEntries([]);
    setBanner(null);

    if (!path) return;

    setLoading(true);
    try {
      const response = await getTocFlat(path);
      if (response.success && response.data) {
        setTocEntries(response.data.entries);
        setBanner({ kind: "ok", text: `Loaded ${response.data.entries.length} TOC entries` });
      } else {
        setBanner({ kind: "err", text: response.message || "Failed to load TOC" });
      }
    } catch (err) {
      setBanner({ kind: "err", text: "Failed to load TOC" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Table of Contents Viewer</h1>
          <p className="page-sub">
            Select a document to view its table of contents entries in JSON format.
          </p>
        </div>
      </header>

      {banner && <div className={"banner " + (banner.kind === "ok" ? "ok" : "err")}>{banner.text}</div>}

      <div className="panel">
        <div className="panel-head">
          <label className="field-label">Select Document</label>
          <select
            className="select"
            value={selectedDocument}
            disabled={loading}
            onChange={(e) => handleDocumentChange(e.target.value)}
          >
            <option value="">— Select a document —</option>
            {documents.map((doc) => (
              <option key={doc.path} value={doc.path}>
                {doc.name}
              </option>
            ))}
          </select>
        </div>
        <div className="panel-body">
          {loadingDocs ? (
            <div className="toc-empty">
              <div className="spinner" /> Loading documents…
            </div>
          ) : documents.length === 0 ? (
            <div className="toc-empty muted">No documents found in the source templates folder.</div>
          ) : loading ? (
            <div className="toc-empty">
              <div className="spinner" /> Loading table of contents…
            </div>
          ) : selectedDocument && tocEntries.length > 0 ? (
            <div className="toc-json-container">
              <h3>TOC Entries</h3>
              <pre className="json-display">{JSON.stringify(tocEntries, null, 2)}</pre>
            </div>
          ) : selectedDocument ? (
            <div className="toc-empty muted">No TOC entries found in this document.</div>
          ) : (
            <div className="toc-empty muted">Select a document to view its table of contents.</div>
          )}
        </div>
      </div>
    </div>
  );
}
