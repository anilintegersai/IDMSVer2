import type { TocItem } from "./api";

/** A TOC node enriched with a stable client id + preview flags. */
export interface TreeNode {
  id: string;
  section_number: string;
  item_text: string;
  page_no: string;
  bookmark: string;
  level: number;
  isNew?: boolean; // inserted during a drag-drop preview
  children: TreeNode[];
}

let counter = 0;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

/** Convert API TocItems into TreeNodes with unique client ids. */
export function toTree(items: TocItem[], prefix = "m"): TreeNode[] {
  return items.map((it) => ({
    id: nextId(prefix),
    section_number: it.section_number,
    item_text: it.item_text,
    page_no: it.page_no,
    bookmark: it.bookmark,
    level: it.level,
    children: toTree(it.children ?? [], prefix),
  }));
}

export function cloneTree(nodes: TreeNode[]): TreeNode[] {
  return nodes.map((n) => ({ ...n, children: cloneTree(n.children) }));
}

/** Depth-first pre-order flatten. */
export function flatten(nodes: TreeNode[], out: TreeNode[] = []): TreeNode[] {
  for (const n of nodes) {
    out.push(n);
    flatten(n.children, out);
  }
  return out;
}

export function findById(nodes: TreeNode[], id: string): TreeNode | null {
  for (const n of nodes) {
    if (n.id === id) return n;
    const hit = findById(n.children, id);
    if (hit) return hit;
  }
  return null;
}

/**
 * The bookmark of the first node AFTER `node`'s whole subtree — i.e. the next
 * sibling-or-higher heading. Used both as the source section's exclusive stop
 * and as the master insert-before target. Returns null if `node` is last.
 */
export function nextSameOrHigherBookmark(flat: TreeNode[], nodeId: string): string | null {
  const idx = flat.findIndex((n) => n.id === nodeId);
  if (idx === -1) return null;
  const level = flat[idx].level;
  for (let j = idx + 1; j < flat.length; j++) {
    if (flat[j].level <= level) return flat[j].bookmark;
  }
  return null;
}

/** Insert `subtree` immediately after `targetId`, as its next sibling. */
export function insertAfter(nodes: TreeNode[], targetId: string, subtree: TreeNode): boolean {
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i].id === targetId) {
      nodes.splice(i + 1, 0, subtree);
      return true;
    }
    if (insertAfter(nodes[i].children, targetId, subtree)) return true;
  }
  return false;
}

/** Recompute hierarchical section numbers purely from nesting (1, 1.1, 1.2, 2 …). */
export function renumber(nodes: TreeNode[], prefix: number[] = []): void {
  nodes.forEach((n, i) => {
    const num = [...prefix, i + 1];
    n.section_number = num.join(".");
    renumber(n.children, num);
  });
}

/** Deep-clone a dragged source node into a fresh preview subtree (flagged new). */
export function makePreviewSubtree(source: TreeNode): TreeNode {
  const clone = (n: TreeNode): TreeNode => ({
    ...n,
    id: nextId("ins"),
    isNew: true,
    children: n.children.map(clone),
  });
  return clone(source);
}
