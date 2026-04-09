# Agentic BURT

This repository contains the BURT++ bug-reporting agent, its observability logging system, and the evaluation pipeline used to score generated bug reports against the development-set ground truth.

The current workflow is:

1. Run the agent for one bug/description pair or for a full or diminished development set.
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
4. `DATABASE_URL = ...`
    - the database access url

## Setup

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in root with the OpenAI credentials required by `langchain-openai`. Both [burt.py](burt.py) and [evaluator/runner.py](evaluator/runner.py) load environment variables with `python-dotenv`.

Before running the agent, make sure these inputs exist:

- the description CSV at [data/dev_set_info_element_gt_and_input_desc.csv](data/dev_set_info_element_gt_and_input_desc.csv)
- the SQLite app database at `database/apps.db`

## Run The Agent

Use [burt.py](burt.py) for a single interactive run:

```bash
python burt.py --bug-id 10 --description-level LC_LP
```

Notes:

- `description-level` must use the format `LC_LP`, `MC_MP`, `HC_HP`, etc.
- BURT++ pulls the initial user description from the matching `<description level> Desc` column in the dev CSV.
- BURT++ loads the app graph and screen descriptions from the database for the requested `bug_id`.
- If the agent needs clarification, it will interrupt in the terminal and ask follow-up questions.
- When the run completes, BURT++ prints the final bug report and writes an observability log.

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
logs/<PROMPT_VERSION>/bug<bug_id>_<description_level>.log
```

What each log includes:

- one JSON record per conversation turn
- within each turn, an `actions` list covering the user description and each logged agent step
- for each action: the acting entity, action name, output payload, latency, and any available token-usage summary
- the final `generate_report` action output, including the generated bug report used by the evaluator
- a final `conversation_summary` JSON record with run-level totals such as total latency, total turns, and aggregate token consumption

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
  logs/bugscribe_mutli-candidate_transitions_and_screen_descriptions/bug10_LC_LP.log \
  logs/bugscribe_mutli-candidate_transitions_and_screen_descriptions/bug135_MC_HP.log
```

Override the judge model:

```bash
python -m evaluator.runner logs/bugscribe_mutli-candidate_transitions_and_screen_descriptions --model gpt-5.4
```

For each log, the evaluator:

1. parses the observability records
2. extracts `bug_id`, `description_level`, and `agent_version` from the log path
3. finds the `generate_report` action
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
python -m evaluator.runner logs/[agent_version_of_previous_run]/bug[bug_id]_[desc_level].log
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

- [graph_utils.py](graph_utils.py) loads prompt templates from `prompt_versioning.json`
- the active prompt version is selected by `PROMPT_VERSION` in [config.py](config.py)
- that same `PROMPT_VERSION` is also used in log output paths and evaluator result grouping

To add a new prompt version:

1. add a new record in [prompt_versioning/prompt_versioning.json](prompt_versioning/prompt_versioning.json) with a new `agent-version-title`
2. include prompt text for every prompt key the runtime expects
3. update `PROMPT_VERSION` in [config.py](config.py) to the new `agent-version-title`
4. run a single-agent test run and confirm logs are written under `logs/<PROMPT_VERSION>/`

If you prefer not to edit the JSON file by hand, [prompt_versioning/prompt_versioning_json.py](prompt_versioning/prompt_versioning_json.py) includes `upsert_prompts(...)` for programmatically adding or updating prompt entries.

## Database Management

The runtime data layer uses SQLite with SQLAlchemy models in [database/models.py](database/models.py) and Alembic migrations in [alembic/versions](alembic/versions).

Current runtime database:

```text
database/apps.db
```

Runtime code reads that path from [config.py](config.py) via `DATABASE_URL`.

Current schema shape:

- the main runtime table is `bug`
- each row stores `bug_id`, `application_name`, `gui_graph`, and `screen_descriptions`
- older individual `screen` and `transition` tables exist in earlier migrations but are not part of the current model

Apply migrations to bring a database up to date:

```bash
alembic upgrade head
```

Check the current migration version:

```bash
alembic current
```

See migration history:

```bash
alembic history
```

Create a new migration after changing [database/models.py](database/models.py):

```bash
alembic revision --autogenerate -m "describe schema change"
```

Then review the generated migration in [alembic/versions](alembic/versions) before applying it:

```bash
alembic upgrade head
```

Load graph data into the database:

- [database/load_data.py](database/load_data.py) is the current manual loader for inserting selected bugs
- it locates raw `graph.txt` files, filters the graph text, generates `screen_descriptions`, and inserts rows into `bug`
- it currently depends on a local absolute graph-data directory and should be treated as a developer utility, not a portable setup script

Important current caveat:

- [alembic.ini](alembic.ini) currently sets `sqlalchemy.url = sqlite:///database/app.db`
- [config.py](config.py) currently sets `DATABASE_URL = "sqlite:///database/apps.db"`
- before running Alembic, make sure those point to the same SQLite file or Alembic may migrate a different database than the runtime uses

## Testing

Automated tests currently live under [tests](tests).

The current test suite is written with Python's built-in `unittest` framework.

Current test modules include:

- [tests/test_evaluator.py](tests/test_evaluator.py)
- [tests/test_generate_review.py](tests/test_generate_review.py)
- [tests/test_graph_utils.py](tests/test_graph_utils.py)
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
