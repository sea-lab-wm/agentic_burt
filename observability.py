"""Observability models and helpers for runtime logging and token tracking."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, List, Optional
import time

from langchain_core.callbacks import BaseCallbackHandler
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
    actions: List[Action]


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
    def from_events(cls, events: List[LLMUsageEvent]) -> "TokenConsumptionSummary":
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


class FullReportRecord(BaseModel):
    """Terminal record that stores the generated report payload."""

    record_type: str = "full_report"
    session_id: str
    full_report: dict[str, Any]


class ConversationSummaryRecord(BaseModel):
    """Final session-level summary appended to each log file."""

    record_type: str = "conversation_summary"
    session_id: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    total_latency_seconds: Optional[float] = None
    total_conversation_turns: int
    token_consumption: TokenConsumptionSummary


class ObservabilitySink(ABC):
    """Persistence backend for observability records."""

    @abstractmethod
    def append_turn(self, turn_record: ConversationTurn, filepath: Path) -> None:
        """Persist one completed turn record."""

    @abstractmethod
    def append_full_report(
        self, full_report_record: FullReportRecord, filepath: Path
    ) -> None:
        """Persist the generated full-report record."""

    @abstractmethod
    def append_conversation_summary(
        self, summary_record: ConversationSummaryRecord, filepath: Path
    ) -> None:
        """Persist the final conversation summary record."""


class LocalFileSink(ObservabilitySink):
    """Append observability records to a local file."""

    def _append_record(self, record: BaseModel, filepath: Path) -> None:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with filepath.open("a", encoding="utf-8") as file_handle:
            file_handle.write(record.model_dump_json(indent=2))
            file_handle.write("\n")

    def append_turn(self, turn_record: ConversationTurn, filepath: Path) -> None:
        self._append_record(turn_record, filepath)

    def append_full_report(
        self, full_report_record: FullReportRecord, filepath: Path
    ) -> None:
        self._append_record(full_report_record, filepath)

    def append_conversation_summary(
        self, summary_record: ConversationSummaryRecord, filepath: Path
    ) -> None:
        self._append_record(summary_record, filepath)


class TurnLogger:
    """Collect one active turn and session-wide aggregate observability state."""

    def __init__(
        self,
        filepath: str,
        session_id: str,
        sink: Optional[ObservabilitySink] = None,
    ):
        self.filepath = Path(filepath)
        self.session_id = str(session_id)
        self.sink = sink or LocalFileSink()
        self.num_turns: int = 0
        self.current_turn: Optional[ConversationTurn] = None
        self._current_action_name: Optional[ActionName] = None
        self._current_action_usage_events: List[LLMUsageEvent] = []
        self._session_usage_events: List[LLMUsageEvent] = []
        self._started_at: Optional[datetime] = None
        self._ended_at: Optional[datetime] = None
        self._session_start_perf: Optional[float] = None
        self._session_total_latency_seconds: Optional[float] = None
        self._summary_record: Optional[ConversationSummaryRecord] = None

    def start_session(self) -> None:
        """Mark the beginning of a session for aggregate timing."""
        self._started_at = datetime.now(timezone.utc)
        self._session_start_perf = time.perf_counter()

    def finish_session(self) -> ConversationSummaryRecord:
        """Build and return the final conversation summary record."""
        self._ended_at = datetime.now(timezone.utc)
        if self._session_start_perf is None:
            self._session_total_latency_seconds = None
        else:
            self._session_total_latency_seconds = time.perf_counter() - self._session_start_perf

        self._summary_record = ConversationSummaryRecord(
            session_id=self.session_id,
            started_at=self._started_at.isoformat() if self._started_at else None,
            ended_at=self._ended_at.isoformat() if self._ended_at else None,
            total_latency_seconds=self._session_total_latency_seconds,
            total_conversation_turns=self.num_turns,
            token_consumption=TokenConsumptionSummary.from_events(
                self._session_usage_events
            ),
        )
        return self._summary_record

    def start_action(self, action_name: ActionName) -> None:
        """Begin action-scoped LLM-usage capture for the next logged action."""
        self._current_action_name = action_name
        self._current_action_usage_events = []

    def record_llm_usage(self, usage_event: LLMUsageEvent) -> None:
        """Record one LLM usage event for action and session-level accounting."""
        if self._current_action_name is not None:
            self._current_action_usage_events.append(usage_event)
        self._session_usage_events.append(usage_event)

    def end_action(self) -> Optional[TokenConsumptionSummary]:
        """End action-scoped capture and return its aggregate token summary."""
        if not self._current_action_usage_events:
            self._current_action_name = None
            return None

        summary = TokenConsumptionSummary.from_events(self._current_action_usage_events)
        self._current_action_name = None
        self._current_action_usage_events = []
        return summary

    def add_action_to_turn(
        self,
        entity: Entity,
        action_name: ActionName,
        output: dict[str, Any] | StrictStr,
        meta_data: MetaData,
    ) -> None:
        """Append one action to the active turn, starting it on user input."""
        if action_name == ActionName.user_description:
            if self.current_turn is not None:
                raise ValueError(
                    "Cannot start a new user_description turn before the current turn is flushed."
                )
            self.num_turns += 1
            self.current_turn = ConversationTurn(
                session_id=self.session_id,
                turn=self.num_turns,
                actions=[],
            )
        elif self.current_turn is None:
            raise ValueError(
                "Cannot log non-user action before the first user_description turn exists."
            )

        new_action = Action(
            entity=entity,
            action_name=action_name,
            output=output,
            meta_data=meta_data,
        )
        self.current_turn.actions.append(new_action)

    def build_turn_record(self) -> Optional[ConversationTurn]:
        """Return the current turn record, if one exists."""
        if self.current_turn is None:
            return None
        return self.current_turn.model_copy(deep=True)

    def reset_turn(self) -> None:
        """Clear active turn state after it has been flushed."""
        self.current_turn = None
        self._current_action_name = None
        self._current_action_usage_events = []


def _coerce_optional_int(value: Any) -> Optional[int]:
    """Best-effort conversion of a numeric-like value to ``int``."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_token_usage(
    token_usage: dict[str, Any],
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Normalize provider token-usage payload keys into input/output/total."""
    input_tokens = _coerce_optional_int(
        token_usage.get("input_tokens", token_usage.get("prompt_tokens"))
    )
    output_tokens = _coerce_optional_int(
        token_usage.get("output_tokens", token_usage.get("completion_tokens"))
    )
    total_tokens = _coerce_optional_int(token_usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens


class ObservabilityTokenCallback(BaseCallbackHandler):
    """Capture provider token usage and forward normalized events to the logger."""

    def __init__(self, logger: TurnLogger, provider: str = "openai"):
        super().__init__()
        self.logger = logger
        self.provider = provider

    def on_llm_end(self, response: Any, **kwargs: Any) -> Any:
        """Capture provider token usage when an LLM call completes."""
        llm_output = getattr(response, "llm_output", None) or {}
        usage = llm_output.get("token_usage")
        model_name = llm_output.get("model_name")

        if isinstance(usage, dict):
            input_tokens, output_tokens, total_tokens = _extract_token_usage(usage)
            self.logger.record_llm_usage(
                LLMUsageEvent(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    model=model_name,
                    provider=self.provider,
                    usage_available=True,
                )
            )
            return

        generations = getattr(response, "generations", []) or []
        for generation_list in generations:
            for generation in generation_list:
                message = getattr(generation, "message", None)
                if message is None:
                    continue

                usage_metadata = getattr(message, "usage_metadata", None) or {}
                response_metadata = getattr(message, "response_metadata", None) or {}
                model_name = model_name or response_metadata.get("model_name")
                token_usage = response_metadata.get("token_usage")

                if usage_metadata:
                    input_tokens, output_tokens, total_tokens = _extract_token_usage(
                        usage_metadata
                    )
                    self.logger.record_llm_usage(
                        LLMUsageEvent(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens,
                            model=model_name,
                            provider=self.provider,
                            usage_available=True,
                        )
                    )
                    return

                if isinstance(token_usage, dict):
                    input_tokens, output_tokens, total_tokens = _extract_token_usage(
                        token_usage
                    )
                    self.logger.record_llm_usage(
                        LLMUsageEvent(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens,
                            model=model_name,
                            provider=self.provider,
                            usage_available=True,
                        )
                    )
                    return

        self.logger.record_llm_usage(
            LLMUsageEvent(
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                model=model_name,
                provider=self.provider,
                usage_available=False,
            )
        )

#NOTE: A little overcomplicated at the moment, just fetches runtime context from different ways of passing it to decorated functions
def _get_runtime_context(*args: Any, **kwargs: Any) -> Any:
    """Resolve the request-local runtime context from function args or kwargs.
    """
    runtime_context = kwargs.get("runtime_context")
    if runtime_context is not None:
        return runtime_context

    config = kwargs.get("config")
    if isinstance(config, dict):
        runtime_context = (config.get("configurable") or {}).get("runtime_context")
        if runtime_context is not None:
            return runtime_context

    for arg in args:
        if hasattr(arg, "logger") and hasattr(arg, "model"):
            return arg
        if isinstance(arg, dict):
            runtime_context = (arg.get("configurable") or {}).get("runtime_context")
            if runtime_context is not None:
                return runtime_context

    raise ValueError("runtime_context with a logger is required for observability logging.")


def log_action(entity: Entity, action_name: ActionName):
    """Build a decorator that logs one runtime action and its metadata."""

    def decorator(node_func):
        @wraps(node_func)
        def wrapper(*args, **kwargs):
            runtime_context = _get_runtime_context(*args, **kwargs)
            logger = runtime_context.logger
            logger.start_action(action_name)

            start = time.perf_counter()
            output = node_func(*args, **kwargs)
            action_latency = f"{(time.perf_counter() - start)} s"
            node_token_consumption = logger.end_action()
            meta_data = MetaData(
                latency=action_latency,
                node_token_consumption=node_token_consumption,
            )
            logger.add_action_to_turn(
                entity=entity,
                action_name=action_name,
                output=output,
                meta_data=meta_data,
            )
            return output

        return wrapper

    return decorator
