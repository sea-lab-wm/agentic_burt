import type {
  ActiveBugIdsResponse,
  ConversationTurnResponse,
  CreateSessionRequest,
  ModifyReportRequest,
  ResumeConversationRequest,
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
