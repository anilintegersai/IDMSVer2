interface Props {
  title: string;
  description: string;
}

export default function Placeholder({ title, description }: Props) {
  return (
    <div className="page">
      <header className="page-header">
        <h1>{title}</h1>
      </header>
      <div className="placeholder-card">
        <div className="placeholder-icon">
          <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" strokeWidth="1.4">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M8 12h8M12 8v8" />
          </svg>
        </div>
        <h2>{title}</h2>
        <p>{description}</p>
        <span className="badge-soon">Coming soon</span>
      </div>
    </div>
  );
}
