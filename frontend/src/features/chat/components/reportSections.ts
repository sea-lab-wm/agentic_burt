import { getReportFieldSection } from "./reportFieldIcons";
import type { ReportSectionId } from "./reportFieldIcons";

export type ReportEntry = [key: string, value: unknown];

export type ReportSection = {
  id: ReportSectionId;
  entries: ReportEntry[];
};

/** Sections are boxed in this order, whichever order the agent emits its keys in. */
const SECTION_ORDER: ReportSectionId[] = ["title", "behavior", "steps", "details"];

/** Names the boxes for screen readers; the boxes themselves carry no heading. */
export const SECTION_LABELS: Record<ReportSectionId, string> = {
  title: "Report title",
  behavior: "Observed and expected behavior",
  steps: "Steps to reproduce",
  details: "Additional details",
};

export function formatLabel(label: string): string {
  return label
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

/**
 * Fold a report's flat key/value list into the boxed sections the card shows,
 * keeping the agent's field order inside each box and dropping empty boxes.
 */
export function groupReportSections(entries: ReportEntry[]): ReportSection[] {
  const entriesBySection = new Map<ReportSectionId, ReportEntry[]>();

  for (const entry of entries) {
    const id = getReportFieldSection(entry[0]);
    const sectionEntries = entriesBySection.get(id);

    if (sectionEntries) {
      sectionEntries.push(entry);
    } else {
      entriesBySection.set(id, [entry]);
    }
  }

  return SECTION_ORDER.flatMap((id) => {
    const sectionEntries = entriesBySection.get(id);
    return sectionEntries ? [{ id, entries: sectionEntries }] : [];
  });
}
