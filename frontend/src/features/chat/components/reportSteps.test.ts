import { describe, expect, it } from "vitest";

import { getReportFieldMedia } from "./reportFieldIcons";
import { buildStepViews, readStepLines } from "./reportSteps";

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

describe("getReportFieldMedia", () => {
  it("maps behavior fields to the triggering screen whatever the key style", () => {
    expect(getReportFieldMedia("observed_behavior")).toBe("screen");
    expect(getReportFieldMedia("Expected Behavior")).toBe("screen");
    expect(getReportFieldMedia("correct-behavior")).toBe("screen");
  });

  it("maps the steps field to the step storyboard", () => {
    expect(getReportFieldMedia("steps_to_reproduce")).toBe("steps");
  });

  it("gives fields with no visual evidence a decorative icon only", () => {
    expect(getReportFieldMedia("title")).toBeNull();
    expect(getReportFieldMedia("severity")).toBeNull();
  });
});
