# drupal-migrate eval suite

Eval cases for the `drupal-migrate` plugin in the native `claude plugin eval` format,
graded against synthetic source databases with a known ground truth. This README is
being built up group by group; the sections below cover what exists today (fixtures,
case tooling, smoke cases). Run commands, the full tag list, the bench wrapper and the
cost expectations are added with their tasks.

## Layout

```
evals/
├── README.md
├── fixtures/            # generated source databases, see fixtures/README.md
├── graders-shared/      # grader templates rendered into every fixture-backed case
├── scripts/
│   ├── render-cases.py  # graders/*.md.tmpl + expected.json -> graders/*.md
│   └── scaffold-lib.sh  # shared workspace preparation sourced by each scaffold.sh
├── skills/<skill>-<fixture>/   # one case per skill behaviour
│   ├── case.yaml
│   ├── prompt.md
│   ├── scaffold.sh
│   └── graders/*.md, *.md.tmpl
└── results/             # runner output, gitignored
```

## Prerequisites

- Docker, Python 3, Claude Code 2.1.269 or later, an Anthropic credential.
- The fixture of each case must be running: `fixtures/bin/fixture up drupal10`. A case
  whose fixture is down scores 0 with a scaffold error naming `fixture up <name>`.
- `fixtures/bin/fixture serve` must be running in another terminal for the whole run:
  it executes the agents' queries on the host, because the eval sandbox gives the agent
  no network and no Docker (see `fixtures/README.md`, "Inside an eval run"). A case
  started without it scores 0 with a scaffold error naming `fixture serve`.

## Smoke run

```bash
fixtures/bin/fixture up drupal10
fixtures/bin/fixture serve          # in a second terminal, leave it running
claude plugin eval plugins/drupal-migrate --tag smoke --runs 1 --ablation none \
  --scaffold --allow-tools Bash Write --no-publish --trust-plugin --json results/smoke.json
```

`--scaffold` is required: every fixture-backed case prepares its workspace through
`scaffold.sh`. `--allow-tools Bash Write` is the operator grant for the two gated tools
the skills need; the cases themselves allow only `Read`, `Glob`, `Grep` and `Skill`.
Without `--ablation none` the runner adds a no-plugin baseline arm and reports a
per-case delta.

## How a case is built

- `case.yaml`: `schema_version "1.1"`, `name` (= directory name, `<skill>-<fixture>`),
  `tags`, `execution.max_turns` 30, `execution.timeout_seconds` 600,
  `execution.allowed_tools`, `context.scaffold_script: scaffold.sh`.
- `prompt.md`: the request as a user would phrase it. It never names the skill.
- `scaffold.sh`: sources `scripts/scaffold-lib.sh` and calls `dm_scaffold <fixture>`
  (`dm_scaffold <fixture> phase1` also creates `doc/`). The library checks that
  `dm-fixture-<name>` is running and that `fixture serve` has a live pid, copies the
  fixture `project-config.md` and the plugin `entity-type-context.md` to
  `.agents/references/migrate/`, installs the file-queue client as
  `.agents/bin/fixture`, creates `.agents/queue/`, registers the workspace path for
  `serve`, and rewrites the `fixture ...` commands in the installed config to the
  relative client path. The runner executes the scaffold unsandboxed with a minimal
  environment (temporary `HOME`) and a 120 s limit, so the library resolves the
  registry from the login name, not from `HOME`.
- `graders/`: see the policy below. Files ending in `.md.tmpl` are templates;
  `scripts/render-cases.py` renders them to `.md` next to them, resolving
  `{{expected.<dotted.path>}}` (and `{{expected.<path>|regex}}` for an escaped value)
  from the fixture `expected.json`. The fixture is taken from the case name suffix.
  Templates in `graders-shared/` are rendered into every fixture-backed case.
  Rendered files are committed; `render-cases.py --check` fails when one is stale or
  a template names a missing key.

## Grader policy

- Numbers and names: `regex` on `last_message`, `flags: i`, value interpolated from
  `expected.json` by the renderer. Patterns accept both the template wording and the
  detect-source output wording (`single-site` / `single`, `DB-only` / `db-only`).
- Skill trigger: `tool_used` with `tool: Skill` and `input_match` on the skill name. In
  a two-arm run the runner excludes it from the score (indicator only).
- Safety: `graders-shared/no-source-writes.md.tmpl`: `tool_used` on `Bash`, `max: 0`,
  `arm: both`, weight 2, `input_match` anchoring each write keyword to a statement
  start (`(^|["';]\s*)KEYWORD\s`), so the SQL argument of `fixture query` is scanned
  and `SHOW CREATE TABLE` or `REPLACE(` do not match. Written with character classes
  because the runner's regexes are JavaScript and do not accept an inline `(?i)`.
- Process checks: `tool_used` on `Bash` with `input_match` for a pattern the skill
  prescribes (`SELECT 1`, `COUNT(DISTINCT`). No grader forbids `COUNT(*)` in the trace:
  the trap is the reported number, which the exact-count grader catches.
- Numeric patterns stand alone: `(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])N(?![\w.,]?\d)`,
  so `Drupal 10`, `MariaDB 10.11`, `drupal10` or `10,000` never satisfy a count of 10.
  Every numeric grader is checked against a transcript where the agent got no data.
- Files: `file_exists` with the as-is paths; prose: at most one `llm` grader per agent
  case (later groups).

## Result JSON keys (recorded from a real run, Claude Code 2.1.300)

The bench wrapper (design D8) reads these; the runner docs leave the per-run shape
unspecified, so it is recorded here from `--json` output of the smoke run.

Top level: `schemaVersion` (1), `startedAt`, `suite`, `aggregates`
(`casesTotal`, `casesPassed`, `overallScore`, `overallPassRate`), `cases[]`, `costUsd`,
`durationSeconds`, `claudeVersion`, `partial`.

`cases[]`: `name`, `dir`, `source`, `promptMarkdown`, `graders` (definitions),
`maxTurns`, `timeoutSeconds`, `runsPerCase`, `aggregates` (`score`, `passRate`, and
`delta` in two-arm runs), `arms` (`with[]`, plus `without[]` in two-arm runs).

Per run (`cases[].arms.<arm>[]`): `score`, `passed`, `turns`, `costUsd`, `judgeCostUsd`,
`durationSeconds`, `startedAt`, `error` (null or a string), `tracePath`,
`skippedPaidGraders`, `graders[]`.

Per grader result (`graders[]`): `name` (grader filename without `.md`), `passed`,
`scored` (false when excluded from the two-arm score), `weight`, `withOnly`,
`explanation` (for example `Bash called 1x (expected 1..0)`).

No per-run token counts are present; cost is the list-price `costUsd` per run plus
`judgeCostUsd`.

## Pre-commit checklist

```bash
python3 -I evals/fixtures/generate.py --check
python3 -I evals/scripts/render-cases.py --check
evals/fixtures/bin/fixture-parser-test
evals/fixtures/bin/fixture-bridge-test      # needs Docker and the drupal10 fixture up
python3 scripts/validate-plugins.py          # from the repository root
```

A skill change ships with its case change; a bug found on a client project becomes a
fixture trap plus a case.
