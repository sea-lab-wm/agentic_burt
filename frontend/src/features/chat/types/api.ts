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

/** Directory the screenshot lives in: a screen reference vs. a reproduction step. */
export type ScreenshotKind = "states" | "transitions";

export type ReportStepMedia = {
  index: number;
  text: string;
  transition_id: string | null;
  has_screenshot: boolean;
};

export type ReportMediaResponse = {
  session_id: string;
  bug_id: number;
  app_name: string | null;
  screen_id: string | null;
  has_screen_screenshot: boolean;
  steps: ReportStepMedia[];
};
