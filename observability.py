"""Observability models and helpers for runtime logging and token tracking."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
import json
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
    """One logged conversation turn containing one or more actions, session_id, turn start time and turn end time."""

    session_id: str
    turn: int
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
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


class FinalReportRecord(BaseModel):
    """Terminal record that stores the generated report payload."""

    record_type: str = "final_report"
    session_id: str
    final_report: dict[str, Any]


class ConversationSummaryRecord(BaseModel):
    """Final session-level summary appended to each log file."""

    record_type: str = "conversation_summary"
    session_id: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    total_wall_clock_seconds: Optional[float] = None
    total_turn_processing_seconds: Optional[float] = None
    total_conversation_turns: int
    token_consumption: TokenConsumptionSummary


class ObservabilitySink(ABC):
    """Persistence backend for observability records."""

    @abstractmethod
    def append_turn(self, turn_record: ConversationTurn, filepath: Path) -> None:
        """Persist one completed turn record."""

    @abstractmethod
    def finalize_session(
        self,
        *,
        session_id: str,
        filepath: Path,
        final_report: dict[str, Any],
    ) -> None:
        """Append final report and reconstructed conversation summary records to finalize json logs."""

    def _aggregate_action_token_summaries(
        self,
        turn_records: List[ConversationTurn],
    ) -> TokenConsumptionSummary:
        """Aggregate per-action token summaries across persisted turns."""
        aggregate = TokenConsumptionSummary(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            llm_calls=0,
            llm_calls_with_usage=0,
            llm_calls_missing_usage=0,
        )

        input_seen = False
        output_seen = False
        total_seen = False

        for turn_record in turn_records:
            for action in turn_record.actions:
                summary = action.meta_data.node_token_consumption
                if summary is None:
                    continue

                aggregate.llm_calls += summary.llm_calls
                aggregate.llm_calls_with_usage += summary.llm_calls_with_usage
                aggregate.llm_calls_missing_usage += summary.llm_calls_missing_usage

                if summary.input_tokens is not None:
                    aggregate.input_tokens = (aggregate.input_tokens or 0) + summary.input_tokens
                    input_seen = True
                if summary.output_tokens is not None:
                    aggregate.output_tokens = (aggregate.output_tokens or 0) + summary.output_tokens
                    output_seen = True
                if summary.total_tokens is not None:
                    aggregate.total_tokens = (aggregate.total_tokens or 0) + summary.total_tokens
                    total_seen = True

        if not input_seen:
            aggregate.input_tokens = None
        if not output_seen:
            aggregate.output_tokens = None
        if not total_seen:
            aggregate.total_tokens = None

        return aggregate

    def _build_conversation_summary(
        self,
        session_id: str,
        turn_records: List[ConversationTurn],
        token_summary: TokenConsumptionSummary,
        parse_iso_timestamp: "Callable[[Optional[str]], Optional[datetime]]",
    ) -> ConversationSummaryRecord:
        """Build a conversation summary from persisted turn records."""
        sorted_turns = sorted(turn_records, key=lambda turn: turn.turn)
        first_turn = sorted_turns[0] if sorted_turns else None
        last_turn = sorted_turns[-1] if sorted_turns else None

        started_at = first_turn.started_at if first_turn else None
        ended_at = last_turn.ended_at if last_turn else None

        started_at_dt = parse_iso_timestamp(started_at)
        ended_at_dt = parse_iso_timestamp(ended_at)

        total_wall_clock_seconds = None
        if started_at_dt is not None and ended_at_dt is not None:
            total_wall_clock_seconds = (ended_at_dt - started_at_dt).total_seconds()

        total_turn_processing_seconds = 0.0
        processing_seen = False
        for turn_record in sorted_turns:
            turn_started_at = parse_iso_timestamp(turn_record.started_at)
            turn_ended_at = parse_iso_timestamp(turn_record.ended_at)
            if turn_started_at is None or turn_ended_at is None:
                continue
            total_turn_processing_seconds += (
                turn_ended_at - turn_started_at
            ).total_seconds()
            processing_seen = True

        return ConversationSummaryRecord(
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            total_wall_clock_seconds=total_wall_clock_seconds,
            total_turn_processing_seconds=(
                total_turn_processing_seconds if processing_seen else None
            ),
            total_conversation_turns=len(sorted_turns),
            token_consumption=token_summary,
        )


class LocalFileSink(ObservabilitySink):
    """Append observability records to a local file."""

    def _append_record(self, record: BaseModel, filepath: Path) -> None:
        """Append one serialized observability record to the target log file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with filepath.open("a", encoding="utf-8") as file_handle:
            file_handle.write(record.model_dump_json(indent=2))
            file_handle.write("\n")

    def append_turn(self, turn_record: ConversationTurn, filepath: Path) -> None:
        """Persist one completed turn record as the next JSON object in the log."""
        self._append_record(turn_record, filepath)

    def _parse_json_records(self, filepath: Path) -> list[dict[str, Any]]:
        """Parse the log file's back-to-back JSON records."""
        if not filepath.exists():
            return []

        text = filepath.read_text(encoding="utf-8")
        decoder = json.JSONDecoder()
        idx = 0
        records: list[dict[str, Any]] = []

        while idx < len(text):
            while idx < len(text) and text[idx].isspace():
                idx += 1

            if idx >= len(text):
                break

            record, next_idx = decoder.raw_decode(text, idx)
            records.append(record)
            idx = next_idx

        return records

    def _parse_iso_timestamp(self, value: Optional[str]) -> Optional[datetime]:
        """Parse an ISO-8601 timestamp string into a datetime."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def finalize_session(
        self,
        *,
        session_id: str,
        filepath: Path,
        final_report: dict[str, Any],
    ) -> None:
        """Append terminal records (FinalReportRecord and ConversationSummaryRecord) after reconstructing totals from persisted turns. """
        
        #loads existing turn records from json log file
        turn_records: list[ConversationTurn] = []
        for record in self._parse_json_records(filepath):
            #NOTE: Maybe remove this, all records in the logs should contain turn at this stage of its life
            if "turn" not in record:
                continue
            #validate turn record prior to append, raises on malformed turn records 
            turn_records.append(ConversationTurn.model_validate(record))
        
        #derives conversation-wide timing and token usage
        token_summary = self._aggregate_action_token_summaries(turn_records)

        #build summary record
        summary_record = self._build_conversation_summary(
            session_id,
            turn_records,
            token_summary,
            self._parse_iso_timestamp,
        )

        #append final report record and summary record
        self._append_record(
            FinalReportRecord(session_id=session_id, final_report=final_report),
            filepath,
        )
        self._append_record(summary_record, filepath)


class TurnLogger:
    """Collect one active turn and turn-local observability state."""

    def __init__(
        self,
        filepath: str,
        session_id: str,
        sink: Optional[ObservabilitySink] = None,
    ):
        """Initialize a turn-scoped observability logger for one session.

        Args:
            filepath: Destination path where observability records should be
                persisted. The logger stores completed turn records and final
                session records at this location through the configured sink.
            session_id: Stable identifier attached to every record emitted by
                this logger. This lets downstream consumers group turns and
                summaries that belong to the same conversation session.
            sink: Persistence backend used to write observability records. When
                omitted, the logger uses ``LocalFileSink`` to append JSON records
                to ``filepath`` on the local filesystem.

        Attributes:
            filepath: Normalized ``Path`` pointing to the output destination for
                persisted observability records.
            session_id: String session identifier copied onto every emitted
                record.
            sink: Active persistence backend used to append turn records and
                finalize session records.
            num_turns: Count of completed conversation turns recorded so far.
            current_turn: In-progress turn record being populated, or ``None``
                when no turn is currently active.
            _current_action_name: Action currently being tracked for per-action
                usage accounting, or ``None`` when no action is active.
            _current_action_usage_events: Raw LLM usage events collected for the
                active action before they are summarized into action metadata.
        """
        self.filepath = Path(filepath)
        self.session_id = str(session_id)
        self.sink = sink or LocalFileSink()
        self.num_turns: int = 0
        self.current_turn: Optional[ConversationTurn] = None
        self._current_action_name: Optional[ActionName] = None
        self._current_action_usage_events: List[LLMUsageEvent] = []

    def start_action(self, action_name: ActionName) -> None:
        """Begin action-scoped LLM-usage capture for the next logged action."""
        self._current_action_name = action_name
        self._current_action_usage_events = []

    def record_llm_usage(self, usage_event: LLMUsageEvent) -> None:
        """
            Record one LLM usage event for the currently active action.
            Called by on_llm_end in ObservabilityTokenCallback following an LLM
            call to a model ObservabilityTokenCallback is attached to, to store
            LLM usage information for the most recent agent action.
        """
        if self._current_action_name is not None:
            self._current_action_usage_events.append(usage_event)

    def end_action(self) -> Optional[TokenConsumptionSummary]:
        """End action-scoped capture and return its aggregate token summary."""

        #If action was not llm_enabled (ie. validate, user_description, etc.), this if statement stops the creation of a usage summary record
        if not self._current_action_usage_events:
            #reset current agent action for next capture
            self._current_action_name = None
            return None

        #caluclate the usage summary for the most recent llm enabled agent action
        summary = TokenConsumptionSummary.from_events(self._current_action_usage_events)
        #reset current agent action for next capture
        self._current_action_name = None
        #empty current usage events for next capture
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
                started_at=datetime.now(timezone.utc).isoformat(),
                actions=[],
            )
        elif self.current_turn is None:
            #used to catch misalignment between burt runtime and what is expected from logs
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
