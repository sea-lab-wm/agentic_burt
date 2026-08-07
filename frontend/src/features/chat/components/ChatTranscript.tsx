import { useEffect, useRef } from "react";

import type { ChatMessage } from "../types/chat";
import { MessageBubble } from "./MessageBubble";

type ChatTranscriptProps = {
  messages: ChatMessage[];
  onSaveReport?: (report: Record<string, unknown>) => Promise<void>;
};

export function ChatTranscript({ messages, onSaveReport }: ChatTranscriptProps) {
  const endRef = useRef<HTMLDivElement | null>(null);

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
            onSaveReport={onSaveReport}
          />
        ))}
        <div ref={endRef} />
      </div>
    </main>
  );
}
