# Proposal

## Why

The `drupal-migrate` plugin lets the agent LLM decide, by reading prose, which query variant and which skill apply to a source (WordPress, Drupal 7, Drupal 8+, DB-only). Every multi-source skill carries all its branches, so each run loads instruction text it never uses, and the same decision is re-read on every invocation. The analysis in `plugins/drupal-migrate/docs/jev-classifier-routing-analysis.md` shows two distinct problems: routing facts that are already deterministic enums are still handled by the LLM, and the high-volume judgment steps (custom-code disposition, field mapping, page-fidelity verification) spend most of a migration's tokens on repetitive classifications that a calibrated classifier could pre-sort.

## What Changes

- Routing facts (`source_tech`, `topology`, `delivery`, `db_access_method`, `source_version`) are established once per run from `project-config.md` or the detection commands, and every later skill consumes them instead of re-deriving them from prose.
- Each source-dependent skill serves only the query variant that matches the established source. The WordPress, Drupal 7 and Drupal 8+ blocks move out of the main `SKILL.md` body into per-variant files that the skill loads by routing fact. A Claude Code mod with a `skill.prompt` hook can serve the same variant selection without the file read, as an optional optimisation.
- Drupal-only bundle skills refuse to run against a non-Drupal source and say so, instead of attempting a Drupal query.
- Entity-type resolution for a bundle uses a source-database lookup, with the name heuristic removed.
- A new optional classifier integration lets `drupal-migrate-codebase-scan`, `drupal-migrate-scan-destination` and `drupal-migrate-verify-content` send batched, typed questions to an external classifier (Jev) and route each item by returned confidence: high confidence is accepted, low confidence goes to the existing LLM path. The integration is off unless `project-config.md` enables it and the API key is present, and it ships with a measurement procedure.
- The plugin gains a hooks module (mod) that holds the routing facts in session state, serves skill variants, and performs the classifier calls outside the model context when running in Claude Code. Non-Claude hosts keep the file-based variant selection and the Bash-based classifier call.

## Capabilities

### New Capabilities

- `migrate-source-routing`: Establishing the migration source's routing facts once per run and serving each skill only the query variant and the skills that apply to that source.
- `migrate-classifier-routing`: Optional confidence-routed classification of high-volume migration judgments through an external typed classifier, with LLM fallback, data-processing gating and measurement.

### Modified Capabilities

_(none; the plugin has no existing specs under `openspec/specs/`)_

## Impact

- `plugins/drupal-migrate/skills/*/SKILL.md`: the 7 skills that branch on Drupal 7 (5 with a "Drupal 7 differences" block, 2 with Drupal 7 step headings) and the 4 skills with WordPress/Drupal branches other than `detect-source` are restructured into a variant-free body plus `variants/<source>.md` files. Prose length per loaded skill drops; behaviour per source is unchanged.
- `plugins/drupal-migrate/agents/drupal-migration-analyst.agent.md`: the entity-type inference rule and the per-step `source_version` passing are replaced by references to the routing facts; the "perform inline if a skill is not loaded" rule no longer applies to a skill that refused to run.
- `plugins/drupal-migrate/skills/drupal-migrate-verify-content/SKILL.md` and the new classifier client: the classifier path fetches and strips page content outside the agent context, which does not exist in the skill today; JavaScript-rendered or authenticated pages stay on the LLM path.
- `plugins/drupal-migrate/references/project-config.template.md`: new optional `Classifier` section (enable flag, model id, confidence thresholds, allowed data classes).
- `plugins/drupal-migrate/hooks/`: new hooks module, new `.claude-plugin/plugin.json` fields for the mod. Claude Code only; mods do not run in the Copilot or OpenCode profiles. The module loads routing facts on the first `drupal-migrate-*` skill call, not in every session, and runs host commands only in the CLI.
- `.github/workflows/`: a new step validating the plugin's hooks module; no workflow validates plugins today.
- New external dependency, optional: TypeSafe Jev API (`TYPESAFE_API_KEY`, `https://api.typesafe.ai/v1/systemone`). Sending source content to it requires a data-processing agreement; the capability spec makes that a precondition.
- `plugins/drupal-migrate/.claude-plugin/plugin.json`: version bump. `README.md` and `CHANGELOG.md` updated.
- No change to `SYSTEM.md` or `config/catalog.json` (plugins are not sparkdock-synced).
