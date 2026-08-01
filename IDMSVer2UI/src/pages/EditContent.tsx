import { useEffect, useState } from "react";
import {
  listDocuments,
  getEditableSections,
  getContentMarkers,
  getContentText,
  replaceContentText,
  type DocumentListItem,
  type EditableContent,
  type ContentMarker,
} from "../api";

/** Last path segment (handles both Windows and POSIX separators). */
function baseName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

/** Suggested copy name derived from a document path: "<stem> - Copy". */
function suggestCopyName(path: string): string {
  return `${baseName(path).replace(/\.docx$/i, "")} - Copy`;
}

export default function EditContent() {
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [docError, setDocError] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [editableSections, setEditableSections] = useState<EditableContent[]>([]);
  const [loadingSections, setLoadingSections] = useState(false);
  const [selectedSection, setSelectedSection] = useState<EditableContent | null>(null);
  const [contentMarkers, setContentMarkers] = useState<ContentMarker[]>([]);
  const [loadingMarkers, setLoadingMarkers] = useState(false);
  const [selectedMarker, setSelectedMarker] = useState<ContentMarker | null>(null);
  const [htmlContent, setHtmlContent] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  
  // Save-target options: default to a copy so the original is never at risk.
  const [saveAsCopy, setSaveAsCopy] = useState(true);
  const [copyName, setCopyName] = useState("");
  const [modalError, setModalError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [updateToc, setUpdateToc] = useState(false);

  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .catch(() => setDocError("Could not reach the backend at /api. Is the FastAPI server running on :8000?"));
  }, []);

  function handleSelectDocument(path: string) {
    setSelectedPath(path);
    setBanner(null);
    loadEditableSections(path);
  }

  async function loadEditableSections(path: string) {
    setLoadingSections(true);
    setEditableSections([]);
    setSelectedSection(null);
    setContentMarkers([]);
    setSelectedMarker(null);
    setHtmlContent("");
    try {
      const res = await getEditableSections({ document_path: path });
      if (res.success && res.data) {
        setEditableSections(res.data.sections);
        if (res.data.sections.length === 0) {
          setBanner({ kind: "err", text: "No editable content found in this document." });
        }
      } else {
        setBanner({ kind: "err", text: res.message || "Failed to load editable sections." });
      }
    } catch {
      setBanner({ kind: "err", text: "Failed to load editable sections." });
    } finally {
      setLoadingSections(false);
    }
  }

  function handleSelectSection(section: EditableContent) {
    setSelectedSection(section);
    setBanner(null);
    loadContentMarkers(section);
  }

  async function loadContentMarkers(section: EditableContent) {
    setLoadingMarkers(true);
    setContentMarkers([]);
    setSelectedMarker(null);
    setHtmlContent("");
    try {
      const res = await getContentMarkers({
        document_path: selectedPath,
        section_bookmark: section.section_bookmark,
      });
      if (res.success && res.data) {
        setContentMarkers(res.data.markers);
      } else {
        setBanner({ kind: "err", text: res.message || "Failed to load content markers." });
      }
    } catch {
      setBanner({ kind: "err", text: "Failed to load content markers." });
    } finally {
      setLoadingMarkers(false);
    }
  }

  function handleSelectMarker(marker: ContentMarker) {
    setSelectedMarker(marker);
    setBanner(null);
    loadContentText(marker);
  }

  async function loadContentText(marker: ContentMarker) {
    setHtmlContent("");
    try {
      const res = await getContentText({
        document_path: selectedPath,
        logical_id: marker.logical_id,
      });
      if (res.success && res.data) {
        setHtmlContent(res.data.html_content);
        setCopyName(suggestCopyName(selectedPath));
        setModalOpen(true);
      } else {
        setBanner({ kind: "err", text: res.message || "Failed to load content text." });
      }
    } catch {
      setBanner({ kind: "err", text: "Failed to load content text." });
    }
  }

  async function handleReplaceContent() {
    if (!selectedPath || !selectedMarker) return;
    if (!htmlContent.trim()) {
      setModalError("Please provide HTML content.");
      return;
    }
    if (saveAsCopy && !copyName.trim()) {
      setModalError("Please provide a name for the copy.");
      return;
    }
    setReplacing(true);
    setModalError("");
    setBanner(null);

    try {
      const res = await replaceContentText({
        document_path: selectedPath,
        logical_id: selectedMarker.logical_id,
        new_html_content: htmlContent,
        save_as_copy: saveAsCopy,
        copy_name: saveAsCopy ? copyName.trim() : null,
        update_toc: updateToc,
      });

      if (res.success) {
        const outPath = res.data?.output_path ?? selectedPath;
        const madeCopy = res.data?.created_copy ?? false;
        setModalOpen(false);

        if (madeCopy) {
          try {
            setDocuments(await listDocuments());
          } catch {
            /* non-fatal: viewer below still targets the copy directly */
          }
        }

        setSelectedPath(outPath);
        await loadEditableSections(outPath);

        setBanner({
          kind: "ok",
          text: madeCopy
            ? `Content replaced in a new copy — the original is unchanged. Now viewing ${baseName(outPath)}.`
            : `Successfully replaced content and updated the document.`,
        });
      } else {
        setModalError(res.message || "Failed to replace content.");
      }
    } catch {
      setModalError("Failed to replace content. Please try again.");
    } finally {
      setReplacing(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Edit Content</h1>
          <p className="page-sub">
            Select a document to view sections with user-inserted content, then select a content block to edit.
          </p>
        </div>
      </header>

      {docError && <div className="banner banner-err">{docError}</div>}
      {banner && (
        <div className={`banner banner-${banner.kind === "ok" ? "ok" : "err"}`}>
          {banner.text}
        </div>
      )}

      <div className="panels">
        <div className="panel">
          <div className="panel-head">
            <label className="field-label">Document</label>
            <select
              value={selectedPath}
              onChange={(e) => handleSelectDocument(e.target.value)}
              className="select"
            >
              <option value="">Select a document...</option>
              {documents.map((doc) => (
                <option key={doc.path} value={doc.path}>
                  {doc.name}
                </option>
              ))}
            </select>
          </div>

          <div className="panel-body">
            {loadingSections && (
              <div className="viewer-state">
                <div className="spinner" />
                <span>Loading editable sections…</span>
              </div>
            )}

            {!loadingSections && selectedPath && editableSections.length > 0 && (
              <div className="toc-tree">
                <div className="form-group">
                  <label className="field-label">Sections with Editable Content</label>
                  <div className="editable-sections-list">
                    {editableSections.map((section) => (
                      <div
                        key={section.logical_id}
                        className={`editable-section-item ${selectedSection?.logical_id === section.logical_id ? "selected" : ""}`}
                        onClick={() => handleSelectSection(section)}
                      >
                        <div className="section-number">{section.section_number}</div>
                        <div className="section-title">{section.section_title}</div>
                        <div className="section-preview">{section.preview}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {!loadingSections && selectedPath && editableSections.length === 0 && (
              <div className="toc-empty">No editable content found in this document.</div>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <label className="field-label">Content Blocks</label>
          </div>
          <div className="panel-body">
            {!selectedSection && (
              <div className="viewer-state">
                <span>Select a section to view editable content blocks</span>
              </div>
            )}

            {selectedSection && loadingMarkers && (
              <div className="viewer-state">
                <div className="spinner" />
                <span>Loading content blocks…</span>
              </div>
            )}

            {selectedSection && !loadingMarkers && contentMarkers.length > 0 && (
              <div className="content-markers-list">
                {contentMarkers.map((marker) => (
                  <div
                    key={marker.logical_id}
                    className={`content-marker-item ${selectedMarker?.logical_id === marker.logical_id ? "selected" : ""}`}
                    onClick={() => handleSelectMarker(marker)}
                  >
                    <div className="marker-preview">{marker.preview}</div>
                  </div>
                ))}
              </div>
            )}

            {selectedSection && !loadingMarkers && contentMarkers.length === 0 && (
              <div className="toc-empty">No editable content blocks found in this section.</div>
            )}
          </div>
        </div>
      </div>

      {/* Edit Modal */}
      {modalOpen && (
        <div className="modal-overlay" onClick={() => setModalOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Edit Content</h2>
              <button
                className="modal-close"
                onClick={() => setModalOpen(false)}
              >
                ×
              </button>
            </div>

            <div className="modal-body">
              {selectedSection && (
                <div className="selected-section-info">
                  <strong>Section:</strong> {selectedSection.section_number} {selectedSection.section_title}
                </div>
              )}

              {selectedMarker && (
                <div className="selected-section-info">
                  <strong>Content Preview:</strong> {selectedMarker.preview}
                </div>
              )}

              <div className="form-group">
                <label>HTML Content</label>
                <textarea
                  value={htmlContent}
                  onChange={(e) => setHtmlContent(e.target.value)}
                  placeholder="<p>Your content here...</p>"
                  className="form-textarea"
                  rows={10}
                />
                <p className="form-hint">Supports: p, b, i, br, div, li tags</p>
              </div>

              <div className="form-group">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={saveAsCopy}
                    onChange={(e) => setSaveAsCopy(e.target.checked)}
                  />
                  Save as copy (recommended)
                </label>
              </div>

              {saveAsCopy && (
                <div className="form-group">
                  <label>Copy Name</label>
                  <input
                    type="text"
                    value={copyName}
                    onChange={(e) => setCopyName(e.target.value)}
                    placeholder="Document Name - Copy"
                    className="form-input"
                  />
                </div>
              )}

              <div className="form-group">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={updateToc}
                    onChange={(e) => setUpdateToc(e.target.checked)}
                  />
                  Update Table of Contents using Word COM automation
                </label>
                <p className="form-hint">
                  Requires Microsoft Word to be installed on the server. Updates TOC fields in the document after replacement.
                </p>
              </div>

              {modalError && <div className="banner banner-err">{modalError}</div>}
            </div>

            <div className="modal-footer">
              <button
                className="btn btn-secondary"
                onClick={() => setModalOpen(false)}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={handleReplaceContent}
                disabled={replacing}
              >
                {replacing ? "Replacing..." : "Replace Content"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
