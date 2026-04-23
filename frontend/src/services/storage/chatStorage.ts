import type { ConversationSnapshot } from "../../features/chat/types/chat";
import { buildOpeningMessages } from "../../features/chat/types/opening";

const STORAGE_KEY = "burt-chat-state";

type PersistedAppState = {
  selectedBugId: number | null;
  conversations: Record<string, ConversationSnapshot>;
};

export function createFreshConversation(bugId: number): ConversationSnapshot {
  return {
    sessionId: null,
    status: "idle",
    messages: buildOpeningMessages(bugId),
  };
}

export function buildDefaultState(): PersistedAppState {
  return {
    selectedBugId: null,
    conversations: {},
  };
}

export function loadAppState(): PersistedAppState {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return buildDefaultState();
    }

    const parsed = JSON.parse(raw) as Partial<PersistedAppState>;
    const selectedBugId =
      typeof parsed.selectedBugId === "number" || parsed.selectedBugId === null
        ? parsed.selectedBugId
        : null;
    const conversations =
      parsed.conversations && typeof parsed.conversations === "object" ? parsed.conversations : {};

    return {
      selectedBugId,
      conversations,
    };
  } catch {
    return buildDefaultState();
  }
}

export function saveAppState(state: PersistedAppState): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function resetConversationForBug(
  state: PersistedAppState,
  bugId: number,
): PersistedAppState {
  return {
    ...state,
    selectedBugId: bugId,
    conversations: {
      ...state.conversations,
      [bugId]: createFreshConversation(bugId),
    },
  };
}

export function initializeConversationForBug(
  state: PersistedAppState,
  bugId: number,
): PersistedAppState {
  return {
    ...state,
    selectedBugId: bugId,
    conversations: {
      ...state.conversations,
      [bugId]: state.conversations[String(bugId)] ?? createFreshConversation(bugId),
    },
  };
}

export type { PersistedAppState };
