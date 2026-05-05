# Architecture

This document is currently scoped to the local quick-development runtime. It does not yet describe the containerized deployment path.

## 1. System Design

```mermaid
flowchart LR
    U[User] --> A[Agent runtime in burt.py]
    A -->|load initial description| CSV[(dev CSV)]
    A -->|fetch graph + app metadata by bug_id| GC[json_graph_data/<DATASET>/bug<id>/context.json]
    GC -->|transitions + app_name + screen_descriptions| A
    A -->|load active prompt templates| PV[(prompt_versioning.json)]
    L2 -->|write observability log| LOGS[(logs/<PROMPT_VERSION>/...)]

    subgraph OBS[Observability]
      L1[log_action decorator]
      L2[TurnLogger]
      L3[ObservabilityTokenCallback]
      L4[ObservabilitySink / LocalFileSink]
      L1 --> L2
      L3 --> L2
      L2 --> L4
    end

    A -->|node outputs + latency| L1
    A -->|LLM token usage| L3
    A -->|flush completed turns + finalize session| L4

    LOGS --> E[Evaluator]
    E --> R[(Results/<agent_version>/...)]
```

### Deeper on Logging
- Per-action logging is handled by `@log_action` in `observability/logging_runtime.py`, which wraps instrumented runtime functions, measures latency, and records their outputs.
- `ObservabilityTokenCallback` attaches to the active `ChatOpenAI` model and captures provider token usage for both action-level and conversation-level summaries.
- `TurnLogger` owns the in-memory turn lifecycle, while `ObservabilitySink` owns persistence.
- The current local backend is `LocalFileSink`, which appends back-to-back JSON records to `logs/<PROMPT_VERSION>/...`.
- CLI runs flush each completed turn to disk, then call `sink.finalize_session(...)` after the graph finishes.
- Finalization reloads the persisted turn records, aggregates token/timing totals, and appends `final_report` plus `conversation_summary` terminal records.
- Each turn contains an `actions` list with entries such as `user_description`, `information_element_extraction`, `clarity_check`, `extract_and_update`, `follow_up`, and `generate_report`.
- Log paths are versioned by `config.PROMPT_VERSION`, so runtime logs and evaluation outputs can be grouped by active prompt version.

## 2. Agent Control Flow

```mermaid
flowchart TD
    A[Start program] --> B[Load env + parse bug_id and description_level]
    B --> C[Load initial description from dev CSV]
    C --> D[Fetch gui_graph, app_name, and screen_descriptions from json_graph_data/<DATASET>]
    D --> E[Initialize logger, ChatOpenAI callback, and LangGraph workflow]
    E --> F[Log initial user description into BugAgentState]
    F --> G[information_element_extraction]
    G --> H[clarity_check]
    H --> I{needs_clarification?}
    I -->|yes| J[clarity_follow_up]
    J --> K[interrupt_and_present]
    K --> L[Resume with user reply]
    L --> G
    I -->|no or clarification limit reached| M[map_to_graph]
    M --> N[evaluate_state]
    N --> O{unknown or ambiguous bug info remains?}
    O -->|yes| P[more_info_follow_up]
    P --> K
    O -->|no| Q[generate_report]
    Q --> R[finish conversation + write log]
    R --> S[End]
```

- The runtime is a LangGraph state machine compiled in `burt.py` with `MemorySaver` checkpointing so the graph can pause at interrupts and resume after the user answers.
- The first user message is not typed interactively; it is loaded from the description CSV column matching the requested `description_level`.
- `information_element_extraction` operates in one of three modes: initial description, clarity follow-up, or more-info follow-up.
- `clarity_check` can request one clarification round before the graph continues to mapping.
- `map_to_graph` grounds extracted natural-language information elements into the structured `BugInfo` mapping using the application graph and screen descriptions.
- `evaluate_state` checks for unresolved slots. If any remain, `more_info_follow_up` generates the next user-facing question and the graph interrupts.
- `generate_report` is the terminal LangGraph node and returns the final `full_report` payload.
- The `generate_report` action entry is the canonical report-generation action record, including per-node token accounting.
- The sink still appends a compatibility `final_report` record at session finalization so downstream consumers can read a stable terminal snapshot.

## 3. File Responsibilities

- `burt.py`: Main local runtime entrypoint. Loads inputs, fetches GUI graph context from local JSON files, builds the LangGraph workflow, manages CLI interrupts, flushes turn records through the sink, and finalizes the observability log.
- `agent_utils.py`: Prompt-loading and LLM orchestration utilities for extraction, clarity checks, graph mapping, follow-up generation, bug-info formatting, and final report synthesis.
- `prompt_versioning/prompt_versioning.json`: Source of truth for prompt-version records. Each record contains an `agent-version-title` plus a `prompts` mapping used by the runtime.
- `prompt_versioning/prompt_versioning_json.py`: Helper utilities for reading and programmatically updating prompt-version records.
- `state.py`: Pydantic models for `BugAgentState`, follow-up tracking, extracted information elements, and the structured `BugInfo` slot mapping.
- `llm_schema.py`: Structured-output schemas used by runtime LLM calls for extraction, follow-up generation, clarity decisions, mapping updates, and report generation.
- `observability/observability_models.py`: Shared observability enums and record models used by both runtime logging and sinks.
- `observability/logging_runtime.py`: Turn lifecycle management, action instrumentation, and token-usage callback capture.
- `observability/observability_sinks.py`: Sink abstractions plus local file persistence and conversation-summary finalization.
- `config.py`: Runtime configuration constants such as `MODEL_NAME`, `PROMPT_VERSION`, `DATASET`, `DESCRIPTION_CSV_PATH`, and `REDIS_URL`.
- `gui_graph_context_management/loader.py`: Runtime loader for reading `json_graph_data/<DATASET>/bug<id>/context.json` and reconstructing the text blocks consumed by the runtime.
- `gui_graph_context_management/build_context.py`: Utility for generating the `context.json` payloads from raw graph data.
- `gui_graph_context_management/generate_screen_descriptions.py`: LLM-assisted generator for screen description text used in each context payload.
- `gui_graph_context_management/graph_data_parser.py`: Graph parsing helpers for locating raw graph files, simplifying IDs, filtering graph text, and preparing transition/screen descriptions.
- `run_all_burt.py`: Batch runner that discovers runnable `(bug_id, description_level)` pairs from the CSV, executes `burt.py` for each one, and then runs the evaluator on the resulting log directory.
- `evaluator/runner.py`: Evaluation entrypoint. Reads logs, derives evaluation context, runs the judge passes, writes `*.evaluation.json`, and rebuilds the manual-review workbook.
- `evaluator/parsing.py`: Parsing helpers for discovering log files, extracting metadata from log paths, decoding JSON records, and joining ground-truth CSV rows.
- `evaluator/judges.py`: Evaluator-local LLM helpers for extracting information elements from the final generated report and grading info elements and steps to reproduce.
- `evaluator/generate_review.py`: Workbook builder for `manual_review.xlsx`, including the `S2R Review`, `Info Elements Review`, and `Summary` sheets.
- `logs/<PROMPT_VERSION>/`: Runtime observability logs grouped by active prompt version.
- `Results/<agent_version>/`: Evaluator outputs grouped by log directory / prompt version, including `*.evaluation.json` and `manual_review.xlsx`.
- `tests/`: Automated test suite, currently written with `unittest`, covering evaluator behavior, review generation, observability, state handling, batch running, and related utilities.

## 4. Core Dependencies

- LangChain Core (`1.2.7`) + LangChain OpenAI (`1.1.7`): Prompt/message abstractions, structured output helpers, and OpenAI chat-model integration. Docs: <https://python.langchain.com/docs/introduction/>
- LangGraph (`1.0.6`): Graph-based runtime orchestration, interrupts, resume commands, and checkpointed state for the agent control flow. Docs: <https://langchain-ai.github.io/langgraph/>
- Pydantic (`2.12.5`): Typed data models and validation for agent state, structured outputs, evaluator schemas, and observability payloads. Docs: <https://docs.pydantic.dev/latest/>
- OpenPyXL (`3.1.5`): Workbook generation for the manual-review artifacts produced by the evaluator. Docs: <https://openpyxl.readthedocs.io/>
