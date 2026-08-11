import { buildScreenshotUrl } from "../../../services/api/sessionApi";
import { buildStoryboardTiles } from "./reportSteps";
import type { ReportStepView } from "./reportSteps";

type ReportStepsStoryboardProps = {
  sessionId: string;
  steps: ReportStepView[];
};

/**
 * The reproduction steps as a storyboard of screens. Rows alternate direction so
 * consecutive steps always sit next to each other, and the arrow leaving each
 * screen traces one unbroken path from the first step to the last.
 *
 * Steps whose transition was never captured still take their place on the path,
 * so a badge number always matches the step of the same number in the list.
 */
export function ReportStepsStoryboard({ sessionId, steps }: ReportStepsStoryboardProps) {
  return (
    <ol className="steps-storyboard" aria-label="Reproduction steps as screenshots">
      {buildStoryboardTiles(steps).map((tile) => (
        <li
          key={tile.index}
          className={`steps-storyboard__step${
            tile.connector ? ` steps-storyboard__step--${tile.connector}` : ""
          }`}
          style={{ gridRow: tile.row, gridColumn: tile.column }}
        >
          <span className="steps-storyboard__badge">{tile.index}</span>
          <div className="screenshot-frame">
            {tile.hasScreenshot && tile.transitionId ? (
              <img
                src={buildScreenshotUrl(sessionId, "transitions", tile.transitionId)}
                alt={`Screenshot for step ${tile.index}: ${tile.text}`}
              />
            ) : (
              <p className="screenshot-frame__empty">No screenshot captured</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
