import { useEffect, useState } from "react";

import { fetchReportMedia } from "../../../services/api/sessionApi";
import type { ReportMediaResponse } from "../types/api";
import { ReportSectionList } from "./ReportSectionList";
import { formatLabel, groupReportSections } from "./reportSections";
import {
  buildStepViews,
  isStepsToReproduceKey,
  readStepLines,
  sanitizeStepsToReproduce,
  stripStepNumber,
} from "./reportSteps";

type FinalReportCardProps = {
  report: Record<string, unknown>;
  heading?: string;
  sessionId?: string;
  onSave?: (report: Record<string, unknown>) => Promise<void>;
};

type EditableField = {
  key: string;
  label: string;
  text: string;
  originalValue: unknown;
};

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

function isPrimitiveValue(value: unknown): boolean {
  return (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

function isPrimitiveList(value: unknown): value is unknown[] {
  return Array.isArray(value) && value.every(isPrimitiveValue);
}

function toEditableText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  if (isPrimitiveList(value)) {
    return value.map(String).join("\n");
  }

  return JSON.stringify(value, null, 2);
}

export function buildEditableFields(
  report: Record<string, unknown>,
): EditableField[] {
  return Object.entries(report).map(([key, value]) => ({
    key,
    label: formatLabel(key),
    text: toEditableText(value),
    originalValue: value,
  }));
}

function parseFieldText(field: EditableField): unknown {
  const { originalValue, text } = field;

  if (typeof originalValue === "number") {
    const parsed = Number(text.trim());
    return text.trim() !== "" && Number.isFinite(parsed) ? parsed : text;
  }

  if (typeof originalValue === "boolean") {
    const normalized = text.trim().toLowerCase();
    if (normalized === "true" || normalized === "false") {
      return normalized === "true";
    }
    return text;
  }

  if (isPrimitiveList(originalValue)) {
    return text
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }

  if (originalValue !== null && typeof originalValue === "object") {
    try {
      return JSON.parse(text);
    } catch {
      throw new Error(`Enter valid JSON for ${field.label}.`);
    }
  }

  return text;
}

export function buildReportFromFields(
  fields: EditableField[],
): Record<string, unknown> {
  return Object.fromEntries(
    fields.map((field) => [field.key, parseFieldText(field)]),
  );
}

export function FinalReportCard({
  report,
  heading = "Draft report",
  sessionId,
  onSave,
}: FinalReportCardProps) {
  const displayReport = sanitizeReportForDisplay(report);
  const sections = groupReportSections(Object.entries(displayReport));
  
  const [isEditing, setIsEditing] = useState(false);
  const [fields, setFields] = useState<EditableField[]>(() =>
    buildEditableFields(displayReport),
  );
  const [editorError, setEditorError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [media, setMedia] = useState<ReportMediaResponse | null>(null);

  useEffect(() => {
    if (!sessionId) {
      return;
    }

    let cancelled = false;

    fetchReportMedia(sessionId)
      .then((response) => {
        if (!cancelled) {
          setMedia(response);
        }
      })
      // Screenshots are supporting evidence, so a report without them still reads
      // fine; the icons simply stay inert.
      .catch(() => {
        if (!cancelled) {
          setMedia(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const screenId = media?.has_screen_screenshot ? media.screen_id : null;
  // The behavior box shows this screen for as long as the report is on screen,
  // so the evidence is resolved once here rather than per icon click.
  const screenEvidence = sessionId && screenId ? { sessionId, screenId } : null;

  // Grouping keys the same way for both views is what keeps the editor's boxes
  // identical to the report's; only the field bodies differ.
  const editableSections = groupReportSections(
    fields.map((field) => [field.key, field.text]),
  );

  const stepLines = readStepLines(displayReport);
  const stepViews = buildStepViews(stepLines, media?.steps ?? []);
  // A report whose steps carry no graph ids would storyboard into nothing but
  // placeholders, so the strip only appears once there is a screen to show.
  const storyboard =
    sessionId && stepViews.some((step) => step.hasScreenshot)
      ? { sessionId, steps: stepViews }
      : null;

  function openEditor(): void {
    setFields(buildEditableFields(displayReport));
    setEditorError(null);
    setIsEditing(true);
  }

  function updateField(key: string, text: string): void {
    setFields((currentFields) =>
      currentFields.map((field) =>
        field.key === key ? { ...field, text } : field,
      ),
    );
  }

  async function saveEditedReport(): Promise<void> {
    let editedReport: Record<string, unknown>;

    try {
      editedReport = buildReportFromFields(fields);
    } catch (error) {
      setEditorError(
        error instanceof Error ? error.message : "Unable to read the edited report.",
      );
      return;
    }

    setIsSaving(true);
    setEditorError(null);

    try {
      await onSave?.(editedReport);
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
      <ReportSectionList
        sections={sections}
        screenEvidence={screenEvidence}
        storyboard={storyboard}
        renderField={([key, value]) =>
          // Numbering the steps here is what ties each one to the badge on its
          // screenshot below.
          isStepsToReproduceKey(key) && stepLines.length > 0 ? (
            <ol className="report-section__steps">
              {stepLines.map((line, position) => (
                <li key={`${position}-${line}`}>{stripStepNumber(line)}</li>
              ))}
            </ol>
          ) : (
            <p>{renderValue(value)}</p>
          )
        }
      />
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
            {/* The same boxes and screenshots as the report itself, so editing
                shows the layout the text will land in. */}
            <ReportSectionList
              sections={editableSections}
              screenEvidence={screenEvidence}
              storyboard={storyboard}
              renderField={([key], labelId) => {
                const field = fields.find((candidate) => candidate.key === key);

                return field ? (
                  <div
                    className="report-editor__autogrow"
                    data-replicated-value={field.text}
                  >
                    <textarea
                      className="report-editor__input"
                      aria-labelledby={labelId}
                      rows={1}
                      value={field.text}
                      onChange={(event) => updateField(field.key, event.target.value)}
                    />
                  </div>
                ) : null;
              }}
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
