import { buildScreenshotUrl } from "../../../services/api/sessionApi";

type ReportScreenshotPanelProps = {
  sessionId: string;
  screenId: string;
  label: string;
};

/**
 * The app screen a report section refers to. It sits beside the section's text
 * for as long as the report is on screen, so there is nothing to open or close.
 */
export function ReportScreenshotPanel({
  sessionId,
  screenId,
  label,
}: ReportScreenshotPanelProps) {
  return (
    <aside className="report-screenshot" aria-label={`${label} screenshot`}>
      <span className="report-screenshot__title">{label}</span>
      <div className="screenshot-frame">
        <img
          src={buildScreenshotUrl(sessionId, "states", screenId)}
          alt={`App screen ${screenId}, where the bug was triggered`}
        />
      </div>
      <p className="report-screenshot__caption">Screen {screenId}</p>
    </aside>
  );
}
