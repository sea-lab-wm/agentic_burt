import { buildScreenshotUrl } from "../../../services/api/sessionApi";

type ReportScreenshotPanelProps = {
  sessionId: string;
  screenId: string;
  label: string;
  onClose: () => void;
};

/** The app screen a report field refers to, shown beside the report text. */
export function ReportScreenshotPanel({
  sessionId,
  screenId,
  label,
  onClose,
}: ReportScreenshotPanelProps) {
  return (
    <aside className="report-screenshot" aria-label={`${label} screenshot`}>
      <div className="report-screenshot__header">
        <span className="report-screenshot__title">{label}</span>
        <button
          className="report-screenshot__close"
          type="button"
          onClick={onClose}
          aria-label={`Close ${label} screenshot`}
        >
          X
        </button>
      </div>
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
