export type AgentMessage = {
  id: string;
  kind: "agent";
  text: string;
};

export type UserMessage = {
  id: string;
  kind: "user";
  text: string;
};

export type ThinkingMessage = {
  id: string;
  kind: "thinking";
};

export type FinalReportMessage = {
  id: string;
  kind: "final_report";
  report: Record<string, unknown>;
};

export type ErrorMessage = {
  id: string;
  kind: "error";
  text: string;
};

export type ChatMessage =
  | AgentMessage
  | UserMessage
  | ThinkingMessage
  | FinalReportMessage
  | ErrorMessage;

export type ConversationStatus =
  | "idle"
  | "awaiting_user"
  | "submitting"
  | "completed"
  | "error";

export type ConversationSnapshot = {
  sessionId: string | null;
  status: ConversationStatus;
  messages: ChatMessage[];
};
