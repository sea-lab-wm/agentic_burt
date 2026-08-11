import type { ReactElement } from "react";

/**
 * Which boxed section of the report a field belongs to. Observed and expected
 * behavior share one section because they describe the same screen from two
 * sides; anything the agent adds beyond the known fields lands in "details".
 */
export type ReportSectionId = "title" | "behavior" | "steps" | "details";

type ReportFieldPresentation = {
  icon: ReactElement;
  section: ReportSectionId;
};

const iconProps = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

const TAG_ICON = (
  <svg {...iconProps}>
    <path d="M3.5 11V4a.5.5 0 0 1 .5-.5h7l9.5 9.5a1.5 1.5 0 0 1 0 2.1l-5.4 5.4a1.5 1.5 0 0 1-2.1 0z" />
    <circle cx="7.75" cy="7.75" r="1.35" />
  </svg>
);

const EYE_ICON = (
  <svg {...iconProps}>
    <path d="M2.5 12S6 5.75 12 5.75 21.5 12 21.5 12 18 18.25 12 18.25 2.5 12 2.5 12z" />
    <circle cx="12" cy="12" r="2.9" />
  </svg>
);

const CHECK_ICON = (
  <svg {...iconProps}>
    <circle cx="12" cy="12" r="8.75" />
    <path d="m8.25 12.35 2.6 2.6 4.9-5.6" />
  </svg>
);

const STEPS_ICON = (
  <svg {...iconProps}>
    <path d="m3.5 6.4 1.5 1.5 2.4-2.9" />
    <path d="m3.5 12.4 1.5 1.5 2.4-2.9" />
    <path d="m3.5 18.4 1.5 1.5 2.4-2.9" />
    <path d="M11.5 6.5h9" />
    <path d="M11.5 12.5h9" />
    <path d="M11.5 18.5h9" />
  </svg>
);

const NOTE_ICON = (
  <svg {...iconProps}>
    <path d="M5.5 3.5h9l5 5v12h-14z" />
    <path d="M14.5 3.5v5h5" />
    <path d="M8.5 13h7" />
    <path d="M8.5 16.5h4.5" />
  </svg>
);

const DEFAULT_PRESENTATION: ReportFieldPresentation = {
  icon: NOTE_ICON,
  section: "details",
};

/**
 * Report keys vary in wording between prompt versions, so each icon is claimed by
 * every phrasing the agent is known to emit for that information element.
 */
const PRESENTATION_BY_FIELD: Record<string, ReportFieldPresentation> = {
  title: { icon: TAG_ICON, section: "title" },
  summary: { icon: TAG_ICON, section: "title" },
  "observed behavior": { icon: EYE_ICON, section: "behavior" },
  "buggy behavior": { icon: EYE_ICON, section: "behavior" },
  "actual behavior": { icon: EYE_ICON, section: "behavior" },
  "expected behavior": { icon: CHECK_ICON, section: "behavior" },
  "correct behavior": { icon: CHECK_ICON, section: "behavior" },
  "steps to reproduce": { icon: STEPS_ICON, section: "steps" },
};

export function normalizeFieldKey(key: string): string {
  return key.replace(/[_-]/g, " ").trim().replace(/\s+/g, " ").toLowerCase();
}

function presentationFor(key: string): ReportFieldPresentation {
  return PRESENTATION_BY_FIELD[normalizeFieldKey(key)] ?? DEFAULT_PRESENTATION;
}

export function getReportFieldSection(key: string): ReportSectionId {
  return presentationFor(key).section;
}

export function ReportFieldIcon({ fieldKey }: { fieldKey: string }): ReactElement {
  return presentationFor(fieldKey).icon;
}
