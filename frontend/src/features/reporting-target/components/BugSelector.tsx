type BugSelectorProps = {
  availableBugIds: number[];
  bugDiscoveryStatus: "loading" | "ready" | "error";
  selectedBugId: number | null;
  onChange: (bugId: number) => void;
};

export function BugSelector({
  availableBugIds,
  bugDiscoveryStatus,
  selectedBugId,
  onChange,
}: BugSelectorProps) {
  const isDisabled = bugDiscoveryStatus !== "ready" || availableBugIds.length === 0;

  return (
    <label className="bug-selector">
      <span className="bug-selector__label">reporting on:</span>
      <select
        aria-label="Select bug to report on"
        className="bug-selector__select"
        disabled={isDisabled}
        value={selectedBugId ?? ""}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {bugDiscoveryStatus === "loading" ? (
          <option value="">Loading active bugs...</option>
        ) : availableBugIds.length === 0 ? (
          <option value="">No active bugs available</option>
        ) : (
          availableBugIds.map((bugId) => (
            <option key={bugId} value={bugId}>
              {`Bug ${bugId}`}
            </option>
          ))
        )}
      </select>
    </label>
  );
}
