import { BugSelector } from "../../reporting-target/components/BugSelector";

type HeaderBarProps = {
  availableBugIds: number[];
  bugDiscoveryStatus: "loading" | "ready" | "error";
  selectedBugId: number | null;
  onBugChange: (bugId: number) => void;
  onBugReload: () => void;
};

export function HeaderBar({
  availableBugIds,
  bugDiscoveryStatus,
  selectedBugId,
  onBugChange,
  onBugReload,
}: HeaderBarProps) {
  return (
    <header className="header-bar">
      <div className="brand-lockup">
        <span className="brand-lockup__mark">BURT++</span>
      </div>
      <BugSelector
        availableBugIds={availableBugIds}
        bugDiscoveryStatus={bugDiscoveryStatus}
        selectedBugId={selectedBugId}
        onChange={onBugChange}
        onRetry={onBugReload}
      />
    </header>
  );
}
