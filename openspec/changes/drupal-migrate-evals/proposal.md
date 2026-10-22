# Proposal

## Why

The `drupal-migrate` plugin (21 skills, one agent, ~3,700 lines of prompt) has been
refined over nine commits of review fixes, but nothing verifies that it still behaves as
designed: the only eval is a three-case `evals.json` for one skill that no tool in this
repository runs. Every edit to a skill, every Claude model release and every change to
the orchestration is validated by hand on a client database, which gives a false sense
of safety for a probabilistic system. The plugin needs a repeatable way to prove the
harness works, to put numbers on the quality of its output, and to compare those numbers
across skill versions and models.

## What Changes

- Add synthetic **fixture source databases** (Drupal 10, Drupal 7, WordPress) generated
  from a single declarative spec, each with a machine-readable ground truth
  (`expected.json`), a fixture `project-config.md`, and a read-only query runner. Served
  by MariaDB in Docker through one `fixture` script (`up`, `down`, `query`, `generate`).
- Add an **eval suite** under `plugins/drupal-migrate/evals/` in the native
  `claude plugin eval` format: one case per skill behaviour plus agent-level phase cases
  and negative cases (unknown CMS, missing bundle, write-query refusal). Deterministic
  graders check counts, file paths, skill triggering and read-only safety against the
  ground truth; LLM graders are used only for report prose and capped at five-level
  rubrics.
- Add a **benchmark harness**: a wrapper that runs the suite with pinned model, judge
  model, run count and plugin git revision, stores a labelled result, and a comparison
  script that diffs two labelled results per case (score mean and stddev, pass rate,
  delta vs the no-plugin baseline, cost, duration) and prints a Markdown table.
- Document how to run, read and extend the suite in `plugins/drupal-migrate/evals/README.md`
  and in the plugin README; bump the plugin version; add a CHANGELOG entry.
- Replace the skill-creator style `skills/drupal-migrate-verify-content/evals/evals.json`
  with cases in the new format so one tool runs everything. Cases that need a live
  source and destination site live in a separate eval dir (`evals-live/`) that is run
  only on request.
- No CI workflow in this change. The suite is run locally; a scheduled workflow is
  evaluated after the first local results.

## Capabilities

### New Capabilities

- `drupal-migrate-eval-fixtures`: synthetic source databases with known ground truth,
  their lifecycle (generate, start, query read-only, stop) and the guarantee that the
  dump and the expected values are produced from the same spec.
- `drupal-migrate-eval-suite`: the eval cases and graders that establish whether the
  plugin's skills and agent behave as designed on the fixtures, including the read-only
  safety gate and the no-plugin ablation.
- `drupal-migrate-benchmark`: labelled benchmark runs, the metrics they record, and the
  comparison of two runs that differ by model, plugin revision or run count.

### Modified Capabilities

None. No existing spec covers the plugin.

## Impact

- New files under `plugins/drupal-migrate/evals/` (cases, graders, fixtures, scripts,
  README) and `plugins/drupal-migrate/evals-live/`; new `.gitignore` entries for results.
- `plugins/drupal-migrate/.claude-plugin/plugin.json`: version bump; no `experimental.evals`
  key because the default `evals/` dir is used.
- `plugins/drupal-migrate/README.md`: new "Testing and benchmarking" section.
- `skills/drupal-migrate-verify-content/evals/evals.json`: removed.
- `scripts/validate-plugins.py`: unchanged behaviour; the eval dir must not break it.
- Dependencies for whoever runs the suite: Docker, Python 3, Claude Code 2.1.269+,
  an Anthropic credential. Each full run spends real tokens.
- `CHANGELOG.md`, root `README.md` plugins table (description unchanged, version only).
