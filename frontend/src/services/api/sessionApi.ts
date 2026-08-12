import type {
  ActiveBugIdsResponse,
  ConversationTurnResponse,
  CreateSessionRequest,
  ModifyReportRequest,
  ReportMediaResponse,
  ResumeConversationRequest,
  ScreenshotKind,
  SessionReportsResponse,
} from "../../features/chat/types/api";

const API_BASE_PATH = (import.meta.env.VITE_API_BASE_PATH ?? "/api").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function apiPath(path: string): string {
  return `${API_BASE_PATH}${path}`;
}

async function requestJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(payload?.detail ?? "Request failed.", response.status);
  }

  return (await response.json()) as T;
}

export function createSession(
  payload: CreateSessionRequest,
): Promise<ConversationTurnResponse> {
  return requestJson<ConversationTurnResponse>(apiPath("/sessions"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchActiveBugIds(): Promise<ActiveBugIdsResponse> {
  return requestJson<ActiveBugIdsResponse>(apiPath("/bugs/active"));
}

export function resumeSession(
  sessionId: string,
  payload: ResumeConversationRequest,
): Promise<ConversationTurnResponse> {
  return requestJson<ConversationTurnResponse>(
    apiPath(`/sessions/${sessionId}/messages`),
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

/**
 * Save an edited report and rerun BURT++ on it. The rerun is single-pass, so the
 * response carries the regenerated draft rather than another question.
 */
export function saveModifiedReport(
  sessionId: string,
  payload: ModifyReportRequest,
): Promise<ConversationTurnResponse> {
  return requestJson<ConversationTurnResponse>(
    apiPath(`/sessions/${sessionId}/report`),
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

/** Read back every report a session has written to its log, oldest first. */
export function fetchSessionReports(sessionId: string): Promise<SessionReportsResponse> {
  return requestJson<SessionReportsResponse>(
    apiPath(`/sessions/${encodeURIComponent(sessionId)}/reports`),
  );
}

export function fetchReportMedia(
  sessionId: string,
  revision?: number,
): Promise<ReportMediaResponse> {
  // A regenerated session holds one run's screenshots per revision, so a report
  // card asks for its own rather than for whichever run finished last.
  const query = revision === undefined ? "" : `?revision=${revision}`;

  return requestJson<ReportMediaResponse>(
    apiPath(`/sessions/${encodeURIComponent(sessionId)}/report-media${query}`),
  );
}

/** Build the <img> source for one GUI graph screenshot captured for a session's bug. */
export function buildScreenshotUrl(
  sessionId: string,
  kind: ScreenshotKind,
  imageId: string,
): string {
  return apiPath(
    `/sessions/${encodeURIComponent(sessionId)}/screenshots/${kind}/${encodeURIComponent(imageId)}`,
  );
}
