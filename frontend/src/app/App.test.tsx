import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const fetchMock = vi.fn<typeof fetch>();

describe("App", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    window.localStorage.clear();
  });

  it("replaces the thinking bubble with the returned question", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          session_id: "session-123",
          status: "awaiting_user",
          question: "What screen were you on?",
          final_report: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Message BURT"), "The app crashed.");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("What screen were you on?")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByLabelText("BURT is thinking")).not.toBeInTheDocument();
    });
  });

  it("wipes the transcript back to opening messages when the bug selection changes", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Message BURT"), "A draft message");
    expect(screen.getByDisplayValue("A draft message")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Select bug to report on"), "135");

    expect(screen.queryByDisplayValue("A draft message")).not.toBeInTheDocument();
    expect(screen.getByText("I’m BURT++, your bug reporting assistant.")).toBeInTheDocument();
  });

  it("renders an inline error bubble on request failure and restores the draft", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Session not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
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

    await user.type(screen.getByLabelText("Message BURT"), "Retry this");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/Reset the bug selection to begin a fresh conversation\./)).toBeInTheDocument();
    expect(screen.getByDisplayValue("Retry this")).toBeInTheDocument();
  });

  it("disables the composer after rendering a completed final report", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          session_id: "session-456",
          status: "completed",
          question: null,
          final_report: { title: "Crash on save" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Message BURT"), "The app crashed.");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Draft report")).toBeInTheDocument();
    expect(screen.getByLabelText("Message BURT")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });
});
