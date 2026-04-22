import { Composer } from "../features/chat/components/Composer";
import { ChatTranscript } from "../features/chat/components/ChatTranscript";
import { HeaderBar } from "../features/chat/components/HeaderBar";
import { useChatSession } from "../features/chat/hooks/useChatSession";

export function App() {
  const {
    appState,
    draft,
    setDraft,
    submitDraft,
    changeBug,
    activeConversation,
  } = useChatSession();

  return (
    <div className="app-shell">
      <HeaderBar selectedBugId={appState.selectedBugId} onBugChange={changeBug} />
      <ChatTranscript messages={activeConversation.messages} />
      <div className="composer-shell">
        <Composer
          disabled={activeConversation.status === "submitting" || activeConversation.status === "completed"}
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
