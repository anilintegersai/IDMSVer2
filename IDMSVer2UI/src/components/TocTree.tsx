import { useState } from "react";
import type { TreeNode } from "../tree";

interface Props {
  nodes: TreeNode[];
  variant: "source" | "target" | "plain";
  canDrop?: boolean;
  onNodeDragStart?: (n: TreeNode) => void;
  onNodeDragEnd?: () => void;
  onNodeDrop?: (target: TreeNode) => void;
  onNodeContextMenu?: (e: React.MouseEvent, node: TreeNode) => void;
  emptyText?: string;
}

export default function TocTree({
  nodes,
  variant,
  canDrop,
  onNodeDragStart,
  onNodeDragEnd,
  onNodeDrop,
  onNodeContextMenu,
  emptyText,
}: Props) {
  const [hoverId, setHoverId] = useState<string | null>(null);

  if (!nodes.length) {
    return <div className="toc-empty">{emptyText ?? "No table of contents found."}</div>;
  }

  const isSource = variant === "source";
  const isTarget = variant === "target" && !!canDrop;

  const renderNode = (node: TreeNode, depth: number): JSX.Element => (
    <div key={node.id} className="toc-branch">
      <div
        className={
          "toc-row" +
          (node.isNew ? " is-new" : "") +
          (isSource ? " draggable" : "") +
          (hoverId === node.id ? " drop-hover" : "")
        }
        style={{ paddingLeft: 12 + depth * 18 }}
        draggable={isSource}
        onDragStart={
          isSource
            ? (e) => {
                e.dataTransfer.effectAllowed = "copy";
                e.dataTransfer.setData("text/plain", node.bookmark);
                onNodeDragStart?.(node);
              }
            : undefined
        }
        onDragEnd={isSource ? () => onNodeDragEnd?.() : undefined}
        onDragOver={
          isTarget
            ? (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "copy";
                if (hoverId !== node.id) setHoverId(node.id);
              }
            : undefined
        }
        onDragLeave={isTarget ? () => setHoverId((h) => (h === node.id ? null : h)) : undefined}
        onDrop={
          isTarget
            ? (e) => {
                e.preventDefault();
                setHoverId(null);
                onNodeDrop?.(node);
              }
            : undefined
        }
        onContextMenu={
          onNodeContextMenu
            ? (e) => {
                onNodeContextMenu(e, node);
              }
            : undefined
        }
        title={node.item_text}
      >
        {isSource && (
          <span className="drag-handle" aria-hidden>
            ⠿
          </span>
        )}
        {node.section_number && <span className="toc-num">{node.section_number}</span>}
        <span className="toc-text">{node.item_text}</span>
        {node.isNew && <span className="new-chip">inserted</span>}
        {node.page_no && <span className="toc-page">{node.page_no}</span>}
      </div>
      {node.children.length > 0 && (
        <div className="toc-children">{node.children.map((c) => renderNode(c, depth + 1))}</div>
      )}
    </div>
  );

  return <div className={"toc-tree" + (isTarget ? " droppable" : "")}>{nodes.map((n) => renderNode(n, 0))}</div>;
}
