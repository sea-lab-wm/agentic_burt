import { BUG_OPTIONS } from "../../config/bugs";
import type { ConversationSnapshot } from "../../features/chat/types/chat";
import { buildOpeningMessages } from "../../features/chat/types/opening";

const STORAGE_KEY = "burt-chat-state";

type PersistedAppState = {
  selectedBugId: number;
  conversations: Record<string, ConversationSnapshot>;
};

function defaultBugId(): number {
  return BUG_OPTIONS[0]?.value ?? 10;
}

export function createFreshConversation(bugId: number): ConversationSnapshot {
  return {
    sessionId: null,
    status: "idle",
    messages: buildOpeningMessages(bugId),
  };
}

export function buildDefaultState(): PersistedAppState {
  const selectedBugId = defaultBugId();
  return {
    selectedBugId,
    conversations: {
      [selectedBugId]: createFreshConversation(selectedBugId),
    },
  };
}

export function loadAppState(): PersistedAppState {
  const fallback = buildDefaultState();

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return fallback;
    }

    const parsed = JSON.parse(raw) as Partial<PersistedAppState>;
    const selectedBugId =
      typeof parsed.selectedBugId === "number" ? parsed.selectedBugId : fallback.selectedBugId;
    const conversations = parsed.conversations ?? {};
    const currentConversation =
      conversations[String(selectedBugId)] ?? createFreshConversation(selectedBugId);

    return {
      selectedBugId,
      conversations: {
        ...conversations,
        [selectedBugId]: currentConversation,
      },
    };
  } catch {
    return fallback;
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

export type { PersistedAppState };
