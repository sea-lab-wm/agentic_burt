import { useEffect, useId, useState } from "react";

import { fetchReportMedia } from "../../../services/api/sessionApi";
import type { ReportMediaResponse } from "../types/api";
import { ReportFieldIcon, getReportFieldMedia } from "./reportFieldIcons";
import type { ReportFieldMedia } from "./reportFieldIcons";
import { ReportScreenshotPanel } from "./ReportScreenshotPanel";
import { ReportStepsDialog } from "./ReportStepsDialog";
import {
  buildStepViews,
  isStepsToReproduceKey,
  readStepLines,
  sanitizeStepsToReproduce,
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

function formatLabel(label: string): string {
  return label
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
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
  const entries = Object.entries(displayReport);
  const fieldIdPrefix = useId();
  const [isEditing, setIsEditing] = useState(false);
  const [fields, setFields] = useState<EditableField[]>(() =>
    buildEditableFields(displayReport),
  );
  const [editorError, setEditorError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [media, setMedia] = useState<ReportMediaResponse | null>(null);
  const [openScreenshotKey, setOpenScreenshotKey] = useState<string | null>(null);
  const [areStepsOpen, setAreStepsOpen] = useState(false);

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
  const stepViews = buildStepViews(readStepLines(displayReport), media?.steps ?? []);
  const hasStepScreenshots = stepViews.some((step) => step.hasScreenshot);

  function isMediaAvailable(fieldMedia: ReportFieldMedia): boolean {
    if (!sessionId) {
      return false;
    }

    if (fieldMedia === "screen") {
      return screenId !== null;
    }

    return fieldMedia === "steps" && hasStepScreenshots;
  }

  function toggleFieldMedia(key: string, fieldMedia: ReportFieldMedia): void {
    if (fieldMedia === "steps") {
      setAreStepsOpen(true);
      return;
    }

    setOpenScreenshotKey((currentKey) => (currentKey === key ? null : key));
  }

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
      <div
        className={`final-report-card__content${
          openScreenshotKey ? " final-report-card__content--with-panel" : ""
        }`}
      >
        <div className="final-report-card__body">
          {entries.map(([key, value]) => {
            const label = formatLabel(key);
            const fieldMedia = getReportFieldMedia(key);
            const isPanelOpen = openScreenshotKey === key;

            return (
              <article key={key} className="final-report-card__row">
                <h3>
                  {isMediaAvailable(fieldMedia) ? (
                    <button
                      className="final-report-card__media-toggle"
                      type="button"
                      aria-expanded={fieldMedia === "screen" ? isPanelOpen : undefined}
                      aria-label={
                        fieldMedia === "steps"
                          ? `Show screenshots for ${label}`
                          : `${isPanelOpen ? "Hide" : "Show"} screenshot for ${label}`
                      }
                      onClick={() => toggleFieldMedia(key, fieldMedia)}
                    >
                      <ReportFieldIcon fieldKey={key} />
                    </button>
                  ) : (
                    <span className="final-report-card__field-icon" aria-hidden="true">
                      <ReportFieldIcon fieldKey={key} />
                    </span>
                  )}
                  {label}
                </h3>
                <p>{renderValue(value)}</p>
              </article>
            );
          })}
        </div>
        {sessionId && screenId && openScreenshotKey ? (
          <ReportScreenshotPanel
            sessionId={sessionId}
            screenId={screenId}
            label={formatLabel(openScreenshotKey)}
            onClose={() => setOpenScreenshotKey(null)}
          />
        ) : null}
      </div>
      {sessionId && areStepsOpen ? (
        <ReportStepsDialog
          sessionId={sessionId}
          steps={stepViews}
          onClose={() => setAreStepsOpen(false)}
        />
      ) : null}
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
            <div className="report-editor__fields">
              {fields.map((field) => (
                <div key={field.key} className="report-editor__field">
                  <label
                    className="report-editor__label"
                    htmlFor={`${fieldIdPrefix}-${field.key}`}
                  >
                    {field.label}
                  </label>
                  <div
                    className="report-editor__autogrow"
                    data-replicated-value={field.text}
                  >
                    <textarea
                      id={`${fieldIdPrefix}-${field.key}`}
                      className="report-editor__input"
                      rows={1}
                      value={field.text}
                      onChange={(event) => updateField(field.key, event.target.value)}
                    />
                  </div>
                </div>
              ))}
            </div>
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
