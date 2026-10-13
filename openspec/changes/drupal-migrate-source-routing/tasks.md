# Tasks

## 1. Routing facts record

- [ ] 1.1 Define the canonical routing-facts block (`source_tech`, `topology`, `delivery`, `db_access_method`, `source_version`, each with `from: project-config | detected` and evidence) in `drupal-migrate-detect-source` and `drupal-migrate-detect-version`, and verify both skills print it in the documented shape on a Drupal 8+ and a WordPress fixture description.
- [ ] 1.2 Update `drupal-migration-analyst.agent.md`: replace "pass `source_version: drupal7` to every step" and the per-skill access-method reminders with one "Routing facts" section that every phase reads, and verify the agent file no longer mentions the per-step passing.
- [ ] 1.3 Add the "source cannot be identified" stop behaviour to `detect-source` (inputs-needed block, no default to Drupal or drush), and verify by reading the skill that no path leads to a query without an identified source.

## 2. Variant split, first skill

- [ ] 2.1 Restructure `drupal-migrate-count-instances` into a source-independent `SKILL.md` plus `variants/drupal8.md` and `variants/drupal7.md`, with a "Load the variant" step before Step 1, and verify the loaded body plus one variant contains every query the current skill contains for that source and none for the other.
- [ ] 2.2 Add the Drupal-only refusal to the same skill (refuse when `source_tech` is `wordpress` or `other`, name the WordPress equivalent where one exists), and verify with an eval prompt that a WordPress source gets the refusal message and no query.
- [ ] 2.3 Add evals under `skills/drupal-migrate-count-instances/evals/` for the D7 variant, the D8+ variant and the WordPress refusal, and verify they run with the skill-creator eval runner.

## 3. Variant split, remaining skills

- [ ] 3.1 Apply the pattern from group 2 to the six other skills with a "Drupal 7 differences" block (`parent-context`, `verify-active`, `detect-container`, `query-fields`, `field-population`, `resolve-examples`), and verify each loaded body plus variant matches its current content per source.
- [ ] 3.2 Apply the pattern to the four skills with WordPress and Drupal branches (`content-inventory`, `ia-audit`, `platform-audit`, `db-discover`) with `variants/wordpress.md`, `variants/drupal7.md` and `variants/drupal8.md` as applicable, and verify each.
- [ ] 3.3 Add the "variant missing for this source" stop to the shared "Load the variant" step wording, and verify by reading each restructured skill that the wording is identical across them.
- [ ] 3.4 Update the `DB-only` short-circuit in `codebase-scan` and `platform-audit` to read `delivery` from the routing facts, and verify the recorded sentence matches the spec scenario text.

## 4. Entity type by DB lookup

- [ ] 4.1 Replace the entity-type name heuristic in `drupal-migration-analyst.agent.md` and `drupal-migrate-count-instances` with the Drupal 8+ `config` lookup and the Drupal 7 `field_config_instance` lookup from design D3, honouring a `project-config.md` mapping first, and verify the queries run on a local Drupal 8+ site and return the second segment as entity type.
- [ ] 4.2 Add the ambiguous (more than one entity type) and missing (zero rows) outcomes to the skill, and verify with evals that each outcome produces the specified stop message.

## 5. Hooks module (Claude Code)

- [ ] 5.1 Create `plugins/drupal-migrate/hooks/hooks.json`, `hooks/register.ts` and `types/index.d.ts` with a `session.start` hook that reads `project-config.md`, runs the signature checks through `$.process.run` when facts are missing, and stores the routing facts in `$.state`; verify with `claude plugin validate plugins/drupal-migrate` and `tsc -p plugins/drupal-migrate`.
- [ ] 5.2 Add the `skill.prompt` hook that appends `variants/<source>.md` to a restructured skill's body, and verify with a `*.test.ts` run by `claude plugin test` that the served text equals body plus the one variant file for each of `wordpress`, `drupal7`, `drupal8+`.
- [ ] 5.3 Add the `tool.call` hook on `Skill` that denies a Drupal-only skill when `source_tech` is not Drupal, with the refusal message from group 2, and verify with a test.
- [ ] 5.4 Document the mod in `plugins/drupal-migrate/README.md` (what it does, Claude Code only, checked build, how to disable in `/plugin`), and verify the documented disable step leaves the file-based variant path working.

## 6. Classifier integration (dormant until enabled)

- [ ] 6.1 Add the optional `Classifier` section from design D5 to `references/project-config.template.md`, and verify every field the skills read is named in the template with its default behaviour when absent.
- [ ] 6.2 Create `plugins/drupal-migrate/scripts/classify.sh` (curl 7.76+, reads `TYPESAFE_API_KEY`, takes a JSON request on stdin, retries 429/529 with backoff, exits non-zero on failure) and verify it against the API with a one-question request when a key is available, and against a local mock otherwise.
- [ ] 6.3 Add the classifier client to the hooks module (`$.http.fetch`, same request shape as the script, option-order randomisation, confidence routing, `security` hint never accepted as disposition), and verify with tests that each routing scenario in `migrate-classifier-routing` maps to the expected path.
- [ ] 6.4 Add the classifier step to `drupal-migrate-codebase-scan` (choice over `replicate`, `triage`, `do_not_port`, `other` plus a security yes/no hint), gated on enabled, key present and `data_processing_approved`, and verify the skill reads unchanged when the section is absent.
- [ ] 6.5 Add the classifier step to `drupal-migrate-scan-destination` (choice over destination fields plus `none`), gated the same way, and verify.
- [ ] 6.6 Add the classifier step to `drupal-migrate-verify-content` (score 1 to 5 per page pair on stripped main content, pass level and confidence threshold from config), gated the same way, and verify.
- [ ] 6.7 Add the per-run classifier report block (items classified, accepted, routed to LLM, fallbacks with reason, input tokens, model id, non-English note) to the three skills, and verify the block appears only when the classifier ran.
- [ ] 6.8 Implement the `measure` flag (both paths on every item, per-item agreement table in the report, only the LLM result written to the docs), and verify with a test that the migration docs are unchanged by a measurement run.

## 7. Integration and release

- [ ] 7.1 Run the full as-is workflow through the analyst agent on a local Drupal 8+ fixture and on a WordPress fixture description, and verify each run loads only the matching variants and the roadmap block carries the routing facts.
- [ ] 7.2 Bump `version` in `plugins/drupal-migrate/.claude-plugin/plugin.json`, update `plugins/drupal-migrate/README.md` (variants, mod, classifier section) and `CHANGELOG.md`, and verify the changelog entry sits under today's date with the project's categories.

## Workflow follow-up

- Run the classifier measurement on one Italian and one English completed migration once the data-processing agreement is recorded; review the agreement table before setting default thresholds in the template.
- Archive the change after review.
