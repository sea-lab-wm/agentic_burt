import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReportStepsDialog } from "./ReportStepsDialog";

/**
 * The card no longer opens this dialog: reproduction steps are shown as text
 * while their inline screenshots are designed. The storyboard is kept working
 * here so it can be wired back up unchanged.
 */
const STEPS = [
  { index: 1, text: "1. Open the app.", transitionId: "-707067098", hasScreenshot: false },
  { index: 2, text: "2. Tap Go.", transitionId: "990647563", hasScreenshot: true },
];

describe("ReportStepsDialog", () => {
  it("shows each reproduction step next to its transition screenshot", () => {
    render(<ReportStepsDialog sessionId="session-456" steps={STEPS} onClose={vi.fn()} />);

    expect(
      screen.getByRole("dialog", { name: "Steps to reproduce with screenshots" }),
    ).toBeInTheDocument();
    expect(screen.getByAltText("Screenshot for step 2: 2. Tap Go.")).toHaveAttribute(
      "src",
      "/api/sessions/session-456/screenshots/transitions/990647563",
    );
    // The synthetic "open app" transition has no capture, so the step still lists.
    expect(screen.getByText("1. Open the app.")).toBeInTheDocument();
    expect(screen.getByText("No screenshot captured")).toBeInTheDocument();
  });

  it("closes on the close button", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<ReportStepsDialog sessionId="session-456" steps={STEPS} onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "Close steps" }));

    expect(onClose).toHaveBeenCalledOnce();
  });
});
