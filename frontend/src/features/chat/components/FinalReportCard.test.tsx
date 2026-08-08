import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinalReportCard, buildEditableFields, buildReportFromFields } from "./FinalReportCard";

describe("report editor fields", () => {
  it("labels each report key and keeps the original key order", () => {
    const fields = buildEditableFields({
      title: "Crash on save",
      observed_behavior: "The app closes.",
      steps_to_reproduce: "1. Open the app.\n2. Tap Save.",
    });

    expect(fields.map((field) => field.key)).toEqual([
      "title",
      "observed_behavior",
      "steps_to_reproduce",
    ]);
    expect(fields.map((field) => field.label)).toEqual([
      "Title",
      "Observed Behavior",
      "Steps To Reproduce",
    ]);
  });

  it("round-trips a multiline string field without altering it", () => {
    const report = { steps_to_reproduce: "1. Open the app.\n2. Tap Save." };

    expect(buildReportFromFields(buildEditableFields(report))).toEqual(report);
  });

  it("edits list-valued fields one item per line and rebuilds the list", () => {
    const fields = buildEditableFields({ steps_to_reproduce: ["Open the app.", "Tap Save."] });
    expect(fields[0]?.text).toBe("Open the app.\nTap Save.");

    const edited = [{ ...fields[0]!, text: "Open the app.\nTap Save.\nConfirm." }];

    expect(buildReportFromFields(edited)).toEqual({
      steps_to_reproduce: ["Open the app.", "Tap Save.", "Confirm."],
    });
  });

  it("preserves number and boolean field types", () => {
    const report = { bug_id: 10, is_reproducible: true };

    expect(buildReportFromFields(buildEditableFields(report))).toEqual(report);
  });

  it("reports which field holds invalid JSON instead of discarding the edit", () => {
    const fields = buildEditableFields({ extra_metadata: { severity: "high" } });
    const edited = [{ ...fields[0]!, text: "{not json" }];

    expect(() => buildReportFromFields(edited)).toThrowError(
      "Enter valid JSON for Extra Metadata.",
    );
  });
});

const REPORT = {
  title: "Crash on save",
  observed_behavior: "The app closes.",
  expected_behavior: "The app should save.",
  steps_to_reproduce: "1. Open the app. <-707067098>\n2. Tap Go. <990647563>",
};

const REPORT_MEDIA = {
  session_id: "session-456",
  bug_id: 11,
  app_name: "1-de.delusions.measure-1.5.4",
  screen_id: "78249749",
  has_screen_screenshot: true,
  steps: [
    { index: 1, text: "1. Open the app.", transition_id: "-707067098", has_screenshot: false },
    { index: 2, text: "2. Tap Go.", transition_id: "990647563", has_screenshot: true },
  ],
};

describe("report field screenshots", () => {
  const fetchMock = vi.fn<typeof fetch>();

  function mockReportMedia(payload: unknown): void {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  }

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("opens the triggering screen beside the report when a behavior icon is clicked", async () => {
    mockReportMedia(REPORT_MEDIA);
    const user = userEvent.setup();
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    const toggle = await screen.findByRole("button", {
      name: "Show screenshot for Observed Behavior",
    });
    await user.click(toggle);

    expect(
      screen.getByAltText("App screen 78249749, where the bug was triggered"),
    ).toHaveAttribute("src", "/api/sessions/session-456/screenshots/states/78249749");
    expect(
      screen.getByRole("button", { name: "Hide screenshot for Observed Behavior" }),
    ).toBeInTheDocument();
  });

  it("swaps the panel to the other behavior rather than stacking two screenshots", async () => {
    mockReportMedia(REPORT_MEDIA);
    const user = userEvent.setup();
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    await user.click(
      await screen.findByRole("button", { name: "Show screenshot for Observed Behavior" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Show screenshot for Expected Behavior" }),
    );

    expect(screen.getAllByRole("img")).toHaveLength(1);
    expect(screen.getByLabelText("Expected Behavior screenshot")).toBeInTheDocument();
  });

  it("closes the panel when the same icon is clicked again", async () => {
    mockReportMedia(REPORT_MEDIA);
    const user = userEvent.setup();
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    const toggle = await screen.findByRole("button", {
      name: "Show screenshot for Observed Behavior",
    });
    await user.click(toggle);
    await user.click(
      screen.getByRole("button", { name: "Hide screenshot for Observed Behavior" }),
    );

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows each reproduction step next to its transition screenshot in a dialog", async () => {
    mockReportMedia(REPORT_MEDIA);
    const user = userEvent.setup();
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    await user.click(
      await screen.findByRole("button", { name: "Show screenshots for Steps To Reproduce" }),
    );

    const dialog = screen.getByRole("dialog", { name: "Steps to reproduce with screenshots" });
    expect(dialog).toBeInTheDocument();
    expect(
      screen.getByAltText("Screenshot for step 2: 2. Tap Go."),
    ).toHaveAttribute("src", "/api/sessions/session-456/screenshots/transitions/990647563");
    // The synthetic "open app" transition has no capture, so the step still lists.
    expect(screen.getByText("1. Open the app.")).toBeInTheDocument();
    expect(screen.getByText("No screenshot captured")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close steps" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("leaves the icons inert when the session has no captured screenshots", async () => {
    mockReportMedia({ ...REPORT_MEDIA, has_screen_screenshot: false, screen_id: null, steps: [] });
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    expect(screen.queryByRole("button", { name: /screenshot/i })).not.toBeInTheDocument();
    expect(screen.getByText("Observed Behavior")).toBeInTheDocument();
  });

  it("still renders the report when the media lookup fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    expect(screen.getByText("The app closes.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /screenshot/i })).not.toBeInTheDocument();
  });

  it("does not look up screenshots for a report with no session", () => {
    render(<FinalReportCard report={REPORT} />);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText("Crash on save")).toBeInTheDocument();
  });
});
