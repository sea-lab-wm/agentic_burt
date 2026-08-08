"""Observability sink abstractions and persistence backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel
import redis

from observability.observability_models import (
    ConversationSummaryRecord,
    ConversationTurn,
    DraftReportRecord,
    ModifiedReportRecord,
    RunMetadata,
    TokenConsumptionSummary,
)


def parse_log_records(filepath: Path) -> list[dict[str, Any]]:
    """Parse a session log file's back-to-back JSON records into dicts, in written order."""
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


class ObservabilitySink(ABC):
    """Persistence backend for observability records."""

    def __init__(self, filepath: Path):
        self.filepath = filepath

    @abstractmethod
    def append_turn(self, turn_record: ConversationTurn) -> None:
        """Persist one completed turn record."""

    @abstractmethod
    def finalize_session(
        self,
        *,
        session_id: str,
        final_report: dict[str, Any],
        run_metadata: RunMetadata | dict[str, Any] | None = None,
    ) -> None:
        """Append final report and reconstructed conversation summary records."""

    def _append_record(self, record: BaseModel, filepath: Path) -> None:
        """
            Append one serialized observability record to the target log file.
            Facilitates all sinks to write log contents sequentially to the log file, preserving log strucutre across dev environments.
        """
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with filepath.open("a", encoding="utf-8") as file_handle:
            file_handle.write(record.model_dump_json(indent=2))
            file_handle.write("\n")

    def _parse_iso_timestamp(self, value: Optional[str]) -> Optional[datetime]:
        """Parse an ISO-8601 timestamp string into a datetime."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _aggregate_action_token_summaries(
        self,
        turn_records: list[ConversationTurn],
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
        turn_records: list[ConversationTurn],
        token_summary: TokenConsumptionSummary,
        parse_iso_timestamp: Callable[[Optional[str]], Optional[datetime]],
        run_metadata: RunMetadata | dict[str, Any] | None = None,
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
            run_metadata=(
                RunMetadata.model_validate(run_metadata)
                if run_metadata is not None
                else None
            ),
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

    def append_turn(self, turn_record: ConversationTurn) -> None:
        """Persist one completed turn record as the next JSON object in the log."""
        self._append_record(turn_record, self.filepath)

    def append_modified_report(
        self,
        *,
        session_id: str,
        modified_report: dict[str, Any],
    ) -> None:
        """Append a user-edited final report record to an existing session log."""
        self._append_record(
            ModifiedReportRecord(
                session_id=session_id,
                modified_report=modified_report,
            ),
            self.filepath,
        )

    def finalize_session(
        self,
        *,
        session_id: str,
        final_report: dict[str, Any],
        run_metadata: RunMetadata | dict[str, Any] | None = None,
    ) -> None:
        """Append terminal records after reconstructing totals from persisted turns."""
        turn_records: list[ConversationTurn] = []
        for record in parse_log_records(self.filepath):
            if "turn" not in record:
                continue
            turn_records.append(ConversationTurn.model_validate(record))

        token_summary = self._aggregate_action_token_summaries(turn_records)
        summary_record = self._build_conversation_summary(
            session_id,
            turn_records,
            token_summary,
            self._parse_iso_timestamp,
            run_metadata,
        )

        self._append_record(
            DraftReportRecord(session_id=session_id, draft_report=final_report),
            self.filepath,
        )
        self._append_record(summary_record, self.filepath)


class RedisThenFileSink(ObservabilitySink):
    """Stage completed turns in Redis, then emit the final file log on completion."""

    def __init__(self, redis_client: redis.Redis, filepath: Path):
        super().__init__(filepath=filepath)
        self.redis_client = redis_client

    def _redis_list_key(self, session_id: str) -> str:
        """Build the Redis list key used to stage observability turns."""
        return f"burt:session-log:{session_id}"

    def _parse_redis_records(self, session_id: str) -> list[dict[str, Any]]:
        """Parse staged Redis JSON payloads for one session."""
        key = self._redis_list_key(session_id)
        return [json.loads(record) for record in self.redis_client.lrange(key, 0, -1)]

    def append_turn(self, turn_record: ConversationTurn) -> None:
        """Stage one completed turn record in Redis under its session list."""
        self.redis_client.rpush(
            self._redis_list_key(turn_record.session_id),
            turn_record.model_dump_json(),
        )

    def finalize_session(
        self,
        *,
        session_id: str,
        final_report: dict[str, Any],
        run_metadata: RunMetadata | dict[str, Any] | None = None,
    ) -> None:
        """Write the reconstructed session log to disk, then clear staged Redis turns."""
        turn_records = [
            ConversationTurn.model_validate(record)
            for record in self._parse_redis_records(session_id)
            if "turn" in record
        ]

        token_summary = self._aggregate_action_token_summaries(turn_records)
        summary_record = self._build_conversation_summary(
            session_id,
            turn_records,
            token_summary,
            self._parse_iso_timestamp,
            run_metadata,
        )

        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with self.filepath.open("w", encoding="utf-8") as file_handle:
            for turn_record in turn_records:
                file_handle.write(turn_record.model_dump_json(indent=2))
                file_handle.write("\n")
            file_handle.write(
                DraftReportRecord(
                    session_id=session_id,
                    draft_report=final_report,
                ).model_dump_json(indent=2)
            )
            file_handle.write("\n")
            file_handle.write(summary_record.model_dump_json(indent=2))
            file_handle.write("\n")

        self.redis_client.delete(self._redis_list_key(session_id))
