import { useEffect, useState } from "react";
import {
  getToc,
  listDocuments,
  insertContent,
  type DocumentListItem,
} from "../api";
import {
  toTree,
  type TreeNode,
} from "../tree";
import TocTree from "../components/TocTree";
import DocViewer from "../components/DocViewer";

interface ContextMenuState {
  x: number;
  y: number;
  node: TreeNode;
}

/** Last path segment (handles both Windows and POSIX separators). */
function baseName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

/** Suggested copy name derived from a document path: "<stem> - Copy". */
function suggestCopyName(path: string): string {
  return `${baseName(path).replace(/\.docx$/i, "")} - Copy`;
}

export default function InsertContent() {
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [docError, setDocError] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [toc, setToc] = useState<TreeNode[]>([]);
  const [loadingToc, setLoadingToc] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  
  // Right-click context menu state
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  
  // Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<TreeNode | null>(null);
  
  // Form fields
  const [htmlContent, setHtmlContent] = useState("");
  const [imageData, setImageData] = useState<string | null>(null);
  const [imageCaption, setImageCaption] = useState("");
  const [imageWidth, setImageWidth] = useState<number>(5);
  const [imageHeight, setImageHeight] = useState<number>(3.75);
  const [highlight, setHighlight] = useState(false);
  const [inserting, setInserting] = useState(false);

  // Save-target options: default to a copy so the original is never at risk.
  const [saveAsCopy, setSaveAsCopy] = useState(true);
  const [copyName, setCopyName] = useState("");
  const [modalError, setModalError] = useState("");
  
  // Viewer reload key
  const [viewerKey, setViewerKey] = useState(0);

  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .catch(() => setDocError("Could not reach the backend at /api. Is the FastAPI server running on :8000?"));

    // Close context menu on click elsewhere
    const handleCloseMenu = () => setContextMenu(null);
    window.addEventListener("click", handleCloseMenu);
    return () => window.removeEventListener("click", handleCloseMenu);
  }, []);

  async function loadToc(path: string) {
    if (!path) {
      setToc([]);
      return;
    }
    setLoadingToc(true);
    setBanner(null);
    try {
      const items = await getToc(path);
      setToc(toTree(items, "ins"));
    } catch {
      setBanner({ kind: "err", text: "Failed to load the document's table of contents." });
    } finally {
      setLoadingToc(false);
    }
  }

  function handleSelectDocument(path: string) {
    setSelectedPath(path);
    setBanner(null);
    loadToc(path);
  }

  function handleNodeContextMenu(e: React.MouseEvent, node: TreeNode) {
    e.preventDefault();
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      node,
    });
  }

  function handleOpenInsertModal() {
    if (!contextMenu) return;
    const node = contextMenu.node;
    setSelectedNode(node);
    setHtmlContent("");
    setImageData(null);
    setImageCaption("");
    setHighlight(false);
    setSaveAsCopy(true);
    setCopyName(suggestCopyName(selectedPath));
    setModalError("");
    setModalOpen(true);
    setContextMenu(null);
  }

  function handleImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        setImageData(event.target?.result as string);
      };
      reader.readAsDataURL(file);
    }
  }

  async function handleInsertContent() {
    if (!selectedPath || !selectedNode) return;
    if (!htmlContent && !imageData) {
      setModalError("Please provide HTML content or an image.");
      return;
    }
    if (saveAsCopy && !copyName.trim()) {
      setModalError("Please provide a name for the copy.");
      return;
    }
    setInserting(true);
    setModalError("");
    setBanner(null);

    try {
      const res = await insertContent({
        document_path: selectedPath,
        section_bookmark: selectedNode.bookmark,
        html_content: htmlContent,
        image_data: imageData,
        image_caption: imageCaption || null,
        image_width: imageData ? imageWidth : null,
        image_height: imageData ? imageHeight : null,
        highlight,
        save_as_copy: saveAsCopy,
        copy_name: saveAsCopy ? copyName.trim() : null,
      });

      if (res.success) {
        const outPath = res.data?.output_path ?? selectedPath;
        const madeCopy = res.data?.created_copy ?? false;
        setModalOpen(false);

        if (madeCopy) {
          try {
            setDocuments(await listDocuments());
          } catch {
            /* non-fatal: viewer/TOC below still target the copy directly */
          }
        }

        setSelectedPath(outPath);
        setViewerKey((prev) => prev + 1);
        await loadToc(outPath);

        setBanner({
          kind: "ok",
          text: madeCopy
            ? `Content inserted into a new copy — the original is unchanged. Now viewing ${baseName(outPath)}.`
            : `Successfully inserted content and updated the document.`,
        });
        
        // Reset form
        setHtmlContent("");
        setImageData(null);
        setImageCaption("");
      } else {
        setModalError(res.message || "Failed to insert content.");
      }
    } catch (e) {
      setModalError(e instanceof Error ? e.message : "Request failed.");
    } finally {
      setInserting(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Insert Content</h1>
          <p className="page-sub">
            Select a document, right-click on any section in the table of contents, and click
            "Insert Content" to add HTML content and images at the end of that section.
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
            {loadingToc && (
              <div className="viewer-state">
                <div className="spinner" />
                <span>Loading table of contents…</span>
              </div>
            )}

            {!loadingToc && selectedPath && toc.length > 0 && (
              <div className="toc-tree">
                <TocTree
                  nodes={toc}
                  variant="plain"
                  onNodeContextMenu={handleNodeContextMenu}
                />
              </div>
            )}

            {!loadingToc && selectedPath && toc.length === 0 && (
              <div className="toc-empty">No table of contents found in this document.</div>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <label className="field-label">Preview</label>
          </div>
          <div className="panel-body">
            {selectedPath ? (
              <DocViewer key={viewerKey} path={selectedPath} />
            ) : (
              <div className="viewer-state">
                <span>Select a document to preview</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Context Menu */}
      {contextMenu && (
        <div
          className="context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button className="context-menu-item" onClick={handleOpenInsertModal}>
            Insert Content here
          </button>
        </div>
      )}

      {/* Modal */}
      {modalOpen && (
        <div className="modal-overlay" onClick={() => setModalOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Insert Content</h2>
              <button
                className="modal-close"
                onClick={() => setModalOpen(false)}
              >
                ×
              </button>
            </div>

            <div className="modal-body">
              {selectedNode && (
                <div className="selected-section-info">
                  <strong>Selected Section:</strong> {selectedNode.section_number} {selectedNode.item_text}
                </div>
              )}

              <div className="form-group">
                <label>HTML Content</label>
                <textarea
                  value={htmlContent}
                  onChange={(e) => setHtmlContent(e.target.value)}
                  placeholder="<p>Your content here...</p>"
                  className="form-textarea"
                  rows={6}
                />
                <p className="form-hint">Supports: p, b, i, br, div, li tags</p>
              </div>

              <div className="form-group">
                <label>Image</label>
                <input
                  type="file"
                  accept="image/*"
                  onChange={handleImageUpload}
                  className="form-input"
                />
                {imageData && (
                  <div className="image-preview">
                    <img src={imageData} alt="Preview" style={{ maxWidth: "200px", maxHeight: "200px" }} />
                    <button
                      type="button"
                      onClick={() => setImageData(null)}
                      className="btn btn-secondary"
                    >
                      Remove
                    </button>
                  </div>
                )}
              </div>

              {imageData && (
                <>
                  <div className="form-group">
                    <label>Image Caption</label>
                    <input
                      type="text"
                      value={imageCaption}
                      onChange={(e) => setImageCaption(e.target.value)}
                      placeholder="Figure: Description"
                      className="form-input"
                    />
                  </div>
                  <div className="form-group">
                    <label>Image Width (inches)</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0.5"
                      max="10"
                      value={imageWidth}
                      onChange={(e) => setImageWidth(parseFloat(e.target.value) || 5)}
                      className="form-input"
                    />
                  </div>
                  <div className="form-group">
                    <label>Image Height (inches)</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0.5"
                      max="10"
                      value={imageHeight}
                      onChange={(e) => setImageHeight(parseFloat(e.target.value) || 3.75)}
                      className="form-input"
                    />
                  </div>
                </>
              )}

              <div className="form-group">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={highlight}
                    onChange={(e) => setHighlight(e.target.checked)}
                  />
                  Highlight content
                </label>
              </div>

              <div className="form-group">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={saveAsCopy}
                    onChange={(e) => setSaveAsCopy(e.target.checked)}
                  />
                  Save as a copy
                </label>
              </div>

              {saveAsCopy && (
                <div className="form-group">
                  <label>Copy Name</label>
                  <input
                    type="text"
                    value={copyName}
                    onChange={(e) => setCopyName(e.target.value)}
                    placeholder="DocumentName_v2.docx"
                    className="form-input"
                  />
                </div>
              )}

              {modalError && <div className="form-error">{modalError}</div>}
            </div>

            <div className="modal-footer">
              <button
                onClick={() => setModalOpen(false)}
                className="btn btn-secondary"
              >
                Cancel
              </button>
              <button
                onClick={handleInsertContent}
                disabled={inserting}
                className="btn btn-primary"
              >
                {inserting ? "Inserting..." : "Insert Content"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
