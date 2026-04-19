"""Observability runtime helpers for logging and token tracking."""

from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Optional
import time

from langchain_core.callbacks import BaseCallbackHandler
from pydantic import StrictStr

from observability.observability_models import (
    Action,
    ActionName,
    ConversationTurn,
    Entity,
    LLMUsageEvent,
    MetaData,
    TokenConsumptionSummary,
)
from observability.observability_sinks import LocalFileSink, ObservabilitySink


class TurnLogger:
    """Collect one active turn and turn-local observability state."""

    def __init__(
        self,
        filepath: str,
        session_id: str,
        sink: Optional[ObservabilitySink] = None,
    ):
        """Initialize a turn-scoped observability logger for one session."""
        self.filepath = Path(filepath)
        self.session_id = str(session_id)
        self.sink = sink or LocalFileSink()
        self.num_turns: int = 0
        self.current_turn: Optional[ConversationTurn] = None
        self._current_action_name: Optional[ActionName] = None
        self._current_action_usage_events: list[LLMUsageEvent] = []

    def start_action(self, action_name: ActionName) -> None:
        """Begin action-scoped LLM-usage capture for the next logged action."""
        self._current_action_name = action_name
        self._current_action_usage_events = []

    def record_llm_usage(self, usage_event: LLMUsageEvent) -> None:
        """Record one LLM usage event for the currently active action."""
        if self._current_action_name is not None:
            self._current_action_usage_events.append(usage_event)

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
                started_at=datetime.now(timezone.utc).isoformat(),
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


def _get_runtime_context(*args: Any, **kwargs: Any) -> Any:
    """Resolve the request-local runtime context from function args or kwargs."""
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
