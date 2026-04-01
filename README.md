# Agentic BURT

This repository contains the BUR++ bug-reporting agent, the observability logs it produces, and the evaluator pipeline that scores generated bug reports against the development-set ground truth.

## Repository Flow

The project has two main stages:

1. Run BURT on a `(bug_id, description_level)` input pair.
2. Evaluate the resulting log files and generate review artifacts.

At a high level:

- Input descriptions come from [`data/dev_set_info_element_gt_and_input_desc.csv`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/data/dev_set_info_element_gt_and_input_desc.csv).
- App graphs are loaded from the SQLite-backed database used by [`burt.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/burt.py).
- BURT++ writes observability logs under `logs/<prompt_version>/`.
- The evaluator reads those logs and writes outputs under `Results/<agent_version>/`.

## Prerequisites

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with the OpenAI credentials required by `langchain-openai`. The runtime loads environment variables with `python-dotenv` in both [`burt.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/burt.py) and [`evaluator/runner.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/runner.py).

The current default configuration lives in [`config.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/config.py).

## Data Inputs

### Description CSV

[`data/dev_set_info_element_gt_and_input_desc.csv`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/data/dev_set_info_element_gt_and_input_desc.csv) is the central experiment table. It contains:

- `bug_id`
- `app_name`
- description columns such as `LC_LP Desc`, `MC_MP Desc`, `HC_HP Desc`
- ground-truth fields used by evaluation, including `info_elements_gt` and `S2R_ground_truth`

BURT++ reads the selected description column for the initial user message. The evaluator joins the same CSV back in to recover ground truth and description text.

### App Graph Database

BURT expects the application execution graph and app name to be available in the SQLite database accessed by [`database/db.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/database/db.py) and [`database/database_utils.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/database/database_utils.py).

If you need to load graph data, the repo includes [`database/load_data.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/database/load_data.py). That script is currently wired to a local absolute `DATA_DIR`, so you will likely need to edit it before using it in another environment.

## Running BURT

### Single Run

Example Use [`burt.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/burt.py) for one bug/description pair:

```bash
python burt.py --bug-id 10 --description-level LC_LP
```

`description_level` must be in the form `LC_LP`, `MC_MP`, `HC_HP`, etc. The script normalizes case and `-` vs `_`, but it still expects the `[L|M|H]C_[L|M|H]P` structure.

### What Happens During a Run

The BUR++ state graph is defined in [`burt.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/burt.py) and follows this loop:

1. `information_element_extraction`
2. `clarity_check`
3. Optional `clarity_follow_up`
4. `map_to_graph`
5. `evaluate_state`
6. Optional `more_info_follow_up`
7. `interrupt_and_present`
8. Repeat until no unknown or low-confidence information remains
9. `generate_report`

Operationally (Current Dev Version):

- The initial message is pulled from the CSV column matching the requested description level.
- BURT++ loads the app graph and app name for the bug ID from the database.
- If the graph decides more information is needed, the run interrupts and asks the user follow-up questions in the terminal.
- Once the graph is satisfied, BURT++ prints the final bug report.

### Log Output

BURT++ writes full conversation logs per run to:

```text
logs/<PROMPT_VERSION>/bug<bug_id>_<description_level>.log
```

Example:

```text
logs/mapping_and_clarity_check/bug10_LC_LP.log
```

The evaluator later parses these logs and looks specifically for the `generate_report` action payload.

## Batch Execution

[`run_all_burt.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/run_all_burt.py) is intended to iterate over every non-empty description cell in the CSV and run BURT for each `(bug_id, description_level)` pair.

Expected usage:

```bash
python run_all_burt.py
```

Behavior:

- It discovers every CSV column ending in ` Desc`.
- For each row, it schedules one run for every populated description column.
- It launches `burt.py` once per pair.
- It prints a batch summary with failures at the end.

Current caveat:

- [`run_all_burt.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/run_all_burt.py) currently invokes `burt.py` with `--current-bug-id`, while [`burt.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/burt.py) expects `--bug-id`. If you plan to use the batch script as-is, fix that argument mismatch first.

## Evaluating Logs

Use [`evaluator/runner.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/runner.py) to evaluate one log, many logs, or an entire log directory:

```bash
python -m evaluator.runner logs/V2
```

You can also point it at specific files:

```bash
python -m evaluator.runner logs/V2/bug10_LC_LP.log logs/V2/bug2_MC_MP.log
```

Optional model override:

```bash
python -m evaluator.runner logs/V2 --model gpt-5.2
```

### Evaluation Steps

For each discovered log file, the evaluator:

1. Parses the observability JSON records.
2. Extracts `bug_id`, `description_level`, and `agent_version` from the log path and filename.
3. Finds the `generate_report` action.
4. Reads the generated `full_report` from that action.
5. Loads the matching ground-truth row from the dev CSV.
6. Computes information elements from observed and expected behavior.
7. Judges information-elements with LLM.
8. Judges S2Rs with LLM.
9. Writes one `.evaluation.json` artifact.
10. Rebuilds aggregate review artifacts for the version directory.

## Evaluation Outputs

For each `agent_version` inferred from the log directory, the evaluator writes to:

```text
Results/<agent_version>/
```

Artifacts:

- `*.evaluation.json`: one file per evaluated log
- `summary.csv`: one row per evaluated log
- `s2r_manual_review.xlsx`: manual review workbook for S2R judgments
- `information_elements_manual_review.xlsx`: manual review workbook for info-element judgments

Example:

```text
Results/V2/bug10_HC_LP.evaluation.json
Results/V2/summary.csv
Results/V2/s2r_manual_review.xlsx
Results/V2/information_elements_manual_review.xlsx
```

### `summary.csv`

[`evaluator/runner.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/runner.py) rebuilds `summary.csv` from all `*.evaluation.json` files in the version directory. It includes:

- `bug_id`
- `description_level`
- `agent_version`
- `log_file`
- `log_path`
- `title`
- `status`
- `parse_status`
- `error`

### `s2r_manual_review.xlsx`

The S2R review workbook is built from the judged S2R steps and currently contains:

- `bug_id`
- `app_name`
- `agent_version`
- `description_level`
- `description_text`
- `full_bug_report`
- `s2r_gt`
- `agent_generate_steps`
- `LLM_evaluation`
- `Matched_GT_by_LLM`
- `human_evaluation`
- `Precision`
- `Recall`

Important detail:

- `human_evaluation` is initialized from `LLM_evaluation`.
- The `Precision` and `Recall` formulas count `CS` values from `human_evaluation`, not from the original LLM column.
- This workbook is intended for manual correction after the automatic judge pass.

### `information_elements_manual_review.xlsx`

The information-elements review workbook contains:

- `bug_id`
- `app_name`
- `agent_version`
- `description_level`
- `description_text`
- `full_generated_bug_report`
- `info_elements_gt`
- `agent_generated_info_elements`
- `buggy_behavior_grade`
- `triggering_gui_interactions_grade`
- `triggering_screen_reference_grade`
- `correct_behavior_grade`

Important detail:
- This workbook is intended for manual correction after the automatic judge pass.

## Recommended End-to-End Workflow

For a normal experiment cycle:

1. Ensure the description CSV and app-graph database are populated.
2. Run BURT for the desired `(bug_id, description_level)` pairs.
3. Confirm logs were written to `logs/<prompt_version>/`.
4. Run the evaluator on those logs.
5. Inspect `Results/<agent_version>/summary.csv` for failures.
6. Manually review `s2r_manual_review.xlsx`.
7. Manually review `information_elements_manual_review.xlsx`.

Minimal example:

```bash
python burt.py --bug-id 10 --description-level LC_LP
python -m evaluator.runner logs/mapping_and_clarity_check
```

## Key Files

- [`burt.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/burt.py): single-run interactive BURT CLI
- [`run_all_burt.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/run_all_burt.py): batch launcher across the CSV
- [`evaluator/runner.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/runner.py): evaluation entry point and workbook generation
- [`evaluator/parsing.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/evaluator/parsing.py): log discovery and parsing helpers
- [`data/dev_set_info_element_gt_and_input_desc.csv`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/data/dev_set_info_element_gt_and_input_desc.csv): experiment input and ground-truth CSV
- [`config.py`](/Users/sambennett/Desktop/BURT++/Agentic_Burt/config.py): default model/version configuration
