import { buildScreenshotUrl } from "../../../services/api/sessionApi";

type ReportScreenshotPanelProps = {
  sessionId: string;
  screenId: string;
  label: string;
};

/**
 * The app screen a report section refers to. It sits beside the section's text
 * for as long as the report is on screen, so there is nothing to open or close.
 *
 * The screen speaks for itself next to the behavior it illustrates, so the panel
 * carries no heading or caption of its own; only the frame, sized to match one
 * step of the storyboard below it.
 */
export function ReportScreenshotPanel({
  sessionId,
  screenId,
  label,
}: ReportScreenshotPanelProps) {
  return (
    <aside className="report-screenshot" aria-label={`${label} screenshot`}>
      <div className="screenshot-frame">
        <img
          src={buildScreenshotUrl(sessionId, "states", screenId)}
          alt={`App screen ${screenId}, where the bug was triggered`}
        />
      </div>
    </aside>
  );
}
