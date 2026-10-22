# Spec Delta

## Purpose

Synthetic source databases with a known ground truth, so the `drupal-migrate` plugin can be exercised and graded without a client database and without hand-measured expected values.

## ADDED Requirements

### Requirement: One spec produces both dump and ground truth

Each fixture SHALL be generated from a single declarative spec by one generator run that writes the SQL dump and the `expected.json` ground truth together, so the two can never disagree.

#### Scenario: Regenerating a fixture is deterministic

- **WHEN** the generator runs twice on the same spec
- **THEN** both runs produce byte-identical dump and `expected.json` files

#### Scenario: Spec change propagates to both outputs

- **WHEN** the spec for a fixture adds one published node to a bundle and the generator runs
- **THEN** the dump contains the new row and `expected.json` reports the bundle count incremented by one

### Requirement: Three source technologies covered

The fixture set SHALL include at least one Drupal 8+ source, one Drupal 7 source and one WordPress single-site source, each detectable by the table signatures the `drupal-migrate-detect-source` skill documents.

#### Scenario: Drupal 8+ fixture signature

- **WHEN** the Drupal 8+ fixture is loaded
- **THEN** the schema contains `config` and `key_value` tables and no `field_config_instance` table

#### Scenario: Drupal 7 fixture signature

- **WHEN** the Drupal 7 fixture is loaded
- **THEN** the schema contains `field_config_instance` and `node` with a `type` column

#### Scenario: WordPress fixture signature

- **WHEN** the WordPress fixture is loaded
- **THEN** the schema contains `{prefix}posts`, `{prefix}options` and `{prefix}postmeta`, and no `{prefix}blogs` table

### Requirement: Fixtures contain the traps the skills are designed to avoid

Every Drupal fixture SHALL hold multiple revisions per entity, at least one orphaned paragraph and a field at 0% population. The Drupal 8+ fixture SHALL in addition hold language variants per entity, at least one paragraph bundle that is a container of another, and fields at partial and 100% population.

#### Scenario: Revision inflation is measurable

- **WHEN** a node bundle in the fixture has N distinct entities
- **THEN** `COUNT(*)` on its field-data table returns a value greater than N and `expected.json` records N

#### Scenario: Orphan paragraphs are present

- **WHEN** a paragraph bundle in the fixture is queried for parents
- **THEN** at least one instance has no referencing parent and `expected.json` records separate total and active counts

#### Scenario: Empty field present

- **WHEN** the fields of a fixture bundle are measured
- **THEN** at least one field has zero populated rows and `expected.json` records it at 0%

### Requirement: Ground truth is complete for every graded value

`expected.json` SHALL hold every value an eval grader compares against: per bundle the distinct and active counts, field list, population per field, parent bundles, child bundles; per source the technology, topology, delivery, table prefix or db key, Drupal major version, module or plugin inventory with activation state, content-type volumes and language coverage.

#### Scenario: Grader finds its value

- **WHEN** an eval case grades the count of a fixture bundle
- **THEN** the value is read from `expected.json` and not written by hand in the grader

### Requirement: Fixture lifecycle through one script

A single `fixture` script SHALL provide `generate`, `up`, `down`, `status` and `query` commands. `up` starts MariaDB in Docker and imports the dump of the named fixture; `query` runs one SQL statement through the read-only runner; `down` removes the container.

#### Scenario: Start and query

- **WHEN** `fixture up drupal10` completes and `fixture query drupal10 "SELECT 1"` runs
- **THEN** the query returns `1` with exit status 0

#### Scenario: Start when Docker is absent

- **WHEN** `fixture up` runs on a host where `docker` is not on `PATH`
- **THEN** it exits non-zero with a message naming Docker as the missing dependency

#### Scenario: Idempotent up

- **WHEN** `fixture up drupal10` runs while the fixture is already running
- **THEN** it exits 0 and reports the fixture as already running without re-importing

### Requirement: Query runner is read-only

The query runner handed to the plugin SHALL connect as a database user with SELECT-only privileges and SHALL refuse, before sending it, any statement whose first keyword is not `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN` or `WITH`.

#### Scenario: Write statement refused by the runner

- **WHEN** the runner receives `UPDATE node_field_data SET status = 0`
- **THEN** it exits non-zero with a message stating the statement was refused as a write, and the database is unchanged

#### Scenario: Write statement refused by the database

- **WHEN** a `DELETE` reaches the database through the runner's credentials by any other path
- **THEN** the database rejects it with a privilege error

### Requirement: Fixture project configuration

Each fixture SHALL ship a `project-config.md` that follows the plugin's template headings and declares the fixture's source technology, topology, delivery, table prefix or db key and the read-only runner command, so a case can install it at `.agents/references/migrate/project-config.md` in the eval workspace.

#### Scenario: Config declares the runner

- **WHEN** a skill reads the fixture's `project-config.md` Database Connection section
- **THEN** it finds the exact `fixture query <name> '<SELECT>'` command and no `drush` or `mysql` invocation

### Requirement: Fixtures hold no real data

Fixture content SHALL be synthetic: no value copied from a client database, no personal data, and all host names under a reserved documentation domain.

#### Scenario: Domain check

- **WHEN** the fixture dumps are scanned for URLs
- **THEN** every host ends in `.example` or `example.com`

### Requirement: Runner works inside the eval sandbox

The query runner installed in an eval workspace SHALL need no network access and no Docker access from the agent process: requests and results travel through files under the workspace, and a host-side process outside the sandbox executes the statements through the read-only path.

#### Scenario: Query from a sandboxed run

- **WHEN** an eval run's agent executes the workspace runner with a `SELECT` while the host process is serving
- **THEN** the result rows are printed in the run and no Docker or TCP connection is attempted by the agent process

#### Scenario: Host process absent

- **WHEN** the workspace runner is executed and no host process is serving
- **THEN** it exits non-zero within its timeout with a message naming the `serve` command
