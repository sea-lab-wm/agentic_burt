import { buildScreenshotUrl } from "../../../services/api/sessionApi";
import type { ReportStepView } from "./reportSteps";

type ReportStepsDialogProps = {
  sessionId: string;
  steps: ReportStepView[];
  onClose: () => void;
};

/** The reproduction steps as a storyboard: each step's text next to its screenshot. */
export function ReportStepsDialog({ sessionId, steps, onClose }: ReportStepsDialogProps) {
  return (
    <div
      className="steps-viewer"
      role="dialog"
      aria-modal="true"
      aria-label="Steps to reproduce with screenshots"
    >
      <div className="steps-viewer__panel">
        <div className="steps-viewer__header">
          <h2>Steps to reproduce</h2>
          <button
            className="steps-viewer__close"
            type="button"
            onClick={onClose}
            aria-label="Close steps"
          >
            X
          </button>
        </div>
        <ol className="steps-viewer__list">
          {steps.map((step) => (
            <li key={step.index} className="steps-viewer__step">
              {step.hasScreenshot && step.transitionId ? (
                <div className="screenshot-frame">
                  <img
                    src={buildScreenshotUrl(sessionId, "transitions", step.transitionId)}
                    alt={`Screenshot for step ${step.index}: ${step.text}`}
                  />
                </div>
              ) : (
                <p className="steps-viewer__no-screenshot">No screenshot captured</p>
              )}
              <p className="steps-viewer__text">{step.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
