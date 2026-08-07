import { describe, expect, it } from "vitest";

import { buildEditableFields, buildReportFromFields } from "./FinalReportCard";

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
