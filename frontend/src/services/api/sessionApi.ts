import type {
  ActiveBugIdsResponse,
  ConversationTurnResponse,
  CreateSessionRequest,
  ResumeConversationRequest,
} from "../../features/chat/types/api";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
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
  return requestJson<ConversationTurnResponse>("/api/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchActiveBugIds(): Promise<ActiveBugIdsResponse> {
  return requestJson<ActiveBugIdsResponse>("/api/bugs/active");
}

export function resumeSession(
  sessionId: string,
  payload: ResumeConversationRequest,
): Promise<ConversationTurnResponse> {
  return requestJson<ConversationTurnResponse>(
    `/api/sessions/${sessionId}/messages`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
