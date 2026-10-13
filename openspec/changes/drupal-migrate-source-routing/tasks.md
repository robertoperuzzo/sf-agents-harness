# Tasks

## 1. Routing facts record

- [ ] 1.1 Define the canonical routing-facts block (`source_tech`, `topology`, `delivery`, `db_access_method`, `source_version`, each with `from: project-config | detected` and evidence) in `drupal-migrate-detect-source` and `drupal-migrate-detect-version`, and verify both skills print it in the documented shape on a Drupal 8+ and a WordPress fixture description.
- [ ] 1.2 Update `drupal-migration-analyst.agent.md`: replace "pass `source_version: drupal7` to every step" and the per-skill access-method reminders with one "Routing facts" section that every phase reads, narrow the "If a skill is not loaded, perform its documented logic inline" rule so it never applies to a skill that refused to run, and verify the agent file no longer mentions the per-step passing and states the refusal exception.
- [ ] 1.3 Add the "source cannot be identified" stop behaviour to `detect-source` (inputs-needed block, no default to Drupal or drush), and verify by reading the skill that no path leads to a query without an identified source.

## 2. Variant split, first skill

- [ ] 2.1 Restructure `drupal-migrate-count-instances` into a source-independent `SKILL.md` plus `variants/drupal8.md` and `variants/drupal7.md`, with a "Load the variant" step before Step 1, and verify the loaded body plus one variant contains every query the current skill contains for that source and none for the other.
- [ ] 2.2 Add the Drupal-only refusal to the same skill (refuse when `source_tech` is `wordpress` or `other`, name the WordPress equivalent where one exists), and verify with an eval prompt that a WordPress source gets the refusal message and no query.
- [ ] 2.3 Add evals under `skills/drupal-migrate-count-instances/evals/` for the D7 variant, the D8+ variant and the WordPress refusal, and verify they run with the skill-creator eval runner.

## 3. Variant split, remaining skills

- [ ] 3.1 Apply the pattern from group 2 to the six other skills that branch on Drupal 7: four with a "Drupal 7 differences" block (`parent-context`, `verify-active`, `field-population`, `resolve-examples`) and two with "Drupal 7" / "Drupal 8+" step headings (`detect-container`, `query-fields`), and verify each loaded body plus variant matches its current content per source.
- [ ] 3.2 Apply the pattern to the four skills with WordPress and Drupal branches other than `detect-source` (`content-inventory`, `ia-audit`, `platform-audit`, `db-discover`) with `variants/wordpress.md`, `variants/drupal7.md` and `variants/drupal8.md` as applicable, and verify each; `detect-source` keeps its branches because it is the detector.
- [ ] 3.3 Add the "variant missing for this source" stop to the shared "Load the variant" step wording, and verify by reading each restructured skill that the wording is identical across them.
- [ ] 3.4 Update the `DB-only` short-circuit in `codebase-scan` and `platform-audit` to read `delivery` from the routing facts, and verify the recorded sentence matches the spec scenario text.

## 4. Entity type by DB lookup

- [ ] 4.1 Replace the entity-type name heuristic in `drupal-migration-analyst.agent.md` and `drupal-migrate-count-instances` with the bundle-configuration lookups from design D3 (Drupal 8+ `config` names `node.type.*`, `paragraphs.paragraphs_type.*`, `taxonomy.vocabulary.*`, `media.type.*`, `block_content.type.*`; Drupal 7 `node_type`, `paragraphs_bundle`, `taxonomy_vocabulary`, `file_type`), honouring a `project-config.md` mapping first, and verify the queries on a local Drupal 8+ site return the entity type for a node type with only base fields and for an empty vocabulary.
- [ ] 4.2 Add the ambiguous (more than one match), missing (zero rows) and no-configurable-fields outcomes to the skill, and verify with evals that each outcome produces the specified message and that a field-less bundle is not reported as missing.

## 5. Hooks module (Claude Code)

- [ ] 5.1 Create `plugins/drupal-migrate/hooks/hooks.json`, `hooks/register.ts` and `types/index.d.ts` with a facts loader that runs on the first `tool.call` for a `drupal-migrate-*` skill (and at `session.start` only when `.agents/references/migrate/project-config.md` exists), reads `project-config.md`, runs the signature checks through `$.process.run` only in the CLI, leaves undeclared facts unset in the desktop app, fills `$.state` from the `detect-source` tool-call result, and verify with a test that a session in a project without `project-config.md` runs no host command, plus `claude plugin validate plugins/drupal-migrate` and `tsc -p plugins/drupal-migrate`.
- [ ] 5.2 Confirm how the hooks module resolves its own plugin root (the `skill.prompt` input carries only `skill` and `text`; check `register`'s `options`, else derive from the module location), then add the `skill.prompt` hook that appends `variants/<source>.md` to a restructured skill's body, and verify with a `*.test.ts` run by `claude plugin test` that the served text equals body plus the one variant file for each of `wordpress`, `drupal7`, `drupal8+`.
- [ ] 5.3 Add the `tool.call` hook on `Skill` that denies a Drupal-only skill when `source_tech` is not Drupal, with the refusal message from group 2, and verify with a test and with the group 2 eval that the agent does not run the skill's queries inline after the denial.
- [ ] 5.4 Document the mod in `plugins/drupal-migrate/README.md` (what it does, Claude Code only, `$.process` CLI only, checked build, how to disable in `/plugin`), and verify the documented disable step leaves the file-based variant path working.
- [ ] 5.5 Add a CI step under `.github/workflows/` that runs `claude plugin validate plugins/drupal-migrate` when the Claude Code CLI installs on the runner and otherwise `tsc -p plugins/drupal-migrate` against the checked-in declaration file, and verify the step fails on a deliberately broken `hooks.json`.

## 6. Classifier integration (dormant until enabled)

- [ ] 6.1 Add the optional `Classifier` section from design D5 (including `Batch size`) to `references/project-config.template.md`, and verify every field the skills read is named in the template with its default behaviour when absent.
- [ ] 6.2 Create `plugins/drupal-migrate/scripts/classify.sh` (curl 7.76+, reads `TYPESAFE_API_KEY`, takes item references on stdin, fetches and strips page content itself for `verify-content` items using `{dest_runner}` for the destination, batches by `Batch size`, retries 429/529 with backoff, halves and retries once on 422, prints the routing result, exits non-zero on failure) and verify it against the API with a one-question request when a key is available, and against a local mock otherwise.
- [ ] 6.3 Add the classifier client to the hooks module (`$.fs.read` for plugin files, `$.http.fetch` or `$.process.run` for pages, same stripping and request shape as the script, option-order randomisation, batch sizing, confidence routing, `security` hint never accepted as disposition), and verify with tests that each routing scenario in `migrate-classifier-routing` maps to the expected path, including the too-large and unfetchable-page scenarios.
- [ ] 6.4 Add the classifier step to `drupal-migrate-codebase-scan` (choice over `replicate`, `triage`, `do_not_port`, `other` plus a security yes/no hint), gated on enabled, key present and `data_processing_approved`, and verify the skill reads unchanged when the section is absent.
- [ ] 6.5 Add the classifier step to `drupal-migrate-scan-destination` (choice over destination fields plus `none`), gated the same way, and verify.
- [ ] 6.6 Add the classifier step to `drupal-migrate-verify-content` so the agent passes URL pairs only and the client fetches and strips both pages (score 1 to 5 per pair, pass level and confidence threshold from config, unfetchable or JavaScript-rendered pages routed to the existing browser comparison with the reason recorded), gated the same way, and verify with a test that an accepted pair is never opened by the agent.
- [ ] 6.7 Add the per-run classifier report block (items classified, accepted, routed to LLM, fallbacks with reason, input tokens, model id, non-English note) to the three skills, and verify the block appears only when the classifier ran.
- [ ] 6.8 Implement the `measure` flag (both paths on every item, per-item agreement table in the report, only the LLM result written to the docs), and verify with a test that the migration docs are unchanged by a measurement run.

## 7. Integration and release

- [ ] 7.1 Run the full as-is workflow through the analyst agent on a local Drupal 8+ fixture and on a WordPress fixture description, and verify each run loads only the matching variants and the roadmap block carries the routing facts.
- [ ] 7.2 Bump `version` in `plugins/drupal-migrate/.claude-plugin/plugin.json`, update `plugins/drupal-migrate/README.md` (variants, mod, classifier section) and `CHANGELOG.md`, and verify the changelog entry sits under today's date with the project's categories.

## Workflow follow-up

- Run the classifier measurement on one Italian and one English completed migration once the data-processing agreement is recorded; review the agreement table before setting default thresholds in the template.
- Archive the change after review.
