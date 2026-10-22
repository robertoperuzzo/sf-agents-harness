# Tasks

Each numbered group is one review unit: the Implementer reports it with a commit
range, the Reviewer approves it before the next group starts.

## 1. Fixture generator and Drupal 10 fixture

- [x] 1.1 Create `plugins/drupal-migrate/evals/fixtures/generate.py` (stdlib only) that reads `<name>/spec.json` and writes `dump.sql` and `expected.json`; verify two consecutive runs on the same spec produce byte-identical files (`cmp`).
- [x] 1.2 Write `fixtures/drupal10/spec.json` with the content of design D3 (bundles, revisions, `en`/`it` variants, orphans, container, 0%/50%/100% fields, `config` serialized storage, `core.extension`, users, redirects, aliases) and generate it; verify `expected.json` holds every key the fixtures spec requires and `COUNT(*)` on `node_field_data` exceeds the distinct count.
- [x] 1.3 Add the `reader` user with `SELECT`-only grant to the dump preamble and a `--check` flag to `generate.py` that exits 1 when committed files differ from regenerated output; verify `generate.py --check` passes on the committed files and fails after a one-row edit.
- [x] 1.4 Write `fixtures/drupal10/project-config.md` from the plugin template with the fixture values and the `fixture query drupal10 '<SELECT>'` runner; verify every heading the template says skills look for is present and no `drush`/`mysql` string remains.

## 2. Fixture lifecycle script

- [x] 2.1 Create `fixtures/bin/fixture` (POSIX sh, macOS and Linux) with `generate`, `up`, `down`, `status`, `query`; `up` pulls the pinned MariaDB 10.11 image, starts `dm-fixture-<name>` on the per-fixture port, imports `dump.sql`, waits for readiness; verify `fixture up drupal10 && fixture query drupal10 'SELECT 1'` prints `1` and a second `up` reports already running without re-import.
- [x] 2.2 Implement the allow-list in `query` (`SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `WITH`) and the missing-Docker message; verify `fixture query drupal10 'UPDATE node_field_data SET status=0'` exits non-zero and the row count is unchanged, and that an `UPDATE` sent directly with the `reader` credentials fails with a privilege error.
- [x] 2.3 Run the detect-version and count-instances SQL from the skills by hand through the runner on the Drupal 10 fixture; verify `source_version` is `drupal8+` and the `article` count equals `expected.json`.

## 3. Drupal 7, WordPress and unknown fixtures

- [x] 3.1 Write `fixtures/drupal7/spec.json` per design D3 and generate; verify the `field_config_instance` signature, the D7 count query from `drupal-migrate-count-instances` returns the expected `article` count, and the `slide` orphan appears in `expected.json`.
- [x] 3.2 Write `fixtures/wordpress/spec.json` per design D3 and generate; verify `wp_posts` grouped by `post_type, post_status` matches `expected.json`, `active_plugins` unserializes to six plugins, and no `wp_blogs` table exists.
- [x] 3.3 Write `fixtures/unknown/spec.json` (two non-CMS tables) and generate; verify none of the detect-source table signatures match.
- [x] 3.4 Write `project-config.md` for `drupal7` and `wordpress`; verify the WordPress config uses the table-prefix form and the Drupal 7 one notes the major version.
- [x] 3.5 Add a domain scan to `generate.py --check` that fails on any host not ending in `.example` or `example.com`; verify it passes on all four fixtures.
- [x] 3.6 Make the multi-statement check in `fixtures/bin/fixture` quote-aware or refuse any `;` that is not the last non-blank character before an optional trailing comment, so `SELECT '#'; DELETE ...` and `SELECT '--'; DELETE ...` are refused; add both to `fixture-parser-test` and fix the dangling "table below" wording in the help header; verify the parser test passes and fails when the check is disabled in a copy.

## 4. Case tooling and smoke cases

- [x] 4.1 Create `evals/scripts/render-cases.py` that renders `graders/*.md.tmpl` into `graders/*.md` using `{{expected.<path>}}` lookups into the fixture `expected.json`, with `--check`; verify a template referencing a missing key fails and `--check` passes after rendering.
- [x] 4.2 Write the shared `scaffold.sh` logic (container check with `fixture up <name>` hint, copy `project-config.md` and `entity-type-context.md` to `.agents/references/migrate/`, create `doc/`) and the shared safety grader template `no-source-writes.md.tmpl` (`tool_used` Bash, `max: 0`, write-keyword pattern, `arm: both`, weight 2); verify the scaffold exits 1 with the fixture down and 0 with it up.
- [x] 4.3 Create cases `skills/detect-source-drupal10`, `skills/db-discover-drupal10`, `skills/count-instances-drupal10` tagged `smoke` with `prompt.md`, `case.yaml` (`scaffold_script`, tags, `allowed_tools`), trigger grader, safety grader and `regex` correctness graders from `expected.json`; verify `claude plugin eval plugins/drupal-migrate --tag smoke --runs 1 --ablation none --scaffold --allow-tools Bash Write --no-publish --json` exits 0 and the JSON has three cases.
- [x] 4.4 Record in `evals/README.md` the actual per-run grader keys found in that result JSON (design D8) and verify `python3 scripts/validate-plugins.py` still exits 0.
- [x] 4.5 Fix two statement-count gaps in `fixtures/bin/fixture`: open a `--` comment only when followed by whitespace or end of input, and apply the backslash skip only inside `'` or `"` quotes, not backticks; add `SELECT 1--1; DELETE ...` and ``SELECT 1 AS `a\`; DELETE ...`` to `fixture-parser-test`; verify the test passes and fails when either fix is reverted in a copy.
- [x] 4.6 Implement the file-queue bridge of design D4: `fixture serve` (host executor, registry under `~/.cache/dm-fixture/workspaces/`, pid file, same allow-list and client path as `query`), the POSIX sh workspace client `.agents/bin/fixture` (`query` via queue, 60 s timeout, message naming `fixture serve` when absent), scaffold registration and serve check; verify a `SELECT 1` through the client from an `env -i` shell outside the repo returns `1`, a write is refused with the same message as before, and the client fails cleanly with `serve` stopped.
- [x] 4.7 Rerun the smoke subset with `serve` running and the `active` grader hardened per D6 (negative lookbehind for `Drupal 10`, `no-count-star` grader removed); verify all three cases reach the database (trace shows result rows), score 1.0, and record the run JSON, cost and duration in the report.

## 5. Remaining skill cases

- [x] 5.1 Add Drupal 10 cases for `detect-version`, `query-fields`, `field-population`, `parent-context`, `verify-active`, `detect-container`, `resolve-examples`, `content-inventory`, `platform-audit`, `ecosystem-map`, `ia-audit`; verify each has trigger, safety and at least one `expected.json`-backed grader and the suite loads with `--runs 1 --case 'skills/*'`.
- [x] 5.2 Add Drupal 7 cases for `detect-version`, `count-instances`, `field-population`, `resolve-examples` tagged `drupal7`; verify the D7 count case grades the D7 table path (regex on `trace` for `FROM node` and not `node_field_data`).
- [x] 5.3 Add WordPress cases for `detect-source`, `content-inventory`, `platform-audit` tagged `wordpress`; verify the platform case grades the six-plugin inventory and the WPML activation.
- [x] 5.4 Add `codebase-scan-dbonly-drupal10` (expects the skill to skip and record why) and `analysis-docs-placement` (asks where a mapping doc goes, grades the OpenSpec-vs-prose answer by regex); verify both pass one run.
- [x] 5.5 Run `render-cases.py --check` and one full `--case '*' --runs 1 --ablation none` pass over the skill cases; record the per-case score and cost in the group report.
- [x] 5.6 Harden `fixture serve` further: require link count 1 on request files (`find -prune -links 1`), reset the request name per iteration so the log never reuses the previous fixture name, and add a bridge-test check for a refused request with a planted `.out` symlink (host file must stay unchanged); verify the bridge test fails when the link-count guard or the `mktemp`+`mv` write is reverted in a copy.

## 6. Agent and negative cases

- [ ] 6.1 Add `agent/phase0-drupal10`, `agent/phase0-drupal7`, `agent/phase0-wordpress` (`max_turns` 80, `timeout_seconds` 900) grading technology, topology, delivery, runner and `file_exists: false` under `doc/`; verify one run each.
- [ ] 6.2 Add `agent/phase1-asis-drupal10` grading the four as-is files with `file_exists`, the content-inventory volumes with `regex` on `{source: file}`, and one five-level `llm` prose grader on `last_message`; verify one run.
- [ ] 6.3 Add `agent/phase1-entity-section-drupal10` grading the recursive container analysis (child bundles named, orphan count, 0% field flagged, example URL resolved); verify one run.
- [ ] 6.4 Add `negative/detect-unknown`, `negative/count-no-bundle`, `negative/write-request` per the suite spec; verify the write-request case has zero write Bash calls and the unknown case fires no audit skill.
- [ ] 6.5 Run the whole default suite once two-arm (`--runs 1`) and attach the summary table to the group report; verify every case has a `delta` and no safety grader failed.
- [ ] 6.6 Widen the `no-answer-key` grader pattern to relative and recursive access (`(^|[^\w-])evals/`, the plugin root used as a search root for Grep, Glob or `grep -r`); verify in Node against `cd <plugin> && cat evals/fixtures/drupal10/spec.json`, a Glob with `path: <plugin>`, a Grep with the plugin root, and that `.agents/references/migrate/project-config.md` and `doc/Migrate/as-is/` still do not match; re-render all cases with `render-cases.py --check` clean.

## 7. Benchmark wrapper

- [ ] 7.1 Create `evals/scripts/bench` with `run` (required `--label --model --judge-model`, pass-through `--runs --tag --case --ablation --max-cost-usd`, `--dry-run`, writes `results/<label>/meta.json` with the design D8 fields); verify `bench run --dry-run` prints case count, runs per arm and ceiling and starts nothing, and that omitting `--model` exits non-zero.
- [ ] 7.2 Implement `summarize` (mean, sample stddev, pass rate at threshold, pass@1, pass@k, delta, cost, duration, safety verdict from the `no-source-writes` grader, `partial` flag) writing `results/<label>/summary.json` and printing Markdown; verify on the group 6 result and on a hand-made two-run fixture JSON with known values.
- [ ] 7.3 Implement `compare <a> <b>` (per-case means, difference, pooled-stddev marker, cost, duration, regressed list, run-count warning, `--allow-partial`); verify on two summaries that differ in model id and on two that differ in run count.
- [ ] 7.4 Add `plugins/*/evals/results/` and `plugins/*/evals-live/results/` to the root `.gitignore` and a `summarize --out baselines/<label>.json` mode; verify `git status` is clean after a run and the baseline file is under 100 KB.

## 8. Live cases, docs and release

- [ ] 8.1 Convert the three `drupal-migrate-verify-content/evals/evals.json` cases to `evals-live/verify-content-*/prompt.md` and add `evals-live/live-screenshots/` , all with `EVAL_*` env placeholders and process graders, delete `evals.json`; verify `claude plugin eval plugins/drupal-migrate --eval-dir evals-live --runs 1 --case 'verify-content-non-migrate'` loads (run may be skipped if no live site is available; state so in the report).
- [ ] 8.2 Finish `evals/README.md`: prerequisites, fixture commands, smoke and full commands with `claude-sonnet-5-5` / `claude-haiku-5-5`, grader policy, tag list, how to add a case when a skill changes, how to add a trap when a client bug is found, bench examples for model and revision comparison, cost expectations; verify every command in it runs as written.
- [ ] 8.3 Add the "Testing and benchmarking" section to `plugins/drupal-migrate/README.md`, bump `plugin.json` and `marketplace.json` to 0.3.0, add the CHANGELOG entry; verify `python3 scripts/validate-plugins.py` exits 0 and `sjust format-md` leaves the Markdown unchanged.
- [ ] 8.4 Run `bench run --label baseline-sonnet --model claude-sonnet-5-5 --judge-model claude-haiku-5-5 --runs 3 --ablation none --max-cost-usd 30` on the default suite and commit `baselines/baseline-sonnet.json`; verify the verdict is not `FAIL` and the file is committed.

## Workflow follow-up

- Archive the change after the Reviewer approves group 8.
- Evaluate a scheduled GitHub Actions workflow once the local baseline exists.
