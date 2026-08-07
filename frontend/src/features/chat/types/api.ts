export type CreateSessionRequest = {
  bug_id: number;
  user_description: string;
};

export type ActiveBugIdsResponse = {
  bug_ids: number[];
};

export type ResumeConversationRequest = {
  user_description: string;
};

export type ModifyReportRequest = {
  modified_report: Record<string, unknown>;
};

export type ConversationTurnResponse = {
  session_id: string;
  status: "awaiting_user" | "completed";
  question: string | null;
  final_report: Record<string, unknown> | null;
};
