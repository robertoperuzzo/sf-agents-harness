# Spec Delta

## Purpose

Labelled, repeatable benchmark runs of the `drupal-migrate` eval suite and a comparison of two runs, so a change of model, skill text or orchestration can be judged on numbers instead of impressions.

## ADDED Requirements

### Requirement: A benchmark run is labelled and pinned

The `bench run` command SHALL execute the eval suite with an explicit model, judge model and run count, and SHALL store the result under a label together with the plugin git revision, the Claude Code version, the fixture generator version, the date, and the exact command line used.

#### Scenario: Run metadata recorded

- **WHEN** `bench run --label sonnet-baseline --model <m> --judge-model <j> --runs 5` completes
- **THEN** `results/sonnet-baseline/meta.json` holds `model`, `judge_model`, `runs`, `plugin_sha`, `claude_version`, `fixtures_version`, `date` and `command`

#### Scenario: Missing model refused

- **WHEN** `bench run` is invoked without `--model` or `--judge-model`
- **THEN** it exits non-zero and explains that unpinned models make results incomparable

### Requirement: Benchmark reports per-case statistics

From the per-run scores the benchmark SHALL compute, per case and overall: mean score, sample standard deviation, pass rate at the configured threshold, pass@1 and pass@k for k equal to the run count, the with-minus-without delta, total cost in USD and wall-clock duration.

#### Scenario: Statistics computed

- **WHEN** a run with five repetitions per case is summarised
- **THEN** every case row shows mean, stddev and pass rate computed over five scores, and the overall row aggregates all cases

#### Scenario: Partial run flagged

- **WHEN** the underlying eval result has `partial: true`
- **THEN** the summary marks the label as partial and the comparison refuses to use it as a baseline unless `--allow-partial` is given

### Requirement: Safety failures dominate the verdict

The benchmark verdict SHALL be `FAIL` whenever any run of any case fails its read-only safety grader, independent of the mean score.

#### Scenario: One write attempt

- **WHEN** one run out of twenty-five contains a write statement in a Bash call
- **THEN** the summary verdict is `FAIL` and the offending case and run are named

### Requirement: Two labels can be compared

The `bench compare <label-a> <label-b>` command SHALL print a Markdown table with one row per case showing the mean score of each label, the difference, whether the difference exceeds the pooled standard deviation, and the cost and duration of each label, followed by an overall row.

#### Scenario: Model comparison

- **WHEN** two labels differ only in `model`
- **THEN** the table header names both models and each row shows the score difference with a marker when it exceeds one pooled standard deviation

#### Scenario: Plugin revision comparison

- **WHEN** two labels differ only in `plugin_sha`
- **THEN** the table header names both revisions and the output lists cases that regressed

#### Scenario: Labels differ in run count

- **WHEN** the two labels have different run counts
- **THEN** the comparison still runs and warns that pass@k is not comparable

### Requirement: Results stay out of version control except summaries

Raw eval results SHALL be ignored by git. A `bench summarize` command SHALL write a compact summary (no transcripts) that can be committed as a baseline.

#### Scenario: Ignored raw results

- **WHEN** a benchmark run completes
- **THEN** `git status` shows no new tracked file under the results directory

#### Scenario: Committed baseline

- **WHEN** `bench summarize <label> --out baselines/<label>.json` runs
- **THEN** the output is under 100 KB and contains per-case statistics and the run metadata but no prompts or transcripts

### Requirement: Benchmark cost is bounded

`bench run` SHALL pass a cost ceiling to the eval runner, defaulting to a documented value, and SHALL report the estimated cost before starting when `--dry-run` is given.

#### Scenario: Dry run

- **WHEN** `bench run --dry-run ...` is invoked
- **THEN** it prints the case count, the run count per arm, and the ceiling, and starts nothing
