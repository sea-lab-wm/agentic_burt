import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinalReportCard, buildEditableFields, buildReportFromFields } from "./FinalReportCard";
import { groupReportSections } from "./reportSections";

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

describe("report sections", () => {
  it("boxes observed and expected behavior together, in a fixed section order", () => {
    const sections = groupReportSections(
      Object.entries({
        steps_to_reproduce: "1. Open the app.",
        expected_behavior: "The app should save.",
        title: "Crash on save",
        observed_behavior: "The app closes.",
      }),
    );

    expect(sections.map((section) => section.id)).toEqual(["title", "behavior", "steps"]);
    expect(sections[1]?.entries.map(([key]) => key)).toEqual([
      "expected_behavior",
      "observed_behavior",
    ]);
  });

  it("collects fields outside the known report shape into one details box", () => {
    const sections = groupReportSections(
      Object.entries({ title: "Crash on save", severity: "high", is_reproducible: true }),
    );

    expect(sections.map((section) => section.id)).toEqual(["title", "details"]);
    expect(sections[1]?.entries.map(([key]) => key)).toEqual(["severity", "is_reproducible"]);
  });

  it("drops sections the report has no fields for", () => {
    expect(groupReportSections(Object.entries({ title: "Crash on save" }))).toEqual([
      { id: "title", entries: [["title", "Crash on save"]] },
    ]);
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

  it("shows the triggering screen inside the behavior box without a click", async () => {
    mockReportMedia(REPORT_MEDIA);
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    const behavior = await screen.findByRole("region", {
      name: "Observed and expected behavior",
    });

    expect(
      within(behavior).getByAltText("App screen 78249749, where the bug was triggered"),
    ).toHaveAttribute("src", "/api/sessions/session-456/screenshots/states/78249749");
    // The icons label their fields now, so there is nothing left to click.
    expect(screen.queryByRole("button", { name: /screenshot/i })).not.toBeInTheDocument();
  });

  it("shows the behavior screen on its own, with no title or caption around it", async () => {
    mockReportMedia(REPORT_MEDIA);
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    const panel = await screen.findByRole("complementary", {
      name: "Triggering screen screenshot",
    });

    // The screen speaks for itself beside the behavior it illustrates.
    expect(within(panel).getByRole("img")).toBeInTheDocument();
    expect(panel).not.toHaveTextContent(/\S/);
  });

  it("asks for the screenshots of the run the report came from", async () => {
    mockReportMedia(REPORT_MEDIA);
    render(<FinalReportCard report={REPORT} sessionId="session-456" revision={2} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/session-456/report-media?revision=2",
      expect.anything(),
    );
  });

  it("shows one screenshot for the behavior pair rather than one per field", async () => {
    mockReportMedia(REPORT_MEDIA);
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    const behavior = await screen.findByRole("region", {
      name: "Observed and expected behavior",
    });

    expect(within(behavior).getAllByRole("img")).toHaveLength(1);
    expect(within(behavior).getByText("Observed Behavior")).toBeInTheDocument();
    expect(within(behavior).getByText("Expected Behavior")).toBeInTheDocument();
  });

  it("keeps the behavior box readable when the session captured no screen", async () => {
    mockReportMedia({ ...REPORT_MEDIA, has_screen_screenshot: false, screen_id: null, steps: [] });
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Observed Behavior")).toBeInTheDocument();
  });

  it("still renders the report when the media lookup fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    expect(screen.getByText("The app closes.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("does not look up screenshots for a report with no session", () => {
    render(<FinalReportCard report={REPORT} />);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText("Crash on save")).toBeInTheDocument();
  });
});

describe("report editor layout", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(REPORT_MEDIA), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
  });

  async function openEditor(onSave = vi.fn().mockResolvedValue(undefined)) {
    const user = userEvent.setup();
    render(<FinalReportCard report={REPORT} sessionId="session-456" onSave={onSave} />);

    // Wait for the media lookup so the editor opens with the screenshots in place.
    await screen.findAllByRole("img");
    await user.click(screen.getByRole("button", { name: "Edit" }));

    return {
      user,
      onSave,
      dialog: screen.getByRole("dialog", { name: "Edit bug report" }),
    };
  }

  it("edits the behaviors in the same box, screenshot and all", async () => {
    const { dialog } = await openEditor();
    const behavior = within(dialog).getByRole("region", {
      name: "Observed and expected behavior",
    });

    expect(within(behavior).getByLabelText("Observed Behavior")).toHaveValue("The app closes.");
    expect(within(behavior).getByLabelText("Expected Behavior")).toHaveValue(
      "The app should save.",
    );
    expect(
      within(behavior).getByAltText("App screen 78249749, where the bug was triggered"),
    ).toBeInTheDocument();
  });

  it("keeps the storyboard beside the steps it is editing", async () => {
    const { dialog } = await openEditor();
    const steps = within(dialog).getByRole("region", { name: "Steps to reproduce" });

    // The steps edit as their raw lines, identifiers already stripped.
    expect(within(steps).getByLabelText("Steps To Reproduce")).toHaveValue(
      "1. Open the app.\n2. Tap Go.",
    );
    expect(
      within(steps).getByRole("list", { name: "Reproduction steps as screenshots" }),
    ).toBeInTheDocument();
  });

  it("boxes every report field, the title included", async () => {
    const { dialog } = await openEditor();

    expect(
      within(dialog)
        .getAllByRole("region")
        .map((region) => region.getAttribute("aria-label")),
    ).toEqual(["Report title", "Observed and expected behavior", "Steps to reproduce"]);
  });

  it("saves what was typed into the boxes", async () => {
    const { user, onSave, dialog } = await openEditor();
    const title = within(dialog).getByLabelText("Title");

    await user.clear(title);
    await user.type(title, "Crash on load");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith({
      ...REPORT,
      title: "Crash on load",
      steps_to_reproduce: "1. Open the app.\n2. Tap Go.",
    });
  });
});

describe("steps storyboard", () => {
  const fetchMock = vi.fn<typeof fetch>();

  function mockReportMedia(payload: unknown): void {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  }

  function findStoryboard(): Promise<HTMLElement> {
    return screen.findByRole("list", { name: "Reproduction steps as screenshots" });
  }

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("puts the storyboard in the steps box, badges matching the written steps", async () => {
    mockReportMedia(REPORT_MEDIA);
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    const storyboard = await findStoryboard();
    const steps = screen.getByRole("region", { name: "Steps to reproduce" });
    const tiles = within(storyboard).getAllByRole("listitem");

    expect(steps).toContainElement(storyboard);
    expect(within(tiles[1]!).getByText("2")).toBeInTheDocument();
    expect(within(tiles[1]!).getByAltText("Screenshot for step 2: 2. Tap Go.")).toHaveAttribute(
      "src",
      "/api/sessions/session-456/screenshots/transitions/990647563",
    );
  });

  it("keeps the uncaptured first step on the path as a placeholder", async () => {
    mockReportMedia(REPORT_MEDIA);
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    const tiles = within(await findStoryboard()).getAllByRole("listitem");

    expect(tiles).toHaveLength(2);
    expect(within(tiles[0]!).getByText("1")).toBeInTheDocument();
    expect(within(tiles[0]!).getByText("No screenshot captured")).toBeInTheDocument();
    expect(within(tiles[0]!).queryByRole("img")).not.toBeInTheDocument();
  });

  it("places the tiles along the serpentine path it computed", async () => {
    mockReportMedia(REPORT_MEDIA);
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    const tiles = within(await findStoryboard()).getAllByRole("listitem");

    expect(tiles[0]).toHaveStyle({ gridRow: "1", gridColumn: "1" });
    expect(tiles[1]).toHaveStyle({ gridRow: "1", gridColumn: "2" });
    expect(tiles[0]).toHaveClass("steps-storyboard__step--right");
    // Nothing follows the last step, so it carries no connector.
    expect(tiles[1]!.className).toBe("steps-storyboard__step");
  });

  it("leaves out the storyboard when no step was captured", async () => {
    mockReportMedia({
      ...REPORT_MEDIA,
      steps: REPORT_MEDIA.steps.map((step) => ({ ...step, has_screenshot: false })),
    });
    render(<FinalReportCard report={REPORT} sessionId="session-456" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    expect(
      screen.queryByRole("list", { name: "Reproduction steps as screenshots" }),
    ).not.toBeInTheDocument();
    // The written steps still stand on their own.
    expect(screen.getByText("Open the app.")).toBeInTheDocument();
  });
});
