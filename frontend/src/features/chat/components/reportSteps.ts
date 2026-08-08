import type { ReportStepMedia } from "../types/api";

/** One reproduction step as shown to the user, paired with its screenshot source. */
export type ReportStepView = {
  index: number;
  text: string;
  transitionId: string | null;
  hasScreenshot: boolean;
};

export function isStepsToReproduceKey(key: string): boolean {
  return key.replace(/[_-]/g, " ").toLowerCase() === "steps to reproduce";
}

/** Drop the trailing "<graph id>" marker the agent appends to every step. */
export function stripStepIdentifier(step: string): string {
  return step.replace(/\s*<[^>\n]+>\s*$/u, "");
}

export function sanitizeStepsToReproduce(value: unknown): unknown {
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

/** Read a report's reproduction steps as one trimmed, identifier-free line per step. */
export function readStepLines(report: Record<string, unknown>): string[] {
  const stepsEntry = Object.entries(report).find(([key]) => isStepsToReproduceKey(key));
  if (!stepsEntry) {
    return [];
  }

  const [, value] = stepsEntry;
  const lines =
    typeof value === "string"
      ? value.split("\n")
      : Array.isArray(value)
        ? value.map((step) => String(step))
        : [];

  return lines
    .map((line) => stripStepIdentifier(line).trim())
    .filter((line) => line.length > 0);
}

/**
 * Pair the steps shown in the card with the transitions the backend mapped them to.
 *
 * The displayed report may have been edited, so its wording wins; the mapping only
 * ever came from the agent-authored report, which is what the backend reports on.
 */
export function buildStepViews(
  stepLines: string[],
  mediaSteps: ReportStepMedia[],
): ReportStepView[] {
  const lines = stepLines.length > 0 ? stepLines : mediaSteps.map((step) => step.text);

  return lines.map((text, position) => {
    const stepMedia = mediaSteps[position];

    return {
      index: position + 1,
      text,
      transitionId: stepMedia?.transition_id ?? null,
      hasScreenshot: stepMedia?.has_screenshot ?? false,
    };
  });
}
