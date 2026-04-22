import { BUG_OPTIONS } from "../../../config/bugs";

type BugSelectorProps = {
  selectedBugId: number;
  onChange: (bugId: number) => void;
};

export function BugSelector({ selectedBugId, onChange }: BugSelectorProps) {
  return (
    <label className="bug-selector">
      <span className="bug-selector__label">reporting on:</span>
      <select
        aria-label="Select bug to report on"
        className="bug-selector__select"
        value={selectedBugId}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {BUG_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
