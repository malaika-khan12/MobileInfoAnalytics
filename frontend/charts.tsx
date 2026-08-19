"use client";

export function SourceBars({ rows }: { rows: { source_domain?: unknown; total_listings?: unknown }[] }) {
  const max = Math.max(1, ...rows.map((row) => Number(row.total_listings) || 0));
  return (
    <div className="source-coverage" role="img" aria-label="Listings by source">
      {rows.map((row) => {
        const label = String(row.source_domain || "unknown");
        const value = Number(row.total_listings) || 0;
        return <div className="coverage-row" key={label}><span className="coverage-source">{label}</span><div className="coverage-track"><i style={{ width: `${(value / max) * 100}%` }} /></div><strong>{value.toLocaleString()}</strong></div>;
      })}
    </div>
  );
}
