import { useEffect, useRef, useState } from "react";
import { renderAsync } from "docx-preview";
import { fetchDocxBlob } from "../api";

/** Renders a .docx (fetched from the backend) inline using docx-preview. */
export default function DocViewer({ path }: { path: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    (async () => {
      try {
        const blob = await fetchDocxBlob(path);
        if (cancelled || !ref.current) return;
        ref.current.innerHTML = "";
        await renderAsync(blob, ref.current, undefined, {
          className: "docx",
          inWrapper: true,
          breakPages: true,
          ignoreLastRenderedPageBreak: true,
          experimental: true,
        });
        if (!cancelled) setStatus("ready");
      } catch (e) {
        if (!cancelled) {
          setStatus("error");
          setMessage(e instanceof Error ? e.message : "Failed to render document.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [path]);

  return (
    <div className="doc-viewer">
      {status === "loading" && (
        <div className="viewer-state">
          <div className="spinner" />
          <span>Rendering document…</span>
        </div>
      )}
      {status === "error" && (
        <div className="viewer-state error">
          <span>Could not render the document.</span>
          <small>{message}</small>
        </div>
      )}
      <div className="docx-host" ref={ref} style={{ display: status === "ready" ? "block" : "none" }} />
    </div>
  );
}
