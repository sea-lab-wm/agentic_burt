import { useState } from "react";

type FinalReportCardProps = {
  report: Record<string, unknown>;
  heading?: string;
  onSave?: (report: Record<string, unknown>) => Promise<void>;
};

function formatLabel(label: string): string {
  return label
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function isStepsToReproduceKey(key: string): boolean {
  return key.replace(/[_-]/g, " ").toLowerCase() === "steps to reproduce";
}

function stripStepIdentifier(step: string): string {
  return step.replace(/\s*<[^>\n]+>\s*$/u, "");
}

function sanitizeStepsToReproduce(value: unknown): unknown {
  if (typeof value === "string") {
    return value
      .split("\n")
      .map((line) => stripStepIdentifier(line))
      .join("\n");
  }

  if (Array.isArray(value)) {
    return value.map((step) =>
      typeof step === "string" ? stripStepIdentifier(step) : step,
    );
  }

  return value;
}

export function sanitizeReportForDisplay(
  report: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(report).map(([key, value]) => [
      key,
      isStepsToReproduceKey(key) ? sanitizeStepsToReproduce(value) : value,
    ]),
  );
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

export function FinalReportCard({
  report,
  heading = "Draft report",
  onSave,
}: FinalReportCardProps) {
  const displayReport = sanitizeReportForDisplay(report);
  const entries = Object.entries(displayReport);
  const [isEditing, setIsEditing] = useState(false);
  const [editorValue, setEditorValue] = useState(() =>
    JSON.stringify(displayReport, null, 2),
  );
  const [editorError, setEditorError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  function openEditor(): void {
    setEditorValue(JSON.stringify(displayReport, null, 2));
    setEditorError(null);
    setIsEditing(true);
  }

  async function saveEditedReport(): Promise<void> {
    let parsedReport: unknown;

    try {
      parsedReport = JSON.parse(editorValue);
    } catch {
      setEditorError("Enter a valid JSON object before saving.");
      return;
    }

    if (
      parsedReport === null ||
      typeof parsedReport !== "object" ||
      Array.isArray(parsedReport)
    ) {
      setEditorError("The report must be a JSON object.");
      return;
    }

    setIsSaving(true);
    setEditorError(null);

    try {
      await onSave?.(parsedReport as Record<string, unknown>);
      setIsEditing(false);
    } catch (error) {
      setEditorError(error instanceof Error ? error.message : "Unable to save report.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section className="final-report-card">
      <div className="final-report-card__header">
        <div>
          <span className="final-report-card__eyebrow">BURT++ complete</span>
          <h2>{heading}</h2>
        </div>
        {onSave ? (
          <button className="final-report-card__edit" type="button" onClick={openEditor}>
            Edit
          </button>
        ) : null}
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
        <pre>{JSON.stringify(displayReport, null, 2)}</pre>
      </details>
      {isEditing ? (
        <div className="report-editor" role="dialog" aria-modal="true" aria-label="Edit bug report">
          <div className="report-editor__panel">
            <div className="report-editor__header">
              <h2>Edit report</h2>
              <button
                className="report-editor__close"
                type="button"
                onClick={() => setIsEditing(false)}
                aria-label="Close editor"
              >
                X
              </button>
            </div>
            <textarea
              className="report-editor__textarea"
              aria-label="Bug report JSON"
              value={editorValue}
              onChange={(event) => setEditorValue(event.target.value)}
              spellCheck={false}
            />
            {editorError ? <p className="report-editor__error">{editorError}</p> : null}
            <div className="report-editor__actions">
              <button
                className="report-editor__secondary"
                type="button"
                onClick={() => setIsEditing(false)}
                disabled={isSaving}
              >
                Cancel
              </button>
              <button
                className="report-editor__save"
                type="button"
                onClick={() => {
                  void saveEditedReport();
                }}
                disabled={isSaving}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
