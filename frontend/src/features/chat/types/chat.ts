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
  heading?: string;
  // Needed to fetch the report's screenshots, including after a page reload.
  sessionId?: string;
  /** Whether BURT++ generated this report or the user saved it. */
  variant?: "draft" | "final";
  /** Which round of the session this report belongs to, counted per variant. */
  revision?: number;
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
  /** How many edit-and-regenerate rounds the session has left, once it has one. */
  editsRemaining?: number;
};
