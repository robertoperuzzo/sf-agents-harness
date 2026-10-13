# Spec Delta

## Purpose

Establishes the migration source's routing facts once per run and serves each skill only the query variant and the skills that apply to that source, so no instruction text for another source is loaded and no Drupal query runs against a non-Drupal source.

## ADDED Requirements

### Requirement: Routing facts are established once per run

The plugin SHALL establish the routing facts `source_tech`, `topology`, `delivery`, `db_access_method` and, for a Drupal source, `source_version` once per run, from `project-config.md` when it declares them and from the detection commands otherwise, and SHALL make them available to every later skill without re-detection.

#### Scenario: Project config declares the source

- **WHEN** `.agents/references/migrate/project-config.md` declares the source technology, topology, delivery and DB access method
- **THEN** the routing facts are taken from the file, the detection commands are not run, and the run reports the facts as "from project-config"

#### Scenario: Project config is absent or silent

- **WHEN** `project-config.md` is missing or does not declare a routing fact
- **THEN** the missing fact is detected from file and database signatures, and the run reports the fact as "detected", with the evidence

#### Scenario: Later skill consumes the facts

- **WHEN** any Phase 1 or Phase 2 skill runs after the facts are established
- **THEN** the skill uses the established facts and does not run its own detection

### Requirement: Source cannot be identified

The plugin SHALL stop and ask the user to confirm the source system when neither `project-config.md` nor the signatures identify it, and SHALL NOT default to Drupal or to drush.

#### Scenario: No known signature matches

- **WHEN** the codebase and the database match no WordPress, Drupal 7 or Drupal 8+ signature
- **THEN** the run ends with an inputs-needed block naming what was checked, and no source query is issued

### Requirement: A skill loads only the matching query variant

Each skill whose queries differ by source SHALL keep a source-independent body and SHALL load exactly one variant block, selected by the routing facts, before it issues a query.

#### Scenario: WordPress source runs content inventory

- **WHEN** `source_tech` is `wordpress` and `drupal-migrate-content-inventory` runs
- **THEN** the WordPress variant is loaded, the Drupal variants are not loaded, and every query groups `{prefix}posts`

#### Scenario: Drupal 7 source runs a bundle skill

- **WHEN** `source_version` is `drupal7` and a bundle skill such as `drupal-migrate-count-instances` runs
- **THEN** the Drupal 7 variant is loaded with its table and column names, and the Drupal 8+ variant is not loaded

#### Scenario: Variant is missing for the established source

- **WHEN** a skill has no variant for the established `source_tech`
- **THEN** the skill reports that the source is unsupported for this step and stops, without running a query from another variant

### Requirement: Drupal-only skills refuse a non-Drupal source

Skills that only apply to a Drupal source SHALL refuse to run when `source_tech` is `wordpress` or `other`, and SHALL name the skill that covers the same concern for that source when one exists.

#### Scenario: Paragraph skill invoked on WordPress

- **WHEN** `source_tech` is `wordpress` and `drupal-migrate-parent-context` is invoked
- **THEN** the invocation is refused with a message stating the skill is Drupal-only, and no query runs

### Requirement: DB-only delivery skips codebase analysis

The plugin SHALL skip `drupal-migrate-codebase-scan` when `delivery` is `db-only`, SHALL record the skip in the as-is documentation, and SHALL NOT infer a custom-code inventory from the database alone.

#### Scenario: DB-only as-is run

- **WHEN** `delivery` is `db-only` and a full as-is analysis runs
- **THEN** the platform document states "source delivered as DB-only; custom-code disposition limited to extension names visible in the database" and the codebase scan is not attempted

### Requirement: Entity type is resolved from the source database

For a Drupal source, the plugin SHALL resolve a bundle's entity type by querying the source database's field or bundle configuration, SHALL honour an explicit mapping in `project-config.md` first, and SHALL NOT infer the entity type from words in the bundle name.

#### Scenario: Bundle exists in the source

- **WHEN** a bundle name is given without an entity type and the source is Drupal 8+
- **THEN** the entity type is read from the configuration entries for that bundle and reported with the query used

#### Scenario: Bundle exists under two entity types

- **WHEN** the lookup returns more than one entity type for the name
- **THEN** the run stops and asks which entity type is meant, listing the candidates

#### Scenario: Bundle does not exist

- **WHEN** the lookup returns no entity type
- **THEN** the run reports that the bundle does not exist in the source and suggests verifying the name

### Requirement: Variant selection is host-independent

Variant selection SHALL work in every host that can read the plugin's skill files, and a host-specific mechanism that pre-selects the variant (such as a Claude Code mod) SHALL produce the same loaded content as the file-based selection.

#### Scenario: Plugin used outside Claude Code

- **WHEN** a skill runs in a host without the plugin's hooks module
- **THEN** the skill still loads the variant matching the routing facts by reading the variant file

#### Scenario: Plugin used with the hooks module

- **WHEN** the hooks module is loaded and serves the variant at skill expansion
- **THEN** the text the model reads is the same body plus the same single variant as the file-based path produces
