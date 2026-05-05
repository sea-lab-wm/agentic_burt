# Agentic BURT

This repository contains the BURT++ bug-reporting agent, its observability logging system, and the evaluation pipeline used to score generated bug reports against the development-set ground truth.

The current workflow is:

1. Run the agent through the containerized session API or through the local CLI workflow.
2. Evaluate the resulting logs with the LLM-as-judge pipeline.
3. Manually validate the judge outputs using the generated review workbook.

## Current Defaults

The active defaults live in [config.py](config.py). Below you can see what each deafault effects:

1. `MODEL_NAME = ...`
    - What gpt model the agent uses
2. `PROMPT_VERSION = ...`
    - what set of prompts stored in prompt_versioning is active
    - where BURT writes logs: `logs/<PROMPT_VERSION>/`
    - where the evaluator writes results: `Results/<agent_version>/`
3. `DESCRIPTION_CSV_PATH = ...`
    - the path of dev set gt and bug descriptions
4. `CORS_ALLOWED_ORIGINS = ...`
    - comma-separated frontend origins allowed to call the backend API
    - defaults to `http://localhost:5173` for local Vite development

## Run The Containerized Deployment

Use Docker Compose to start the backend API and Redis together:

```bash
docker compose up --build
```

This starts:

- the FastAPI service on `http://localhost:8000`
- the Redis service used for session storage and LangGraph checkpointing
- the session API consumed by the frontend, including:
  - `GET /healthz`
  - `GET /bugs/active`
  - `POST /sessions`
  - `GET /sessions/{session_id}`
  - `POST /sessions/{session_id}/messages`

Before starting the containers, make sure these inputs exist:

- a root `.env` file with the OpenAI credentials required by `langchain-openai`
- optional: `CORS_ALLOWED_ORIGINS=...` in the root `.env` if you need to override the default local frontend origin allowlist
- the GUI graph context directory at [gui_graph_context](gui_graph_context)

### Frontend + Container Backend Startup Path

The current UI workflow is:

1. Start the containerized backend:

```bash
docker compose up --build
```

2. In a second terminal, install frontend dependencies if needed:

```bash
cd frontend
npm install
```

3. Start the Vite frontend:

```bash
npm run dev
```

4. Open the frontend at the local Vite URL, usually `http://localhost:5173`

Notes:

- The frontend talks to the containerized FastAPI backend on `http://localhost:8000`.
- The frontend reads `VITE_API_BASE_PATH` from [frontend/.env.local](frontend/.env.local), which should point to `http://localhost:8000` for local development.
- The backend now allows the local Vite origin through CORS by default, so the frontend calls the API directly instead of relying on a Vite proxy.
- If you only need the backend API and not the UI, you can skip the frontend steps above.

Useful API endpoints:

- `GET /bugs/active`
- `GET /healthz`
- `POST /sessions`
- `GET /sessions/{session_id}`
- `POST /sessions/{session_id}/messages`

Example session flow:

```bash
curl http://localhost:8000/healthz

curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"bug_id": 10, "user_description": "The app crashed after I tapped save."}'

curl http://localhost:8000/sessions/<session_id>

curl -X POST http://localhost:8000/sessions/<session_id>/messages \
  -H "Content-Type: application/json" \
  -d '{"user_description": "The app crashed after I tapped save."}'
```

Stop the deployment with:

```bash
docker compose down
```

## Setup For Local CLI Work

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in root with the OpenAI credentials required by `langchain-openai`. Both [burt.py](burt.py) and [evaluator/runner.py](evaluator/runner.py) load environment variables with `python-dotenv`.

Before running the agent, make sure these inputs exist:

- the description CSV at [data/dev_set_info_element_gt_and_input_desc.csv](data/dev_set_info_element_gt_and_input_desc.csv)
- the GUI graph context directory at [gui_graph_context](gui_graph_context)

## Run The Agent Locally

Use [burt.py](burt.py) for a single interactive run:

```bash
python burt.py --bug-id 10 --description-level LC_LP
```

Notes:

- `description-level` must use the format `LC_LP`, `MC_MP`, `HC_HP`, etc.
- BURT++ pulls the initial user description from the matching `<description level> Desc` column in the dev CSV.
- BURT++ loads the app graph and screen descriptions from `gui_graph_context/bug<id>/context.json`.
- If the agent needs clarification, it will interrupt in the terminal and ask follow-up questions.
- When the run completes, BURT++ prints the final bug report and writes an observability log through the default local file sink.

## Run The Full Experiment

Use [run_all_burt.py](run_all_burt.py) to run every non-empty description in the CSV:

```bash
python run_all_burt.py
```

To restrict the batch run to specific bug/description pairs:

```bash
python run_all_burt.py --limit-desc-to "[(10, 'LC_LP'), (135, 'MC_HP')]"
```

Behavior:

- the script discovers every CSV column ending in ` Desc`
- it runs [burt.py](burt.py) once per populated `(bug_id, description_level)` pair
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

Logged action names currently include:

- `user_description`
- `information_element_extraction`
- `clarity_check`
- `clarity_follow_up`
- `extract_and_update`
- `evaluate`
- `follow_up`
- `generate_report`

## Evaluate The Agent

Use [evaluator/runner.py](evaluator/runner.py) to evaluate one log, many logs, or a full log directory.

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
Results/<agent_version>/
```

For the current default setup, that is typically:

```text
Results/bugscribe_mutli-candidate_transitions_and_screen_descriptions/
```

Current generated artifacts:

- `*.evaluation.json`: one file per evaluated log
- `manual_review.xlsx`: combined manual review workbook for all evaluated runs in one agent version

Example:

```text
Results/bugscribe_mutli-candidate_transitions_and_screen_descriptions/bug10_LC_LP.evaluation.json
Results/bugscribe_mutli-candidate_transitions_and_screen_descriptions/manual_review.xlsx
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
- those older files are historical artifacts, not the current output format produced by [evaluator/generate_review.py](evaluator/generate_review.py)

## Recommended End-To-End Flow

Single run:

```bash
python burt.py --bug-id [bug_id] --description-level [desc_level]
python -m evaluator.runner logs/[agent_version_of_previous_run]/[session_id].log
```

Batch run:

```bash
python run_all_burt.py
```

After evaluation:

1. open `Results/<agent_version>/manual_review.xlsx`
2. review the `S2R Review` sheet
3. review the `Info Elements Review` sheet
4. use the `Summary` sheet for aggregated counts and averages

## Adding New Prompt Versions

Prompt-version definitions live in [prompt_versioning](prompt_versioning).

Key files:

- [prompt_versioning/prompt_versioning.json](prompt_versioning/prompt_versioning.json): the source of truth for prompt versions
- [prompt_versioning/prompt_versioning_json.py](prompt_versioning/prompt_versioning_json.py): helper utilities for loading, saving, and upserting prompt records

How prompt versions are structured:

- the JSON file contains a top-level list of prompt-version records
- each record has an `agent-version-title`
- each record also has a `prompts` mapping
- the `prompts` mapping holds one template string for each agent step, such as `information_element_extraction`, `clarity_check`, `clarity_follow_up`, `map_to_graph`, `more_info_follow_up`, and `generate_report`

How the agent uses them:

- [agent_utils.py](agent_utils.py) loads prompt templates from `prompt_versioning.json`
- the active prompt version is selected by `PROMPT_VERSION` in [config.py](config.py)
- that same `PROMPT_VERSION` is also used in log output paths and evaluator result grouping
- the runtime terminal node is still named `generate_report`; prompt-version updates for report synthesis should update the `generate_report` prompt key

To add a new prompt version:

1. add a new record in [prompt_versioning/prompt_versioning.json](prompt_versioning/prompt_versioning.json) with a new `agent-version-title`
2. include prompt text for every prompt key the runtime expects
3. update `PROMPT_VERSION` in [config.py](config.py) to the new `agent-version-title`
4. run a single-agent test run and confirm logs are written under `logs/<PROMPT_VERSION>/`

If you prefer not to edit the JSON file by hand, [prompt_versioning/prompt_versioning_json.py](prompt_versioning/prompt_versioning_json.py) includes `upsert_prompts(...)` for programmatically adding or updating prompt entries.

## GUI Context Data

The runtime now reads bug-specific application context from JSON files under [gui_graph_context](gui_graph_context).

Current runtime context shape:

- one directory per bug, such as `gui_graph_context/bug10/`
- one `context.json` file per bug
- each payload stores `application_name`, `transitions`, and `screen_names_and_descriptions`

The builder utilities for regenerating these files live under [gui_graph_context_management](gui_graph_context_management):

- [gui_graph_context_management/build_context.py](gui_graph_context_management/build_context.py)
- [gui_graph_context_management/generate_screen_descriptions.py](gui_graph_context_management/generate_screen_descriptions.py)
- [gui_graph_context_management/graph_data_parser.py](gui_graph_context_management/graph_data_parser.py)

## Testing

Automated tests currently live under [tests](tests).

The current test suite is written with Python's built-in `unittest` framework.

Current test modules include:

- [tests/test_evaluator.py](tests/test_evaluator.py)
- [tests/test_generate_review.py](tests/test_generate_review.py)
- [tests/test_agent_utils.py](tests/test_agent_utils.py)
- [tests/test_observability.py](tests/test_observability.py)
- [tests/test_run_all_burt.py](tests/test_run_all_burt.py)
- [tests/test_screen_descriptions.py](tests/test_screen_descriptions.py)
- [tests/test_state.py](tests/test_state.py)

Run the full test suite from repo root with `unittest`:

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
