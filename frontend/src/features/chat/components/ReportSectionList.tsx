import { useId } from "react";
import type { ReactNode } from "react";

import { ReportFieldIcon } from "./reportFieldIcons";
import { ReportScreenshotPanel } from "./ReportScreenshotPanel";
import { ReportStepsStoryboard } from "./ReportStepsStoryboard";
import { SECTION_LABELS, formatLabel } from "./reportSections";
import type { ReportEntry, ReportSection } from "./reportSections";
import type { ReportStepView } from "./reportSteps";

export type ScreenEvidence = { sessionId: string; screenId: string };

export type StoryboardEvidence = { sessionId: string; steps: ReportStepView[] };

type ReportSectionListProps = {
  sections: ReportSection[];
  screenEvidence: ScreenEvidence | null;
  storyboard: StoryboardEvidence | null;
  /** Renders one field's body. `labelId` names the heading the body belongs to. */
  renderField: (entry: ReportEntry, labelId: string) => ReactNode;
};

/**
 * The boxed layout of a report: one tinted box per information element, its text
 * and its screenshots in separate panels inside.
 *
 * Reading the report and editing it share this component so the two cannot drift
 * apart; only the field bodies differ, which is what `renderField` supplies.
 */
export function ReportSectionList({
  sections,
  screenEvidence,
  storyboard,
  renderField,
}: ReportSectionListProps) {
  const labelIdPrefix = useId();

  return (
    <div className="report-sections">
      {sections.map((section) => {
        // Steps carry their own storyboard, so only the behavior box takes the
        // triggering screen.
        const sectionScreen = section.id === "behavior" ? screenEvidence : null;

        return (
          <section
            key={section.id}
            className={`report-section report-section--${section.id}${
              sectionScreen ? " report-section--with-media" : ""
            }`}
            aria-label={SECTION_LABELS[section.id]}
          >
            <div className="report-section__text">
              {section.entries.map((entry) => {
                const labelId = `${labelIdPrefix}-${entry[0]}`;

                return (
                  <article key={entry[0]} className="report-section__field">
                    <h3 id={labelId}>
                      <span className="report-section__icon" aria-hidden="true">
                        <ReportFieldIcon fieldKey={entry[0]} />
                      </span>
                      {formatLabel(entry[0])}
                    </h3>
                    {renderField(entry, labelId)}
                  </article>
                );
              })}
            </div>
            {sectionScreen ? (
              <ReportScreenshotPanel
                sessionId={sectionScreen.sessionId}
                screenId={sectionScreen.screenId}
                label="Triggering screen"
              />
            ) : null}
            {section.id === "steps" && storyboard ? (
              <ReportStepsStoryboard
                sessionId={storyboard.sessionId}
                steps={storyboard.steps}
              />
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
