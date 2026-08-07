import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("App", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    window.localStorage.clear();
  });

  it("loads active bug ids and renders the dropdown from the API", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ bug_ids: [2, 10, 135] }));

    render(<App />);

    expect(await screen.findByRole("option", { name: "Bug 135" })).toBeInTheDocument();
    expect(screen.getByLabelText("Select bug to report on")).toHaveValue("2");
    expect(screen.getByText("I’m BURT++, your bug reporting assistant.")).toBeInTheDocument();
  });

  it("preserves the stored active bug session instead of resetting to the first active bug", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ bug_ids: [2, 10, 135] }));

    window.localStorage.setItem(
      "burt-chat-state",
      JSON.stringify({
        selectedBugId: 135,
        conversations: {
          "135": {
            sessionId: "session-135",
            status: "awaiting_user",
            messages: [
              {
                id: "agent-1",
                kind: "agent",
                text: "Which screen were you on?",
              },
            ],
          },
        },
      }),
    );

    render(<App />);

    expect(await screen.findByText("Which screen were you on?")).toBeInTheDocument();
    expect(screen.getByLabelText("Select bug to report on")).toHaveValue("135");
  });

  it("replaces the thinking bubble with the returned question", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ bug_ids: [2, 10, 135] }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        session_id: "session-123",
        status: "awaiting_user",
        question: "What screen were you on?",
        final_report: null,
      }),
    );

    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("I’m BURT++, your bug reporting assistant.");

    await user.type(screen.getByLabelText("Message BURT"), "The app crashed.");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("What screen were you on?")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByLabelText("BURT is thinking")).not.toBeInTheDocument();
    });
  });

  it("wipes the transcript back to opening messages when the bug selection changes", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ bug_ids: [2, 10, 135] }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("I’m BURT++, your bug reporting assistant.");

    await user.type(screen.getByLabelText("Message BURT"), "A draft message");
    expect(screen.getByDisplayValue("A draft message")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Select bug to report on"), "135");

    expect(screen.queryByDisplayValue("A draft message")).not.toBeInTheDocument();
    expect(screen.getByText("I’m BURT++, your bug reporting assistant.")).toBeInTheDocument();
  });

  it("renders an inline error bubble on request failure and restores the draft", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ bug_ids: [2, 10, 135] }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Session not found" }, 404),
    );

    window.localStorage.setItem(
      "burt-chat-state",
      JSON.stringify({
        selectedBugId: 2,
        conversations: {
          "2": {
            sessionId: "missing-session",
            status: "awaiting_user",
            messages: [
              {
                id: "opening-1",
                kind: "agent",
                text: "I’m BURT++, your bug reporting assistant.",
              },
            ],
          },
        },
      }),
    );

    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("I’m BURT++, your bug reporting assistant.");

    await user.type(screen.getByLabelText("Message BURT"), "Retry this");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/Reset the bug selection to begin a fresh conversation\./)).toBeInTheDocument();
    expect(screen.getByDisplayValue("Retry this")).toBeInTheDocument();
  });

  it("disables the composer after rendering a completed final report", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ bug_ids: [2, 10, 135] }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        session_id: "session-456",
        status: "completed",
        question: null,
        final_report: { title: "Crash on save" },
      }),
    );

    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("I’m BURT++, your bug reporting assistant.");

    await user.type(screen.getByLabelText("Message BURT"), "The app crashed.");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Draft report")).toBeInTheDocument();
    expect(screen.getByLabelText("Message BURT")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("hides step identifiers and appends an edited final report after save", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ bug_ids: [2, 10, 135] }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        session_id: "session-456",
        status: "completed",
        question: null,
        final_report: {
          title: "Crash on save",
          steps_to_reproduce: "1. Open the app. <abc-123>\n2. Tap Save. <def-456>",
        },
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        session_id: "session-456",
        status: "completed",
        question: null,
        final_report: {
          title: "Edited crash on save",
          steps_to_reproduce: "1. Open the app.\n2. Tap Save.",
        },
      }),
    );

    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("I’m BURT++, your bug reporting assistant.");

    await user.type(screen.getByLabelText("Message BURT"), "The app crashed.");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Draft report")).toBeInTheDocument();
    expect(
      screen.getByText((_, element) =>
        element?.tagName.toLowerCase() === "p" &&
        element.textContent === "1. Open the app.\n2. Tap Save.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/<abc-123>|<def-456>/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Edit" }));
    const editor = screen.getByLabelText("Bug report JSON");
    expect(editor).toHaveValue(
      JSON.stringify(
        {
          title: "Crash on save",
          steps_to_reproduce: "1. Open the app.\n2. Tap Save.",
        },
        null,
        2,
      ),
    );

    fireEvent.change(editor, {
      target: {
        value: JSON.stringify(
          {
            title: "Edited crash on save",
            steps_to_reproduce: "1. Open the app.\n2. Tap Save.",
          },
          null,
          2,
        ),
      },
    });
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Final Report")).toBeInTheDocument();
    expect(screen.getByText("Edited crash on save")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/sessions/session-456/report",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          modified_report: {
            title: "Edited crash on save",
            steps_to_reproduce: "1. Open the app.\n2. Tap Save.",
          },
        }),
      }),
    );
  });

  it("keeps the selector and composer disabled when active bug discovery fails", async () => {
    fetchMock.mockRejectedValueOnce(new Error("Network error"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText("Select bug to report on")).toBeDisabled();
    });
    expect(screen.getByLabelText("Message BURT")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("keeps the selector and composer disabled when no active bugs are returned", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ bug_ids: [] }));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText("Select bug to report on")).toBeDisabled();
    });
    expect(screen.getByRole("option", { name: "No active bugs available" })).toBeInTheDocument();
    expect(screen.getByLabelText("Message BURT")).toBeDisabled();
  });
});
