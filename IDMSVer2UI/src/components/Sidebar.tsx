import { NavLink } from "react-router-dom";

interface MenuEntry {
  to: string;
  label: string;
  icon: JSX.Element;
}

const MENU: MenuEntry[] = [
  {
    to: "/merge-templates",
    label: "Merge Templates",
    icon: (
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M8 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h6" />
        <path d="M13 20h6a1 1 0 0 0 1-1V9l-5-5h-2" />
        <path d="M11 12h8m0 0-2.5-2.5M19 12l-2.5 2.5" />
      </svg>
    ),
  },
  {
    to: "/insert-content",
    label: "Insert Content",
    icon: (
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
        <rect x="4" y="4" width="16" height="16" rx="1.5" />
        <path d="M8 9h8M8 13h8M8 17h5" />
      </svg>
    ),
  },
  {
    to: "/edit-content",
    label: "Edit Content",
    icon: (
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
      </svg>
    ),
  },
  {
    to: "/delete-section",
    label: "Delete Section",
    icon: (
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M3 6h18M8 6V4h8v2M10 11v6M14 11v6M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      </svg>
    ),
  },
  {
    to: "/toc-viewer",
    label: "TOC",
    icon: (
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M4 6h16M4 12h16M4 18h16" />
        <path d="M8 6v12M12 6v12M16 6v12" />
      </svg>
    ),
  },
];

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">ID</div>
        <div className="brand-text">
          <span className="brand-title">IDMS</span>
          <span className="brand-sub">Document Automation</span>
        </div>
      </div>
      <nav className="menu">
        {MENU.map((m) => (
          <NavLink
            key={m.to}
            to={m.to}
            className={({ isActive }) => "menu-item" + (isActive ? " active" : "")}
          >
            <span className="menu-icon">{m.icon}</span>
            <span>{m.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer">v1.0 · Phase 1</div>
    </aside>
  );
}
