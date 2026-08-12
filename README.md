# Agentic BURT

This repository contains the BURT++ bug-reporting agent, its observability logging system, and the evaluation pipeline used to score generated bug reports against the development-set ground truth.

The current workflow is:

1. Run the agent through the containerized session API or through the local CLI workflow.
2. Evaluate the resulting logs with the LLM-as-judge pipeline.
3. Manually validate the judge outputs using the generated review workbook.

## Current Defaults

The active backend defaults live in [backend/config.py](backend/config.py). Below you can see what each default affects:

1. `MODEL_NAME = ...`
   - What gpt model the agent uses
2. `PROMPT_VERSION = ...`
   - what set of prompts stored in prompt_versioning is active
   - where BURT writes logs: `logs/<PROMPT_VERSION>/`
   - where the evaluator writes results: `results/<agent_version>/`
3. `DATASET = ...`
   - which dataset BURT uses for CSV input/ground truth and JSON graph context
   - CSV path convention: `gt_and_test_data/<DATASET>.csv`
   - graph context path convention: `json_graph_data/<DATASET>/`

## Run The Containerized Deployment

Before starting the containers, make sure these inputs exist:

- a root `.env` file with the OpenAI credentials required by `langchain-openai`
- a GUI graph context dataset directory at `backend/json_graph_data/[dataset]`

### Add `.env` file to root:

1. Create a `.env` file in root with the OpenAI credentials required by `langchain-openai`.
   * Add your OpenAI API key: `OPENAI_API_KEY=<your-key>`

### Install Docker (if not installed already):

1. Download from: https://www.docker.com/products/docker-desktop
2. Install and open it
3. Keep the Docker Desktop app running
4. Verify the installation: ``docker --version``

### Frontend + Container Backend Startup Path

The current UI workflow is:

1. Start the containerized stack:

```bash
docker compose up --build
```

This starts:

- the frontend nginx service on `http://localhost:3000`
- the FastAPI service inside the Compose network as `http://api:3000`
- the Redis service used for session storage and LangGraph checkpointing
- the session API consumed by the frontend, including:
  - `GET /healthz`
  - `GET /bugs/active`
  - `POST /sessions`
  - `GET /sessions/{session_id}`
  - `POST /sessions/{session_id}/messages`
  - `POST /sessions/{session_id}/report`
  - `GET /sessions/{session_id}/reports`
  - `GET /sessions/{session_id}/report-media`
  - `GET /sessions/{session_id}/screenshots/{kind}/{image_id}`

2. Open the frontend at:
   * Local machine: `http://localhost:3000`
   * SEA-Lab server: `http://rocco.cs.wm.edu:21202`

Notes:

- The backend API is not exposed directly on the host.
- Browser API calls go through nginx at `/api/...`, which proxies to the internal `api:3000` service.

### Editing And Regenerating A Report

Saving an edited report does not only store the edit. `POST /sessions/{session_id}/report`
writes it to the session log as the round's **final report**, then reruns BURT++ from the
start on that edited report, exactly as if the text had been typed into the composer.

The rerun is **single-pass**: the user has already said what they wanted changed, so it
regenerates in one try instead of asking follow-up questions. Both follow-up branches of
the graph are skipped for it (`BugAgentState.single_pass`), and the report is written from
whatever the edit supplied — unresolved slots reach the prompt carrying their `unknown` or
`ambiguous` status rather than blocking generation. The response therefore always carries
the newly generated **draft report**.

One session therefore accumulates alternating reports in its log:

```
draft report 1   <- the first BURT++ run
final report 1   <- the user's edit, which triggers a rerun
draft report 2   <- the regenerated report
...
```

`config.MAX_REPORT_EDITS` (default 3) caps how many times this can happen, so a session
tops out at final report 3 and draft report 4. `GET /sessions/{session_id}/reports` replays
every report on file, which is what lets a reloaded page rebuild the whole history rather
than only the report the last request happened to return.

Stop the deployment with:

```bash
docker compose down
```

## Setup For Local CLI Work

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
cd backend
pip install -r requirements.txt
```

Create a `.env` file in root with the OpenAI credentials required by `langchain-openai`. Both [backend/burt_core/burt.py](backend/burt_core/burt.py) and [backend/evaluator/runner.py](backend/evaluator/runner.py) load environment variables with `python-dotenv`.

Before running the agent, make sure these inputs exist:

- the description/ground-truth CSV at `backend/gt_and_test_data/[DATASET].csv`
- the GUI graph context dataset directory at `backend/json_graph_data/[DATASET]`

## Run The Agent Locally

From `backend/`, use [backend/burt_core/cli.py](backend/burt_core/cli.py) for a single interactive run. For example:

```bash
python -m burt_core.cli --bug-id 10 --description-level LC_LP
```

Notes:

- `description-level` must use the format `LC_LP`, `MC_MP`, `HC_HP`, etc.
- BURT++ pulls the initial user description from the matching `<description level> Desc` column in `gt_and_test_data/<DATASET>.csv`.
- BURT++ loads the app graph and screen descriptions from `json_graph_data/<DATASET>/bug<id>/context.json`.
- If the agent needs clarification, it will interrupt in the terminal and ask follow-up questions.
- When the run completes, BURT++ prints the final bug report and writes an observability log through the default local file sink.

## Run The Full Experiment

From `backend/`, use [backend/run_all_burt.py](backend/run_all_burt.py) to run every non-empty description in the gt and test data CSV for your dataset:

```bash
python run_all_burt.py
```

To restrict the batch run to specific bug/description pairs:

```bash
python run_all_burt.py --limit-desc-to "[(10, 'LC_LP'), (135, 'MC_HP')]"
```

Behavior:

- the script discovers every CSV column ending in ` Desc`
- it runs [backend/burt_core/cli.py](backend/burt_core/cli.py) once per populated `(bug_id, description_level)` pair
- after the runs finish, it automatically evaluates the logs in `logs/<PROMPT_VERSION>/`

## Agent Logging

BURT++ writes one observability log per run. These logs are the input to the evaluator.

Log location:

```text
logs/<PROMPT_VERSION>/<session_id>.log
```

Current logging behavior:

- `TurnLogger` builds turn records in memory and hands persistence off to an `ObservabilitySink`.
- The default sink is `LocalFileSink`, which appends back-to-back JSON records to the local log file.
- At the end of the run, the sink reconstructs conversation totals from the persisted turn records and appends terminal records.

What each log includes:

- one JSON record per conversation turn
- within each turn, an `actions` list covering the user description and each logged agent step
- for each action: the acting entity, action name, output payload, latency, and any available token-usage summary
- a terminal `final_report` JSON record appended by the sink as a compatibility snapshot of the generated report. NOTE: this will eventually represent the final report agreed upon by the user and BURT++.
- a final `conversation_summary` JSON record with run metadata, total latency, total turns, and aggregate token consumption

## Evaluate The Agent

From `backend/`, use [backend/evaluator/runner.py](backend/evaluator/runner.py) to evaluate one log, many logs, or a full log directory.

Evaluate the current prompt-version directory:

```bash
python -m evaluator.runner logs/bugscribe_mutli-candidate_transitions_and_screen_descriptions
```

Evaluate specific log files:

```bash
python -m evaluator.runner \
  logs/bugscribe_mutli-candidate_transitions_and_screen_descriptions/<session_id>.log \
  logs/bugscribe_mutli-candidate_transitions_and_screen_descriptions/<another_session_id>.log
```

Override the judge model:

```bash
python -m evaluator.runner logs/bugscribe_mutli-candidate_transitions_and_screen_descriptions --model gpt-5.4
```

For each log, the evaluator:

1. parses the observability records
2. extracts `bug_id` and `description_level` from embedded `conversation_summary.run_metadata`, with filename parsing as a legacy fallback; result grouping still uses the log directory as `agent_version`
3. finds the terminal `final_report` record or falls back to the `generate_report` action for legacy log files
4. reads the final generated bug report
5. joins the matching ground-truth row from the dev CSV
6. recomputes information elements from the generated report
7. runs LLM judging for information elements
8. runs LLM judging for steps to reproduce
9. writes one `*.evaluation.json` artifact
10. rebuilds the manual review workbook for that agent version

## Evaluation Outputs

The evaluator writes outputs under:

```text
results/<agent_version>/
```

For the current default setup, that is typically:

```text
results/bugscribe_mutli-candidate_transitions_and_screen_descriptions/
```

Current generated artifacts:

- `*.evaluation.json`: one file per evaluated log
- `manual_review.xlsx`: combined manual review workbook for all evaluated runs in one agent version

Example:

```text
results/bugscribe_mutli-candidate_transitions_and_screen_descriptions/bug10_LC_LP.evaluation.json
results/bugscribe_mutli-candidate_transitions_and_screen_descriptions/manual_review.xlsx
```

## Manual Validation Of LLM-As-Judge Results

The manual review workbook currently contains three sheets:

- `S2R Review`
- `Info Elements Review`
- `Summary`

What each sheet is for:

- `S2R Review`: manual validation of LLM labels for generated steps-to-reproduce
- `Info Elements Review`: manual validation of LLM information-element grading
- `Summary`: aggregated metrics across the workbook

Important implementation detail:

- the current evaluator generates a single combined `manual_review.xlsx`
- older result folders in this repo may still contain legacy files such as `s2r_manual_review.xlsx`, `information_elements_manual_review.xlsx`, or `summary.csv`
- those older files are historical artifacts, not the current output format produced by [backend/evaluator/generate_review.py](backend/evaluator/generate_review.py)

## Adding New Prompt Versions

Prompt-version definitions live in [backend/prompt_versioning](backend/prompt_versioning).

Key files:

- [backend/prompt_versioning/prompt_versioning.json](backend/prompt_versioning/prompt_versioning.json): the source of truth for prompt versions
- [backend/prompt_versioning/prompt_versioning_json.py](backend/prompt_versioning/prompt_versioning_json.py): helper utilities for loading, saving, and upserting prompt records

How prompt versions are structured:

- the JSON file contains a top-level list of prompt-version records
- each record has an `agent-version-title`
- each record also has a `prompts` mapping
- the `prompts` mapping holds one template string for each agent step, such as `information_element_extraction`, `clarity_check`, `clarity_follow_up`, `map_to_graph`, `more_info_follow_up`, and `generate_report`

How the agent uses them:

- [backend/burt_core/agent_utils.py](backend/burt_core/agent_utils.py) loads prompt templates from `prompt_versioning.json`
- the active prompt version is selected by `PROMPT_VERSION` in [backend/config.py](backend/config.py)
- that same `PROMPT_VERSION` is also used in log output paths and evaluator result grouping
- the runtime terminal node is still named `generate_report`; prompt-version updates for report synthesis should update the `generate_report` prompt key

To add a new prompt version:

1. add a new record in [backend/prompt_versioning/prompt_versioning.json](backend/prompt_versioning/prompt_versioning.json) with a new `agent-version-title`
2. include prompt text for every prompt key the runtime expects
3. update `PROMPT_VERSION` in [backend/config.py](backend/config.py) to the new `agent-version-title`
4. run a single-agent test run and confirm logs are written under `logs/<PROMPT_VERSION>/`

If you prefer not to edit the JSON file by hand, [backend/prompt_versioning/prompt_versioning_json.py](backend/prompt_versioning/prompt_versioning_json.py) includes `upsert_prompts(...)` for programmatically adding or updating prompt entries.

## GUI Context

The runtime reads bug-specific application context from JSON files under `json_graph_data/<DATASET>` inside `backend/`, where `DATASET` is configured in [backend/config.py](backend/config.py).

Current runtime context shape:

- one directory per bug, such as `json_graph_data/AstroBR/bug10/`
- one `context.json` file per bug
- each payload stores `application_name`, `transitions`, and `screen_names_and_descriptions`

The builder utilities for regenerating these files live under [backend/gui_graph_context_management](backend/gui_graph_context_management):

- [backend/gui_graph_context_management/build_context.py](backend/gui_graph_context_management/build_context.py)
- [backend/gui_graph_context_management/generate_screen_descriptions.py](backend/gui_graph_context_management/generate_screen_descriptions.py)
- [backend/gui_graph_context_management/graph_data_parser.py](backend/gui_graph_context_management/graph_data_parser.py)

## Testing

Automated tests currently live under [backend/tests](backend/tests).

The current test suite is written with Python's built-in `unittest` framework.

Current test modules include:

- [backend/tests/test_evaluator.py](backend/tests/test_evaluator.py)
- [backend/tests/test_generate_review.py](backend/tests/test_generate_review.py)
- [backend/tests/test_agent_utils.py](backend/tests/test_agent_utils.py)
- [backend/tests/test_observability.py](backend/tests/test_observability.py)
- [backend/tests/test_run_all_burt.py](backend/tests/test_run_all_burt.py)
- [backend/tests/test_screen_descriptions.py](backend/tests/test_screen_descriptions.py)
- [backend/tests/test_state.py](backend/tests/test_state.py)

Run the full test suite from `backend/` with `unittest`:

```bash
python -m unittest discover -s tests
```

Run one test module:

```bash
python -m unittest tests.test_evaluator
```

Run one specific test method:

```bash
python -m unittest tests.test_evaluator.EvaluatorTests.test_build_log_context_extracts_summary_metrics
```

You can also run a single test file directly because the test modules call `unittest.main()`:

```bash
python tests/test_evaluator.py
```

If you prefer `pytest` as a nicer runner, it should also work for the current suite:

```bash
pytest tests
```

## Key Files, Agent Flow, Tech Stack

Please refer to [ARCHITECTURE.md](ARCHITECTURE.md).
