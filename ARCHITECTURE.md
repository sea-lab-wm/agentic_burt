# Architecture

## 1. System Design

```mermaid
flowchart LR
    U[User] --> A[Agent burt.py]
    A -->|fetch app graph by bug id| DB[(SQLite DB)]
    DB -->|return app graph| A

    subgraph OBS[Per-node Observability]
      L1[log_action decorator]
      L2[ConversationLogger]
      L3[(log files in logs directory)]
      L1 --> L2
      L2 --> L3
    end

    A -->|node outputs and latency| L1
```

### Deeper on Logging
- Per-node logging is handled by `@log_action` in `observability.py`, which wraps each node execution, measures latency, and records the node output.
- When a new `user_description` is logged, the logger advances to a new conversation turn.

## 2. Agent Control Flow

```mermaid
flowchart TD
    A[Start program] --> B[Load env + create DB session]
    B --> E[Init ConversationLogger, ChatOpenAI, StateGraph, MemorySaver]
    E --> F[Create initial bug agent state with first user bug description]
    F --> G[Generate mapping from user's intiial bug description]

    G --> H{Interrupt returned: Is there missing/ambiguous information in bug agent state?}
    H -->|yes| I[Display follow-up question]
    I --> J[Read user response from CLI]
    J --> K[Update mapping with user response to follow up]
    K --> H

    H -->|no| L[Generate final report from BugInfo]
    L --> M[Write conversation log to file]
    M --> N[End]
```

## 3. File Responsibilities

- `burt.py`: Main runtime entrypoint. Builds and runs the LangGraph workflow, orchestrates user interaction loop, and triggers final report generation plus log writing.
- `graph_utils.py`: Prompt and LLM orchestration utilities for extraction, follow-up generation, bug-info postprocessing, and final report synthesis.
- `state.py`: Pydantic models for agent state (`BugAgentState`), tracked bug information (`InfoSlots`/`Slot`), and confidence/status types.
- `llm_schema.py`: Structured-output schemas for LLM calls (extraction, follow-up question, report sections).
- `observability.py`: Logging domain models and decorator-based per-action instrumentation, including latency and turn-based conversation logging.
- `config.py`: Central constants such as model and DB uri.
- `requirements.txt`: Pinned Python dependencies for runtime and development.
- `database/db.py`: SQLAlchemy engine/session setup and SQLite foreign-key pragma configuration.
- `database/models.py`: SQLAlchemy ORM schema for `Bug`, `Screen`, and `Transition` tables.
- `database/database_utils.py`: DB query helper(s), currently `fetch_app_graph` by `bug_id`.
- `database/load_data.py`: One-off loader script to ingest graph text data into the `bug` table.
- `logs/*.log`: Generated conversation traces written by `ConversationLogger` for each bug/session run.

## 4. Core Dependencies

- SQLAlchemy (`2.0.46`): ORM and DB toolkit for SQLite schema/session/querying. Docs: <https://docs.sqlalchemy.org/>
- LangChain Core (`1.2.7`) + LangChain OpenAI (`1.1.7`): Prompting/message abstractions and OpenAI chat model integration. Docs: <https://python.langchain.com/docs/introduction/>
- LangGraph (`1.0.6`): Graph-based control flow, interrupts, commands, and checkpointed state for the agent lifecycle. Docs: <https://langchain-ai.github.io/langgraph/>
- Pydantic (`2.12.5`): Typed data models and validation for state, logging payloads, and structured model output schemas. Docs: <https://docs.pydantic.dev/latest/>
