import { BugSelector } from "../../reporting-target/components/BugSelector";

type HeaderBarProps = {
  selectedBugId: number;
  onBugChange: (bugId: number) => void;
};

export function HeaderBar({ selectedBugId, onBugChange }: HeaderBarProps) {
  return (
    <header className="header-bar">
      <div className="brand-lockup">
        <span className="brand-lockup__mark">BURT++</span>
      </div>
      <BugSelector selectedBugId={selectedBugId} onChange={onBugChange} />
    </header>
  );
}
