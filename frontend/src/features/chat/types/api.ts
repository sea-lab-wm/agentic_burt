export type CreateSessionRequest = {
  bug_id: number;
  user_description: string;
};

export type ResumeConversationRequest = {
  user_description: string;
};

export type ConversationTurnResponse = {
  session_id: string;
  status: "awaiting_user" | "completed";
  question: string | null;
  final_report: Record<string, unknown> | null;
};
