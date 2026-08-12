import { useEffect, useState } from "react";

import {
  ApiError,
  createSession,
  fetchActiveBugIds,
  fetchSessionReports,
  resumeSession,
  saveModifiedReport,
} from "../../../services/api/sessionApi";
import {
  buildDefaultState,
  initializeConversationForBug,
  loadAppState,
  resetConversationForBug,
  saveAppState,
  type PersistedAppState,
} from "../../../services/storage/chatStorage";
import type { SessionReportEntry } from "../types/api";
import type { ChatMessage, ConversationSnapshot } from "../types/chat";

type ActiveConversationState = {
  appState: PersistedAppState;
  availableBugIds: number[];
  bugDiscoveryStatus: "loading" | "ready" | "error";
  draft: string;
  setDraft: (value: string) => void;
  submitDraft: () => Promise<void>;
  submitModifiedReport: (report: Record<string, unknown>) => Promise<void>;
  changeBug: (bugId: number) => void;
  reloadActiveBugs: () => void;
  activeConversation: ConversationSnapshot;
  /** Whether the newest draft report may still be edited and regenerated. */
  canEditReport: boolean;
  /** How many edit-and-regenerate rounds the session has left. */
  editsRemaining: number;
};

const EMPTY_CONVERSATION: ConversationSnapshot = {
  sessionId: null,
  status: "idle",
  messages: [],
};

/**
 * How many times a report may be edited and regenerated. The backend is the
 * authority and reports what is left with every turn; this only covers the gap
 * before the first answer arrives, so it has to match `config.MAX_REPORT_EDITS`.
 */
export const MAX_REPORT_EDITS = 3;

function makeMessageId(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
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
    // Every run of a session is numbered, so a report regenerated from an edit
    // reads as the next draft rather than as a replacement for the last one.
    const revision = response.draft_revision || 1;

    return [
      {
        id: makeMessageId("report"),
        kind: "final_report",
        report: response.final_report,
        heading: `Draft report ${revision}`,
        sessionId: response.session_id,
        variant: "draft",
        revision,
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

/** Rebuild the report cards of a session from the reports its log holds. */
export function reportEntriesToMessages(
  sessionId: string,
  entries: SessionReportEntry[] | undefined,
): ChatMessage[] {
  if (!Array.isArray(entries)) {
    return [];
  }

  return entries.map((entry) => ({
    id: `report-${entry.kind}-${entry.revision}`,
    kind: "final_report",
    report: entry.report,
    heading: entry.label,
    sessionId,
    variant: entry.kind,
    revision: entry.revision,
  }));
}

/**
 * Splice the reports the backend has on file into a locally kept transcript.
 *
 * The transcript is the record of the conversation and the log is the record of
 * the reports, so the reports are replaced wholesale and dropped in where the
 * transcript's own first report card sat.
 */
export function mergeReportMessages(
  messages: ChatMessage[],
  reportMessages: ChatMessage[],
): ChatMessage[] {
  if (reportMessages.length === 0) {
    return messages;
  }

  const others = messages.filter((message) => message.kind !== "final_report");
  // Everything before the transcript's first report card is conversation, so its
  // index in the original list is also its index once the cards are taken out.
  const firstReportIndex = messages.findIndex(
    (message) => message.kind === "final_report",
  );
  const insertAt = firstReportIndex === -1 ? others.length : firstReportIndex;

  return [...others.slice(0, insertAt), ...reportMessages, ...others.slice(insertAt)];
}

export function getRequestMode(snapshot: ConversationSnapshot): "create" | "resume" {
  return snapshot.sessionId ? "resume" : "create";
}

/** Count the report cards of one kind already in a transcript. */
export function countReports(
  messages: ChatMessage[],
  variant: "draft" | "final",
): number {
  return messages.filter(
    (message) =>
      // Transcripts saved before reports were numbered hold agent drafts only.
      message.kind === "final_report" && (message.variant ?? "draft") === variant,
  ).length;
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
  // Bumped by reloadActiveBugs so a failed discovery can be retried without a page reload.
  const [bugDiscoveryAttempt, setBugDiscoveryAttempt] = useState(0);

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
  }, [bugDiscoveryAttempt]);

  function reloadActiveBugs(): void {
    setBugDiscoveryAttempt((attempt) => attempt + 1);
  }

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

  // Until the backend has answered for this session, go by what the transcript
  // shows: a session that has never been edited still has every round left.
  const editsRemaining =
    activeConversation.editsRemaining ??
    Math.max(MAX_REPORT_EDITS - countReports(activeConversation.messages, "final"), 0);
  const canEditReport =
    activeConversation.status === "completed" && editsRemaining > 0;

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

  // Reports live in the session log, so a transcript restored from this browser
  // is brought back in line with what the backend actually has on file.
  useEffect(() => {
    const { sessionId } = activeConversation;
    if (sessionId === null || activeConversation.status !== "completed") {
      return;
    }

    let cancelled = false;

    fetchSessionReports(sessionId)
      .then((response) => {
        if (cancelled) {
          return;
        }

        setAppState((currentState) => {
          const bugKey = String(currentState.selectedBugId);
          const conversation = currentState.conversations[bugKey];

          // Anything the user has since started takes precedence over a reload.
          if (!conversation || conversation.sessionId !== sessionId) {
            return currentState;
          }

          return {
            ...currentState,
            conversations: {
              ...currentState.conversations,
              [bugKey]: {
                ...conversation,
                editsRemaining: response.edits_remaining ?? conversation.editsRemaining,
                messages: mergeReportMessages(
                  conversation.messages,
                  reportEntriesToMessages(sessionId, response.reports),
                ),
              },
            },
          };
        });
      })
      // The transcript already holds the reports this browser saw, so a failed
      // replay costs nothing beyond staying with them.
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
    // Replaying once per completed session is enough; later reports arrive with
    // the responses that produce them.
  }, [activeConversation.sessionId, activeConversation.status]);

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

  /**
   * Save an edited report and let BURT++ rerun on it.
   *
   * The rerun goes in through the same door a typed message does, so it takes a
   * while, but it is single-pass and always comes back with a report. The saved
   * edit and a thinking bubble go up straight away, and the regenerated draft
   * replaces the bubble once the run lands.
   */
  async function submitModifiedReport(report: Record<string, unknown>): Promise<void> {
    const { sessionId } = activeConversation;

    if (
      appState.selectedBugId === null ||
      sessionId === null ||
      activeConversation.status !== "completed"
    ) {
      throw new Error("The completed report is no longer available to edit.");
    }

    if (!canEditReport) {
      throw new Error("This report has already used all of its regenerations.");
    }

    const savedRevision = countReports(activeConversation.messages, "final") + 1;
    const regeneratingSnapshot: ConversationSnapshot = {
      ...activeConversation,
      status: "submitting",
      editsRemaining: Math.max(editsRemaining - 1, 0),
      messages: [
        ...activeConversation.messages,
        {
          id: makeMessageId("report"),
          kind: "final_report",
          report,
          heading: `Final report ${savedRevision}`,
          sessionId,
          variant: "final",
          revision: savedRevision,
        },
        { id: makeMessageId("thinking"), kind: "thinking" },
      ],
    };
    setActiveConversation(regeneratingSnapshot);

    // The rerun owns the rest of the round, and reports its own failure into the
    // transcript, so the editor closes as soon as the edit is on screen.
    void runRegeneration(sessionId, report, regeneratingSnapshot);
  }

  async function runRegeneration(
    sessionId: string,
    report: Record<string, unknown>,
    regeneratingSnapshot: ConversationSnapshot,
  ): Promise<void> {
    try {
      const response = await saveModifiedReport(sessionId, { modified_report: report });

      if (response.status !== "completed" || !response.final_report) {
        throw new Error("BURT++ did not return a regenerated report.");
      }

      setActiveConversation({
        sessionId: response.session_id,
        status: "completed",
        editsRemaining: response.edits_remaining,
        messages: responseToMessages(response).reduce(
          (messages, message) => replaceThinkingMessage(messages, message),
          regeneratingSnapshot.messages,
        ),
      });
    } catch (error) {
      const errorMessage: ChatMessage = {
        id: makeMessageId("error"),
        kind: "error",
        text: buildRecoverableErrorMessage(error),
      };

      setActiveConversation({
        ...regeneratingSnapshot,
        // The saved edit is on file either way, so the report stands completed
        // and the round it consumed is not handed back.
        status: "completed",
        messages: replaceThinkingMessage(regeneratingSnapshot.messages, errorMessage),
      });
    }
  }

  return {
    appState,
    availableBugIds,
    bugDiscoveryStatus,
    draft,
    setDraft,
    submitDraft,
    submitModifiedReport,
    changeBug,
    reloadActiveBugs,
    activeConversation,
    canEditReport,
    editsRemaining,
  };
}
