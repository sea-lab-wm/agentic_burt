import { describe, expect, it } from "vitest";

import {
  buildDefaultState,
  createFreshConversation,
  initializeConversationForBug,
  resetConversationForBug,
} from "../../../services/storage/chatStorage";
import type { ChatMessage } from "../types/chat";
import {
  countReports,
  getRequestMode,
  mergeReportMessages,
  reportEntriesToMessages,
  responseToMessages,
} from "./useChatSession";

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
      draft_revision: 1,
      final_revision: 0,
      edits_remaining: 3,
    });

    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({
      kind: "final_report",
      report: { title: "Crash on save" },
      heading: "Draft report 1",
      variant: "draft",
      revision: 1,
    });
  });

  it("numbers a regenerated report as the next draft of the session", () => {
    const messages = responseToMessages({
      session_id: "session-123",
      status: "completed",
      question: null,
      final_report: { title: "Crash on save" },
      draft_revision: 3,
      final_revision: 2,
      edits_remaining: 1,
    });

    expect(messages[0]).toMatchObject({ heading: "Draft report 3", revision: 3 });
  });
});

describe("report round bookkeeping", () => {
  const draft = (revision: number): ChatMessage => ({
    id: `draft-${revision}`,
    kind: "final_report",
    report: {},
    variant: "draft",
    revision,
  });
  const final = (revision: number): ChatMessage => ({
    id: `final-${revision}`,
    kind: "final_report",
    report: {},
    variant: "final",
    revision,
  });

  it("counts the saved edits of a transcript separately from the drafts", () => {
    const messages = [draft(1), final(1), draft(2)];

    expect(countReports(messages, "final")).toBe(1);
    expect(countReports(messages, "draft")).toBe(2);
  });

  it("reads an unlabelled report card as an agent draft", () => {
    // Transcripts stored before reports carried a variant hold agent drafts only.
    const legacy: ChatMessage = { id: "report-1", kind: "final_report", report: {} };

    expect(countReports([legacy], "draft")).toBe(1);
    expect(countReports([legacy], "final")).toBe(0);
  });
});

describe("replaying reports from the session log", () => {
  const entries = [
    { kind: "draft" as const, revision: 1, label: "Draft report 1", report: { title: "One" } },
    { kind: "final" as const, revision: 1, label: "Final report 1", report: { title: "Edit" } },
    { kind: "draft" as const, revision: 2, label: "Draft report 2", report: { title: "Two" } },
  ];

  it("turns logged reports into cards that carry their own label and revision", () => {
    expect(reportEntriesToMessages("session-1", entries)).toEqual([
      {
        id: "report-draft-1",
        kind: "final_report",
        report: { title: "One" },
        heading: "Draft report 1",
        sessionId: "session-1",
        variant: "draft",
        revision: 1,
      },
      {
        id: "report-final-1",
        kind: "final_report",
        report: { title: "Edit" },
        heading: "Final report 1",
        sessionId: "session-1",
        variant: "final",
        revision: 1,
      },
      {
        id: "report-draft-2",
        kind: "final_report",
        report: { title: "Two" },
        heading: "Draft report 2",
        sessionId: "session-1",
        variant: "draft",
        revision: 2,
      },
    ]);
  });

  it("drops the transcript's own report cards in favour of the logged ones", () => {
    const messages: ChatMessage[] = [
      { id: "user-1", kind: "user", text: "The app crashed." },
      { id: "stale", kind: "final_report", report: { title: "Stale" } },
      { id: "agent-1", kind: "agent", text: "Anything else?" },
    ];

    const merged = mergeReportMessages(
      messages,
      reportEntriesToMessages("session-1", entries),
    );

    expect(merged.map((message) => message.id)).toEqual([
      "user-1",
      "report-draft-1",
      "report-final-1",
      "report-draft-2",
      "agent-1",
    ]);
  });

  it("appends the logged reports to a transcript that has none of its own", () => {
    const messages: ChatMessage[] = [{ id: "user-1", kind: "user", text: "Crashed." }];

    const merged = mergeReportMessages(
      messages,
      reportEntriesToMessages("session-1", entries),
    );

    expect(merged.map((message) => message.id)).toEqual([
      "user-1",
      "report-draft-1",
      "report-final-1",
      "report-draft-2",
    ]);
  });

  it("leaves the transcript alone when the log has no reports to replay", () => {
    const messages: ChatMessage[] = [
      { id: "report-1", kind: "final_report", report: { title: "Local" } },
    ];

    expect(mergeReportMessages(messages, [])).toBe(messages);
    expect(reportEntriesToMessages("session-1", undefined)).toEqual([]);
  });
});
