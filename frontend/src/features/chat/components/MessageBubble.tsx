import type { ChatMessage } from "../types/chat";
import { FinalReportCard } from "./FinalReportCard";
import { ThinkingBubble } from "./ThinkingBubble";

type MessageBubbleProps = {
  message: ChatMessage;
  onSaveReport?: (report: Record<string, unknown>) => Promise<void>;
};

export function MessageBubble({ message, onSaveReport }: MessageBubbleProps) {
  if (message.kind === "thinking") {
    return (
      <div className="message-row message-row--agent">
        <div className="message-bubble message-bubble--agent">
          <ThinkingBubble />
        </div>
      </div>
    );
  }

  if (message.kind === "final_report") {
    return (
      <div className="message-row message-row--agent">
        <div className="message-bubble message-bubble--report">
          <FinalReportCard
            heading={message.heading}
            report={message.report}
            sessionId={message.sessionId}
            onSave={onSaveReport}
          />
        </div>
      </div>
    );
  }

  const isUser = message.kind === "user";
  const isError = message.kind === "error";
  const rowClassName = isUser ? "message-row--user" : "message-row--agent";
  const bubbleClassName = isUser
    ? "message-bubble--user"
    : isError
      ? "message-bubble--error"
      : "message-bubble--agent";

  return (
    <div className={`message-row ${rowClassName}`}>
      <div className={`message-bubble ${bubbleClassName}`}>
        <p>{message.text}</p>
      </div>
    </div>
  );
}
