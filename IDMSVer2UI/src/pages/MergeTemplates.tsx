import { useEffect, useMemo, useRef, useState } from "react";
import {
  getToc,
  listDocuments,
  mergeSection,
  type DocumentListItem,
} from "../api";
import {
  cloneTree,
  findById,
  flatten,
  insertAfter,
  makePreviewSubtree,
  nextSameOrHigherBookmark,
  renumber,
  toTree,
  type TreeNode,
} from "../tree";
import TocTree from "../components/TocTree";
import DocViewer from "../components/DocViewer";

interface Pending {
  sourceStart: string;
  sourceStop: string | null;
  insertBefore: string | null;
  sourceLabel: string;
  targetLabel: string;
}

export default function MergeTemplates() {
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [docError, setDocError] = useState("");

  const [masterPath, setMasterPath] = useState("");
  const [associatedPath, setAssociatedPath] = useState("");

  const [masterOriginal, setMasterOriginal] = useState<TreeNode[]>([]);
  const [masterPreview, setMasterPreview] = useState<TreeNode[]>([]);
  const [associated, setAssociated] = useState<TreeNode[]>([]);

  const [loadingMaster, setLoadingMaster] = useState(false);
  const [loadingAssoc, setLoadingAssoc] = useState(false);

  const [pending, setPending] = useState<Pending | null>(null);
  const draggedRef = useRef<TreeNode | null>(null);

  const [merging, setMerging] = useState(false);
  const [mergedPath, setMergedPath] = useState<string | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [mergeName, setMergeName] = useState("");
  const [updateToc, setUpdateToc] = useState(false);

  const mergeNameValid = /\.docx$/i.test(mergeName.trim());

  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .catch(() => setDocError("Could not reach the backend at /api. Is the FastAPI server running on :8000?"));
  }, []);

  const associatedOptions = useMemo(
    () => documents.filter((d) => d.path !== masterPath),
    [documents, masterPath]
  );

  const locked = pending !== null;

  async function onSelectMaster(path: string) {
    setMasterPath(path);
    setAssociatedPath("");
    setAssociated([]);
    setPending(null);
    setMergedPath(null);
    setBanner(null);
    draggedRef.current = null;
    if (!path) {
      setMasterOriginal([]);
      setMasterPreview([]);
      return;
    }
    setLoadingMaster(true);
    try {
      const tree = toTree(await getToc(path), "m");
      setMasterOriginal(tree);
      setMasterPreview(cloneTree(tree));
    } catch {
      setBanner({ kind: "err", text: "Failed to load the master template's table of contents." });
    } finally {
      setLoadingMaster(false);
    }
  }

  async function onSelectAssociated(path: string) {
    setAssociatedPath(path);
    setPending(null);
    setMasterPreview(cloneTree(masterOriginal));
    draggedRef.current = null;
    if (!path) {
      setAssociated([]);
      return;
    }
    setLoadingAssoc(true);
    try {
      setAssociated(toTree(await getToc(path), "s"));
    } catch {
      setBanner({ kind: "err", text: "Failed to load the associated template's table of contents." });
    } finally {
      setLoadingAssoc(false);
    }
  }

  function onDropOnMaster(target: TreeNode) {
    if (locked) return;
    const src = draggedRef.current;
    if (!src) return;

    const assocFlat = flatten(associated);
    const masterFlat = flatten(masterOriginal);
    const sourceStart = src.bookmark;
    const sourceStop = nextSameOrHigherBookmark(assocFlat, src.id);
    const insertBefore = nextSameOrHigherBookmark(masterFlat, target.id);

    const preview = cloneTree(masterOriginal);
    const anchor = findById(preview, target.id);
    if (!anchor) return;
    const subtree = makePreviewSubtree(src);
    insertAfter(preview, target.id, subtree);
    renumber(preview);

    setMasterPreview(preview);
    setPending({
      sourceStart,
      sourceStop,
      insertBefore,
      sourceLabel: src.item_text,
      targetLabel: target.item_text,
    });
    draggedRef.current = null;
    setBanner(null);
  }

  function onCancel() {
    setPending(null);
    setMasterPreview(cloneTree(masterOriginal));
    draggedRef.current = null;
    setBanner(null);
  }

  async function onMerge() {
    if (!pending || !masterPath || !associatedPath || !mergeNameValid) return;
    setMerging(true);
    setBanner(null);
    try {
      const res = await mergeSection({
        master_template_path: masterPath,
        source_document_path: associatedPath,
        source_start_bookmark: pending.sourceStart,
        source_stop_bookmark: pending.sourceStop,
        insert_before_bookmark: pending.insertBefore,
        output_filename: mergeName.trim(),
        update_toc: updateToc,
      });
      if (res.success && res.data) {
        setMergedPath(res.data.output_path);
        setViewerOpen(true);
        setPending(null);
        setMasterPreview(cloneTree(masterOriginal));
        setBanner({ kind: "ok", text: `Merged document saved to ${res.data.output_path}` });
      } else {
        setBanner({ kind: "err", text: res.message || "Merge failed." });
      }
    } catch (e) {
      setBanner({ kind: "err", text: e instanceof Error ? e.message : "Merge request failed." });
    } finally {
      setMerging(false);
    }
  }

  const masterName = documents.find((d) => d.path === masterPath)?.name ?? "";
  const associatedName = documents.find((d) => d.path === associatedPath)?.name ?? "";

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Merge Templates</h1>
          <p className="page-sub">
            Select a master and an associated template, then drag a section from the associated
            table of contents onto the master to merge it in.
          </p>
        </div>
        <div className="action-bar">
          <button className="btn btn-ghost" onClick={onCancel} disabled={!pending || merging}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={onMerge}
            disabled={!pending || merging || !mergeNameValid}
            title={!mergeNameValid ? "Enter a Merge Document Name ending in .docx" : undefined}
          >
            {merging ? "Merging…" : "Merge"}
          </button>
        </div>
      </header>

      <div className="merge-name-bar">
        <label className="merge-name-label" htmlFor="mergeName">
          Merge Document Name
        </label>
        <div className="merge-name-field">
          <input
            id="mergeName"
            className={"merge-name-input" + (mergeName && !mergeNameValid ? " invalid" : "")}
            type="text"
            placeholder="e.g. ICSS_with_FF_Integration.docx"
            value={mergeName}
            spellCheck={false}
            onChange={(e) => setMergeName(e.target.value)}
          />
          {mergeName.trim() && !mergeNameValid && (
            <span className="merge-name-hint">The name must end with <code>.docx</code></span>
          )}
        </div>
      </div>

      <div className="merge-name-bar">
        <label className="merge-name-label">Options</label>
        <div className="merge-name-field">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={updateToc}
              onChange={(e) => setUpdateToc(e.target.checked)}
            />
            Update Table of Contents using Word COM automation
          </label>
          <p className="form-hint">
            Requires Microsoft Word to be installed on the server. Updates TOC fields in the merged document.
          </p>
        </div>
      </div>

      {docError && <div className="banner err">{docError}</div>}
      {banner && <div className={"banner " + (banner.kind === "ok" ? "ok" : "err")}>{banner.text}</div>}

      {pending && (
        <div className="pending-strip">
          <span className="pending-dot" />
          Ready to merge <strong>{pending.sourceLabel}</strong> into the master after{" "}
          <strong>{pending.targetLabel}</strong>. Click <strong>Merge</strong> to apply, or{" "}
          <strong>Cancel</strong> to choose a different section.
        </div>
      )}

      <div className="panels">
        {/* Master panel */}
        <section className="panel">
          <div className="panel-head">
            <label className="field-label">Master Template</label>
            <select
              className="select"
              value={masterPath}
              disabled={locked}
              onChange={(e) => onSelectMaster(e.target.value)}
            >
              <option value="">— Select master template —</option>
              {documents.map((d) => (
                <option key={d.path} value={d.path}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>
          <div className="panel-body">
            {loadingMaster ? (
              <div className="toc-empty">
                <div className="spinner" /> Loading table of contents…
              </div>
            ) : masterPath ? (
              <TocTree
                nodes={masterPreview}
                variant="target"
                canDrop={!locked}
                onNodeDrop={onDropOnMaster}
                emptyText="This document has no detectable table of contents."
              />
            ) : (
              <div className="toc-empty muted">Select a master template to view its contents.</div>
            )}
          </div>
        </section>

        {/* Associated panel */}
        <section className="panel">
          <div className="panel-head">
            <label className="field-label">Associated Template</label>
            <select
              className="select"
              value={associatedPath}
              disabled={!masterPath || locked}
              onChange={(e) => onSelectAssociated(e.target.value)}
            >
              <option value="">
                {masterPath ? "— Select associated template —" : "— Select a master first —"}
              </option>
              {associatedOptions.map((d) => (
                <option key={d.path} value={d.path}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>
          <div className="panel-body">
            {loadingAssoc ? (
              <div className="toc-empty">
                <div className="spinner" /> Loading table of contents…
              </div>
            ) : associatedPath ? (
              <TocTree
                nodes={associated}
                variant="source"
                onNodeDragStart={(n) => (draggedRef.current = n)}
                onNodeDragEnd={() => {
                  /* keep ref until drop handles it */
                }}
                emptyText="This document has no detectable table of contents."
              />
            ) : (
              <div className="toc-empty muted">
                {masterPath
                  ? "Select an associated template, then drag a section onto the master."
                  : "Disabled until a master template is selected."}
              </div>
            )}
          </div>
        </section>
      </div>

      {viewerOpen && mergedPath && (
        <div className="modal-overlay" onClick={() => setViewerOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h2>Merged document</h2>
                <span className="modal-path">{mergedPath}</span>
              </div>
              <button className="btn btn-ghost" onClick={() => setViewerOpen(false)}>
                Close
              </button>
            </div>
            <div className="modal-body">
              <DocViewer path={mergedPath} />
            </div>
            <div className="modal-foot">
              <span className="merge-summary">
                {masterName} <span className="arrow">←</span> {associatedName}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
