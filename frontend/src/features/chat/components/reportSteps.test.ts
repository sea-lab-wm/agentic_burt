import { describe, expect, it } from "vitest";

import { getReportFieldSection } from "./reportFieldIcons";
import {
  buildStepViews,
  buildStoryboardTiles,
  readStepLines,
  stripStepNumber,
} from "./reportSteps";
import type { ReportStepView } from "./reportSteps";

describe("readStepLines", () => {
  it("reads a multiline steps string as one identifier-free line per step", () => {
    expect(
      readStepLines({
        title: "Crash",
        steps_to_reproduce: "1. Open the app. <-707067098>\n2. Tap Go. <990647563>",
      }),
    ).toEqual(["1. Open the app.", "2. Tap Go."]);
  });

  it("reads list-valued steps and skips blank lines", () => {
    expect(
      readStepLines({ "steps-to-reproduce": ["Open the app. <123>", "", "Tap Go."] }),
    ).toEqual(["Open the app.", "Tap Go."]);
  });

  it("returns nothing when the report has no steps field", () => {
    expect(readStepLines({ title: "Crash", observed_behavior: "It closes." })).toEqual([]);
  });
});

describe("buildStepViews", () => {
  const mediaSteps = [
    { index: 1, text: "1. Open the app.", transition_id: "-707067098", has_screenshot: false },
    { index: 2, text: "2. Tap Go.", transition_id: "990647563", has_screenshot: true },
  ];

  it("pairs each displayed step with the transition the backend mapped it to", () => {
    expect(buildStepViews(["1. Open the app.", "2. Tap Go."], mediaSteps)).toEqual([
      { index: 1, text: "1. Open the app.", transitionId: "-707067098", hasScreenshot: false },
      { index: 2, text: "2. Tap Go.", transitionId: "990647563", hasScreenshot: true },
    ]);
  });

  it("keeps the edited wording shown in the card over the logged wording", () => {
    const [firstStep] = buildStepViews(["1. Launch the app."], mediaSteps);

    expect(firstStep?.text).toBe("1. Launch the app.");
    expect(firstStep?.transitionId).toBe("-707067098");
  });

  it("falls back to the logged steps when the report itself has none", () => {
    expect(buildStepViews([], mediaSteps).map((step) => step.text)).toEqual([
      "1. Open the app.",
      "2. Tap Go.",
    ]);
  });

  it("marks steps added beyond the mapped ones as having no screenshot", () => {
    const steps = buildStepViews(["1. Open the app.", "2. Tap Go.", "3. Tap Back."], mediaSteps);

    expect(steps).toHaveLength(3);
    expect(steps[2]).toEqual({
      index: 3,
      text: "3. Tap Back.",
      transitionId: null,
      hasScreenshot: false,
    });
  });
});

describe("stripStepNumber", () => {
  it("drops the agent's own numbering so a list does not number twice", () => {
    expect(stripStepNumber("1. Open the app.")).toBe("Open the app.");
    expect(stripStepNumber("2) Tap Go.")).toBe("Tap Go.");
    expect(stripStepNumber("10.Enter a value")).toBe("Enter a value");
  });

  it("leaves an unnumbered step alone", () => {
    expect(stripStepNumber("Open the app.")).toBe("Open the app.");
  });

  it("keeps a step that is nothing but a number rather than blanking it", () => {
    expect(stripStepNumber("6.")).toBe("6.");
  });
});

describe("buildStoryboardTiles", () => {
  function steps(count: number): ReportStepView[] {
    return Array.from({ length: count }, (_, position) => ({
      index: position + 1,
      text: `Step ${position + 1}`,
      transitionId: String(position),
      hasScreenshot: true,
    }));
  }

  it("runs the first row left to right and the next one back right to left", () => {
    const tiles = buildStoryboardTiles(steps(8));

    expect(tiles.map((tile) => [tile.row, tile.column])).toEqual([
      [1, 1],
      [1, 2],
      [1, 3],
      [1, 4],
      [2, 4],
      [2, 3],
      [2, 2],
      [2, 1],
    ]);
  });

  it("turns the path down at the end of a row and back up the next direction", () => {
    expect(buildStoryboardTiles(steps(8)).map((tile) => tile.connector)).toEqual([
      "right",
      "right",
      "right",
      "down",
      "left",
      "left",
      "left",
      null,
    ]);
  });

  it("starts a reversed short row from the right so the path stays unbroken", () => {
    const tiles = buildStoryboardTiles(steps(6));

    // Step 5 sits directly under step 4, then the row reads leftwards.
    expect(tiles[4]).toMatchObject({ index: 5, row: 2, column: 4, connector: "left" });
    expect(tiles[5]).toMatchObject({ index: 6, row: 2, column: 3, connector: null });
  });

  it("gives a single step no connector at all", () => {
    expect(buildStoryboardTiles(steps(1))).toEqual([
      { index: 1, text: "Step 1", transitionId: "0", hasScreenshot: true, row: 1, column: 1, connector: null },
    ]);
  });

  it("keeps an uncaptured step on the path so badges match the written steps", () => {
    const withGap = steps(5);
    withGap[0] = { ...withGap[0]!, hasScreenshot: false, transitionId: null };
    const tiles = buildStoryboardTiles(withGap);

    expect(tiles).toHaveLength(5);
    expect(tiles[0]).toMatchObject({ index: 1, column: 1, hasScreenshot: false });
    expect(tiles.map((tile) => tile.index)).toEqual([1, 2, 3, 4, 5]);
  });
});

describe("getReportFieldSection", () => {
  it("shares one box between the behaviors whatever the key style", () => {
    expect(getReportFieldSection("observed_behavior")).toBe("behavior");
    expect(getReportFieldSection("Expected Behavior")).toBe("behavior");
    expect(getReportFieldSection("correct-behavior")).toBe("behavior");
  });

  it("keeps the title and the steps in boxes of their own", () => {
    expect(getReportFieldSection("title")).toBe("title");
    expect(getReportFieldSection("summary")).toBe("title");
    expect(getReportFieldSection("steps_to_reproduce")).toBe("steps");
  });

  it("sends fields outside the known report shape to the details box", () => {
    expect(getReportFieldSection("severity")).toBe("details");
  });
});
