import { describe, expect, it } from "vitest";

import {
  buildDefaultState,
  createFreshConversation,
  initializeConversationForBug,
  resetConversationForBug,
} from "../../../services/storage/chatStorage";
import { getRequestMode, responseToMessages } from "./useChatSession";

describe("useChatSession helpers", () => {
  it("routes requests to create when there is no session id", () => {
    expect(getRequestMode(createFreshConversation(10))).toBe("create");
  });

  it("routes requests to resume when a session id exists", () => {
    expect(
      getRequestMode({
        ...createFreshConversation(10),
        sessionId: "session-123",
      }),
    ).toBe("resume");
  });

  it("resets the selected bug transcript to the opening state", () => {
    const state = buildDefaultState();
    const resetState = resetConversationForBug(state, 135);

    expect(resetState.selectedBugId).toBe(135);
    expect(resetState.conversations["135"]?.sessionId).toBeNull();
    expect(resetState.conversations["135"]?.messages).toHaveLength(2);
  });

  it("initializes the first discovered bug with opening messages", () => {
    const state = buildDefaultState();
    const initializedState = initializeConversationForBug(state, 10);

    expect(initializedState.selectedBugId).toBe(10);
    expect(initializedState.conversations["10"]?.sessionId).toBeNull();
    expect(initializedState.conversations["10"]?.messages).toHaveLength(2);
  });

  it("maps final report responses into a final report message", () => {
    const messages = responseToMessages({
      session_id: "session-123",
      status: "completed",
      question: null,
      final_report: { title: "Crash on save" },
    });

    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({
      kind: "final_report",
      report: { title: "Crash on save" },
    });
  });
});
