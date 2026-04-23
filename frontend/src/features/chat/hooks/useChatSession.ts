import { useEffect, useState } from "react";

import {
  ApiError,
  createSession,
  fetchActiveBugIds,
  resumeSession,
} from "../../../services/api/sessionApi";
import {
  buildDefaultState,
  initializeConversationForBug,
  loadAppState,
  resetConversationForBug,
  saveAppState,
  type PersistedAppState,
} from "../../../services/storage/chatStorage";
import type { ChatMessage, ConversationSnapshot } from "../types/chat";

type ActiveConversationState = {
  appState: PersistedAppState;
  availableBugIds: number[];
  bugDiscoveryStatus: "loading" | "ready" | "error";
  draft: string;
  setDraft: (value: string) => void;
  submitDraft: () => Promise<void>;
  changeBug: (bugId: number) => void;
  activeConversation: ConversationSnapshot;
};

const EMPTY_CONVERSATION: ConversationSnapshot = {
  sessionId: null,
  status: "idle",
  messages: [],
};

function makeMessageId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function replaceThinkingMessage(messages: ChatMessage[], nextMessage: ChatMessage): ChatMessage[] {
  const nextMessages = [...messages];
  const thinkingIndex = nextMessages.findIndex((message) => message.kind === "thinking");

  if (thinkingIndex === -1) {
    return [...nextMessages, nextMessage];
  }

  nextMessages.splice(thinkingIndex, 1, nextMessage);
  return nextMessages;
}

function buildRecoverableErrorMessage(error: unknown): string {
  if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
    return `${error.message} Reset the bug selection to begin a fresh conversation.`;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "Something went wrong while contacting BURT++.";
}

export function responseToMessages(
  response: Awaited<ReturnType<typeof createSession>>,
): ChatMessage[] {
  if (response.status === "completed" && response.final_report) {
    return [
      {
        id: makeMessageId("report"),
        kind: "final_report",
        report: response.final_report,
      },
    ];
  }

  return [
    {
      id: makeMessageId("agent"),
      kind: "agent",
      text: response.question ?? "BURT++ is ready for your next message.",
    },
  ];
}

export function getRequestMode(snapshot: ConversationSnapshot): "create" | "resume" {
  return snapshot.sessionId ? "resume" : "create";
}

function resolveSelectedBugId(
  currentSelectedBugId: number | null,
  availableBugIds: number[],
): number | null {
  if (currentSelectedBugId !== null && availableBugIds.includes(currentSelectedBugId)) {
    return currentSelectedBugId;
  }

  return availableBugIds[0] ?? null;
}

export function useChatSession(): ActiveConversationState {
  const [appState, setAppState] = useState<PersistedAppState>(() => {
    if (typeof window === "undefined") {
      return buildDefaultState();
    }

    return loadAppState();
  });
  const [availableBugIds, setAvailableBugIds] = useState<number[]>([]);
  const [bugDiscoveryStatus, setBugDiscoveryStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [draft, setDraft] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadActiveBugs(): Promise<void> {
      setBugDiscoveryStatus("loading");

      try {
        const response = await fetchActiveBugIds();
        if (cancelled) {
          return;
        }

        setAvailableBugIds(response.bug_ids);
        setAppState((currentState) => {
          const selectedBugId = resolveSelectedBugId(
            currentState.selectedBugId,
            response.bug_ids,
          );

          if (selectedBugId === null) {
            return buildDefaultState();
          }

          return initializeConversationForBug(currentState, selectedBugId);
        });
        setBugDiscoveryStatus("ready");
      } catch {
        if (cancelled) {
          return;
        }

        setAvailableBugIds([]);
        setAppState(buildDefaultState());
        setBugDiscoveryStatus("error");
      }
    }

    void loadActiveBugs();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    saveAppState(appState);
  }, [appState]);

  const activeConversation =
    appState.selectedBugId === null
      ? EMPTY_CONVERSATION
      : appState.conversations[String(appState.selectedBugId)] ??
        initializeConversationForBug(appState, appState.selectedBugId).conversations[
          String(appState.selectedBugId)
        ]!;

  function setActiveConversation(nextConversation: ConversationSnapshot): void {
    if (appState.selectedBugId === null) {
      return;
    }

    setAppState((currentState) => {
      if (currentState.selectedBugId === null) {
        return currentState;
      }

      return {
        ...currentState,
        conversations: {
          ...currentState.conversations,
          [currentState.selectedBugId]: nextConversation,
        },
      };
    });
  }

  function changeBug(bugId: number): void {
    if (!availableBugIds.includes(bugId)) {
      return;
    }

    setDraft("");
    setAppState((currentState) => resetConversationForBug(currentState, bugId));
  }

  async function submitDraft(): Promise<void> {
    const trimmedDraft = draft.trim();
    if (
      !trimmedDraft ||
      appState.selectedBugId === null ||
      bugDiscoveryStatus !== "ready" ||
      activeConversation.status === "submitting" ||
      activeConversation.status === "completed"
    ) {
      return;
    }

    const userMessage: ChatMessage = {
      id: makeMessageId("user"),
      kind: "user",
      text: trimmedDraft,
    };
    const thinkingMessage: ChatMessage = {
      id: makeMessageId("thinking"),
      kind: "thinking",
    };

    const submittingSnapshot: ConversationSnapshot = {
      ...activeConversation,
      status: "submitting",
      messages: [...activeConversation.messages, userMessage, thinkingMessage],
    };
    setActiveConversation(submittingSnapshot);
    setDraft("");

    try {
      const response =
        getRequestMode(activeConversation) === "create"
          ? await createSession({
              bug_id: appState.selectedBugId,
              user_description: trimmedDraft,
            })
          : await resumeSession(activeConversation.sessionId!, {
              user_description: trimmedDraft,
            });

      const nextMessages = responseToMessages(response);
      setActiveConversation({
        sessionId: response.session_id,
        status: response.status,
        messages: nextMessages.reduce(
          (messages, message) => replaceThinkingMessage(messages, message),
          submittingSnapshot.messages,
        ),
      });
    } catch (error) {
      const errorMessage: ChatMessage = {
        id: makeMessageId("error"),
        kind: "error",
        text: buildRecoverableErrorMessage(error),
      };
      setActiveConversation({
        ...submittingSnapshot,
        status: "error",
        messages: replaceThinkingMessage(submittingSnapshot.messages, errorMessage),
      });
      setDraft(trimmedDraft);
    }
  }

  return {
    appState,
    availableBugIds,
    bugDiscoveryStatus,
    draft,
    setDraft,
    submitDraft,
    changeBug,
    activeConversation,
  };
}
