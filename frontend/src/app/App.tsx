import { Composer } from "../features/chat/components/Composer";
import { ChatTranscript } from "../features/chat/components/ChatTranscript";
import { HeaderBar } from "../features/chat/components/HeaderBar";
import { useChatSession } from "../features/chat/hooks/useChatSession";

export function App() {
  const {
    appState,
    availableBugIds,
    bugDiscoveryStatus,
    draft,
    setDraft,
    submitDraft,
    submitModifiedReport,
    changeBug,
    reloadActiveBugs,
    activeConversation,
    canEditReport,
    editsRemaining,
  } = useChatSession();
  const composerDisabled =
    bugDiscoveryStatus !== "ready" ||
    appState.selectedBugId === null ||
    activeConversation.status === "submitting" ||
    activeConversation.status === "completed";

  return (
    <div className="app-shell">
      <HeaderBar
        availableBugIds={availableBugIds}
        bugDiscoveryStatus={bugDiscoveryStatus}
        selectedBugId={appState.selectedBugId}
        onBugChange={changeBug}
        onBugReload={reloadActiveBugs}
      />
      <ChatTranscript
        messages={activeConversation.messages}
        onSaveReport={submitModifiedReport}
        canEditReport={canEditReport}
        editsRemaining={editsRemaining}
      />
      <div className="composer-shell">
        <Composer
          disabled={composerDisabled}
          draft={draft}
          onDraftChange={setDraft}
          onSubmit={() => {
            void submitDraft();
          }}
        />
      </div>
    </div>
  );
}
