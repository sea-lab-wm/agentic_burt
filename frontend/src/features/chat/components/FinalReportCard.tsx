type FinalReportCardProps = {
  report: Record<string, unknown>;
};

function formatLabel(label: string): string {
  return label
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function renderValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  if (Array.isArray(value)) {
    return value.join(", ");
  }

  return JSON.stringify(value, null, 2);
}

export function FinalReportCard({ report }: FinalReportCardProps) {
  const entries = Object.entries(report);

  return (
    <section className="final-report-card">
      <div className="final-report-card__header">
        <span className="final-report-card__eyebrow">BURT++ complete</span>
        <h2>Draft report</h2>
      </div>
      <div className="final-report-card__body">
        {entries.map(([key, value]) => (
          <article key={key} className="final-report-card__row">
            <h3>{formatLabel(key)}</h3>
            <p>{renderValue(value)}</p>
          </article>
        ))}
      </div>
      <details className="final-report-card__raw">
        <summary>Raw response</summary>
        <pre>{JSON.stringify(report, null, 2)}</pre>
      </details>
    </section>
  );
}
