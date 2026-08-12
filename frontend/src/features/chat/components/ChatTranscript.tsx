import { useEffect, useRef } from "react";

import type { ChatMessage } from "../types/chat";
import { MessageBubble } from "./MessageBubble";

type ChatTranscriptProps = {
  messages: ChatMessage[];
  onSaveReport?: (report: Record<string, unknown>) => Promise<void>;
  /** Whether the newest draft report may still be edited and regenerated. */
  canEditReport?: boolean;
  /** How many edit-and-regenerate rounds the session has left. */
  editsRemaining?: number;
};

/** The newest agent-written report, the only one an edit can still be based on. */
function findEditableReportId(messages: ChatMessage[]): string | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]!;

    if (message.kind === "final_report" && (message.variant ?? "draft") === "draft") {
      return message.id;
    }
  }

  return undefined;
}

export function ChatTranscript({
  messages,
  onSaveReport,
  canEditReport = true,
  editsRemaining,
}: ChatTranscriptProps) {
  const endRef = useRef<HTMLDivElement | null>(null);
  // Superseded reports stay on screen as a record of the round they belong to,
  // so only the report a regeneration would start from keeps its Edit button.
  const editableReportId = canEditReport ? findEditableReportId(messages) : undefined;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  return (
    <main className="chat-transcript" aria-live="polite">
      <div className="chat-transcript__inner">
        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            onSaveReport={message.id === editableReportId ? onSaveReport : undefined}
            editsRemaining={editsRemaining}
          />
        ))}
        <div ref={endRef} />
      </div>
    </main>
  );
}
