import { useEffect, useState } from "react";
import {
  getToc,
  listDocuments,
  deleteSections,
  type DocumentListItem,
} from "../api";
import {
  toTree,
  flatten,
  nextSameOrHigherBookmark,
  type TreeNode,
} from "../tree";
import TocTree from "../components/TocTree";
import DocViewer from "../components/DocViewer";

interface ContextMenuState {
  x: number;
  y: number;
  node: TreeNode;
}

export default function DeleteSection() {
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [docError, setDocError] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [toc, setToc] = useState<TreeNode[]>([]);
  const [loadingToc, setLoadingToc] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  
  // Right-click context menu state
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  
  // Confirmation modal state
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<TreeNode | null>(null);
  const [deleting, setDeleting] = useState(false);
  
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
      setToc(toTree(items, "del"));
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

  function handleOpenConfirmModal() {
    if (!contextMenu) return;
    const node = contextMenu.node;
    setSelectedNode(node);
    setConfirmOpen(true);
    setContextMenu(null);
  }

  async function handleDeleteSection() {
    if (!selectedPath || !selectedNode) return;
    
    setDeleting(true);
    setBanner(null);

    try {
      // Get the stop bookmark (next same or higher level bookmark)
      const flatToc = flatten(toc);
      const stopBookmark = nextSameOrHigherBookmark(flatToc, selectedNode.id);
      
      if (!stopBookmark) {
        setBanner({ kind: "err", text: "Could not determine section boundaries." });
        return;
      }
      
      const sections: Record<string, string> = {};
      sections[selectedNode.bookmark] = stopBookmark;

      const res = await deleteSections({
        document_path: selectedPath,
        sections,
        track_in_history: false,
      });

      if (res.success) {
        setConfirmOpen(false);
        setViewerKey((prev) => prev + 1);
        await loadToc(selectedPath);
        setBanner({
          kind: "ok",
          text: `Successfully deleted section: ${selectedNode.section_number} ${selectedNode.item_text}`,
        });
      } else {
        setBanner({ kind: "err", text: res.message || "Failed to delete section." });
      }
    } catch (e) {
      setBanner({ kind: "err", text: e instanceof Error ? e.message : "Delete request failed." });
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Delete Section</h1>
          <p className="page-sub">
            Select a document, right-click on any section in the table of contents, and click
            "Delete This Section" to remove it and all its children from the document.
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
          <button className="context-menu-item" onClick={handleOpenConfirmModal}>
            Delete This Section
          </button>
        </div>
      )}

      {/* Confirmation Modal */}
      {confirmOpen && selectedNode && (
        <div className="modal-overlay" onClick={() => setConfirmOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Confirm Delete</h2>
              <button
                className="modal-close"
                onClick={() => setConfirmOpen(false)}
              >
                ×
              </button>
            </div>

            <div className="modal-body">
              <div className="selected-section-info">
                <strong>Section to delete:</strong> {selectedNode.section_number} {selectedNode.item_text}
              </div>
              <p className="warning-text">
                This will delete the selected section and all its children. This action cannot be undone.
              </p>
              <p>Are you sure you want to proceed?</p>
            </div>

            <div className="modal-footer">
              <button
                onClick={() => setConfirmOpen(false)}
                className="btn btn-secondary"
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteSection}
                disabled={deleting}
                className="btn btn-primary"
              >
                {deleting ? "Deleting..." : "Delete Section"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
