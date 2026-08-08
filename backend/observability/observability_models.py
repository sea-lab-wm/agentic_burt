"""Shared observability enums and record models."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, StrictStr


class Entity(str, Enum):
    """Actors that can produce logged actions."""

    user = "user"
    bot = "bot"


class ActionName(str, Enum):
    """Runtime action names that can appear in observability logs."""

    user_description = "user_description"
    information_element_extraction = "information_element_extraction"
    clarity_check = "clarity_check"
    clarity_follow_up = "clarity_follow_up"
    extract_and_update = "extract_and_update"
    evaluate = "evaluate"
    follow_up = "follow_up"
    generate_report = "generate_report"


class MetaData(BaseModel):
    """Per-action metadata stored alongside a logged output."""

    latency: str
    node_token_consumption: Optional["TokenConsumptionSummary"] = None


class Action(BaseModel):
    """One logged user or agent action inside a turn."""

    entity: Entity
    action_name: ActionName
    output: dict[str, Any] | StrictStr
    meta_data: MetaData


class ConversationTurn(BaseModel):
    """One logged conversation turn containing one or more actions."""

    session_id: str
    turn: int
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    actions: list[Action]


class LLMUsageEvent(BaseModel):
    """Normalized token-usage event captured from one provider response."""

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    usage_available: bool = False


class TokenConsumptionSummary(BaseModel):
    """Aggregate token-usage totals and capture-quality counters."""

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    llm_calls: int = 0
    llm_calls_with_usage: int = 0
    llm_calls_missing_usage: int = 0

    @classmethod
    def from_events(cls, events: list[LLMUsageEvent]) -> "TokenConsumptionSummary":
        """Build an aggregate token summary from raw per-call usage events."""
        llm_calls = len(events)
        with_usage = sum(1 for event in events if event.usage_available)
        missing_usage = llm_calls - with_usage

        if llm_calls == 0:
            return cls(
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                llm_calls=0,
                llm_calls_with_usage=0,
                llm_calls_missing_usage=0,
            )

        if missing_usage > 0:
            return cls(
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                llm_calls=llm_calls,
                llm_calls_with_usage=with_usage,
                llm_calls_missing_usage=missing_usage,
            )

        input_total = sum(event.input_tokens or 0 for event in events)
        output_total = sum(event.output_tokens or 0 for event in events)
        total = sum(
            event.total_tokens
            if event.total_tokens is not None
            else (event.input_tokens or 0) + (event.output_tokens or 0)
            for event in events
        )

        return cls(
            input_tokens=input_total,
            output_tokens=output_total,
            total_tokens=total,
            llm_calls=llm_calls,
            llm_calls_with_usage=with_usage,
            llm_calls_missing_usage=0,
        )


class RunMetadata(BaseModel):
    """Stable run identity and source metadata for evaluator joins."""

    bug_id: Optional[int] = None
    description_level: Optional[str] = None
    input_source: Optional[str] = None
    runtime: Optional[str] = None


class DraftReportRecord(BaseModel):
    """Terminal record that stores the generated report payload."""

    record_type: str = "draft_report"
    session_id: str
    draft_report: dict[str, Any]


class ModifiedReportRecord(BaseModel):
    """Post-terminal record that stores a user-edited report payload."""

    record_type: str = "modified_report"
    session_id: str
    modified_report: dict[str, Any]


class ConversationSummaryRecord(BaseModel):
    """Final session-level summary appended to each log file."""

    record_type: str = "conversation_summary"
    session_id: str
    run_metadata: Optional[RunMetadata] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    total_wall_clock_seconds: Optional[float] = None
    total_turn_processing_seconds: Optional[float] = None
    total_conversation_turns: int
    token_consumption: TokenConsumptionSummary
