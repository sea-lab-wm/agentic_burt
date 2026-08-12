from typing import Any, Literal

from pydantic import BaseModel

import config


class CreateSessionRequest(BaseModel):
    """Input payload used to create a new agent conversation session."""

    bug_id: int
    user_description: str


class ResumeConversationRequest(BaseModel):
    """Input payload containing the user's next message, submitted to resume an existing agent conversation session."""

    user_description: str


class ModifyReportRequest(BaseModel):
    """Input payload containing the user's edited final report."""

    modified_report: dict[str, Any]


class ConversationTurnResponse(BaseModel):
    """API response describing the current question or final report for an agent conversation session.
    This is returned following an agent acting upon a user description both initially and on resume of session
    """

    session_id: str
    status: Literal["awaiting_user", "completed"]
    question: str | None = None
    final_report: dict[str, Any] | None = None
    # Revision bookkeeping, so the client can label the report it just received
    # and know whether another edit is still allowed.
    draft_revision: int = 0
    final_revision: int = 0
    edits_remaining: int = config.MAX_REPORT_EDITS


class SessionReportEntry(BaseModel):
    """One report a session produced, in the order it was written to the log."""

    kind: Literal["draft", "final"]
    revision: int
    label: str
    report: dict[str, Any]


class SessionReportsResponse(BaseModel):
    """API response replaying every report a session has on file, oldest first."""

    session_id: str
    bug_id: int
    reports: list[SessionReportEntry]
    draft_revision: int
    final_revision: int
    edits_remaining: int


class ActiveBugIdsResponse(BaseModel):
    """API response describing which bug ids are currently reportable."""

    bug_ids: list[int]


class ReportStepMedia(BaseModel):
    """One reproduction step and the GUI graph transition it was mapped to."""

    index: int
    text: str
    transition_id: str | None = None
    has_screenshot: bool


class ReportMediaResponse(BaseModel):
    """API response describing which report fields have a retrievable screenshot."""

    session_id: str
    bug_id: int
    app_name: str | None = None
    screen_id: str | None = None
    has_screen_screenshot: bool
    steps: list[ReportStepMedia]
