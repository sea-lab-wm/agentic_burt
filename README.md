# Agentic BURT

This repository contains the BURT++ bug-reporting agent, its observability logging system, and the evaluation pipeline used to score generated bug reports against the development-set ground truth.

The current workflow is:

1. Run the agent for one bug/description pair or for a full or diminished development set.
2. Evaluate the resulting logs with the LLM-as-judge pipeline.
3. Manually validate the judge outputs using the generated review workbook.

## Current Defaults

The active defaults live in [config.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/config.py). Below you can see what each deafault effects:

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

Create a `.env` file in root with the OpenAI credentials required by `langchain-openai`. Both [burt.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/burt.py) and [evaluator/runner.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/runner.py) load environment variables with `python-dotenv`.

Before running the agent, make sure these inputs exist:

- the description CSV at [data/dev_set_info_element_gt_and_input_desc.csv](/Users/sambennett/Desktop/BURT++/Agentic_Burt/data/dev_set_info_element_gt_and_input_desc.csv)
- the SQLite app database at `database/apps.db`

## Run The Agent

Use [burt.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/burt.py) for a single interactive run:

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

Use [run_all_burt.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/run_all_burt.py) to run every non-empty description in the CSV:

```bash
python run_all_burt.py
```

To restrict the batch run to specific bug/description pairs:

```bash
python run_all_burt.py --limit-desc-to "[(10, 'LC_LP'), (135, 'MC_HP')]"
```

Behavior:

- the script discovers every CSV column ending in ` Desc`
- it runs [burt.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/burt.py) once per populated `(bug_id, description_level)` pair
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

Use [evaluator/runner.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/runner.py) to evaluate one log, many logs, or a full log directory.

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
- those older files are historical artifacts, not the current output format produced by [evaluator/generate_review.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/generate_review.py)

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

## Key Files

- [burt.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/burt.py): single-run BURT CLI
- [run_all_burt.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/run_all_burt.py): batch runner plus evaluator trigger
- [evaluator/runner.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/runner.py): evaluation entry point
- [evaluator/generate_review.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/generate_review.py): manual review workbook generation
- [evaluator/parsing.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/parsing.py): log discovery and parsing
- [data/dev_set_info_element_gt_and_input_desc.csv](/Users/sambennett/Desktop/BURT++/Agentic_Burt/data/dev_set_info_element_gt_and_input_desc.csv): input descriptions and ground truth
- [config.py](/Users/sambennett/Desktop/BURT++/Agentic_Burt/config.py): active model and prompt-version defaults
