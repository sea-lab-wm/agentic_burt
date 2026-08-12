"""Replay every report one session produced, read back out of its log file.

A session can be regenerated from a saved edit, so its log holds an alternating
run of agent-authored drafts and user-saved finals. The frontend rebuilds its
report cards from this, which is what lets a reloaded page show the whole history
rather than only the report the last request happened to return.
"""

from typing import Any

import config
from app.schemas.sessions import SessionReportEntry, SessionReportsResponse
from app.services.burt_runtime import (
    InvalidSessionError,
    SessionNotFoundError,
    build_api_log_path,
    report_revisions,
)
from app.services.session_store import get_session
from observability.observability_sinks import parse_log_records

DRAFT_RECORD_TYPE = "draft_report"
MODIFIED_RECORD_TYPE = "modified_report"

# Which payload key each record type carries its report under.
_REPORT_KEY_BY_RECORD_TYPE = {
    DRAFT_RECORD_TYPE: "draft_report",
    MODIFIED_RECORD_TYPE: "modified_report",
}

_KIND_BY_RECORD_TYPE = {DRAFT_RECORD_TYPE: "draft", MODIFIED_RECORD_TYPE: "final"}

_LABEL_BY_KIND = {"draft": "Draft report", "final": "Final report"}


def _revision_of(record: dict[str, Any], position: int) -> int:
    """Read a record's revision, falling back to its position for pre-revision logs."""
    revision = record.get("revision")
    if isinstance(revision, int) and revision > 0:
        return revision
    return position


def read_report_entries(records: list[dict[str, Any]]) -> list[SessionReportEntry]:
    """Collect the session's reports from its log records, oldest first."""
    entries: list[SessionReportEntry] = []
    seen_by_kind = {"draft": 0, "final": 0}

    for record in records:
        record_type = record.get("record_type")
        kind = _KIND_BY_RECORD_TYPE.get(record_type)
        if kind is None:
            continue

        report = record.get(_REPORT_KEY_BY_RECORD_TYPE[record_type])
        if not isinstance(report, dict):
            continue

        seen_by_kind[kind] += 1
        revision = _revision_of(record, seen_by_kind[kind])
        entries.append(
            SessionReportEntry(
                kind=kind,
                revision=revision,
                label=f"{_LABEL_BY_KIND[kind]} {revision}",
                report=report,
            )
        )

    return entries


def build_session_reports(session_id: str) -> SessionReportsResponse:
    """Describe every report a session has on file and how many edits it has left."""
    session_record = get_session(session_id)
    if session_record is None:
        raise SessionNotFoundError(f"Session {session_id} was not found.")

    bug_id = session_record.get("bug_id")
    if not isinstance(bug_id, int):
        raise InvalidSessionError(
            f"Session {session_id} is missing required report metadata."
        )

    entries = read_report_entries(parse_log_records(build_api_log_path(session_id)))

    # The session record counts a round as spent the moment it starts, so it leads
    # the log while a regeneration is still running.
    record_drafts, record_finals = report_revisions(session_record)
    draft_revision = max(
        (entry.revision for entry in entries if entry.kind == "draft"),
        default=0,
    )
    final_revision = max(
        (entry.revision for entry in entries if entry.kind == "final"),
        default=0,
    )

    final_revision = max(final_revision, record_finals)

    return SessionReportsResponse(
        session_id=session_id,
        bug_id=bug_id,
        reports=entries,
        draft_revision=max(draft_revision, record_drafts),
        final_revision=final_revision,
        edits_remaining=max(config.MAX_REPORT_EDITS - final_revision, 0),
    )
