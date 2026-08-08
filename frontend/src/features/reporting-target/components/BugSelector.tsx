type BugSelectorProps = {
  availableBugIds: number[];
  bugDiscoveryStatus: "loading" | "ready" | "error";
  selectedBugId: number | null;
  onChange: (bugId: number) => void;
  onRetry: () => void;
};

export function BugSelector({
  availableBugIds,
  bugDiscoveryStatus,
  selectedBugId,
  onChange,
  onRetry,
}: BugSelectorProps) {
  const isDisabled = bugDiscoveryStatus !== "ready" || availableBugIds.length === 0;

  function renderOptions() {
    if (bugDiscoveryStatus === "loading") {
      return <option value="">Loading active bugs...</option>;
    }

    if (bugDiscoveryStatus === "error") {
      return <option value="">Could not reach the server</option>;
    }

    if (availableBugIds.length === 0) {
      return <option value="">No active bugs available</option>;
    }

    return availableBugIds.map((bugId) => (
      <option key={bugId} value={bugId}>
        {`Bug ${bugId}`}
      </option>
    ));
  }

  return (
    <div className="bug-selector">
      <label className="bug-selector__field">
        <span className="bug-selector__label">reporting on:</span>
        <select
          aria-label="Select bug to report on"
          className="bug-selector__select"
          disabled={isDisabled}
          value={selectedBugId ?? ""}
          onChange={(event) => onChange(Number(event.target.value))}
        >
          {renderOptions()}
        </select>
      </label>
      {bugDiscoveryStatus === "error" ? (
        <button className="bug-selector__retry" type="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
