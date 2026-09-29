# Migration Project Configuration — <PROJECT NAME>

This file provides project-specific values for the generic `drupal-migrate-*` skills.
The skills read this file to adapt their behavior to your project.

**Install location**: copy this template to `.agents/references/migrate/project-config.md`
in your project and fill in the real values. Delete sections that do not apply, but
keep the headings the skills look for (Database Connection, Live URL Resolution,
URL Scope Support Table, Scope Exclusions).

> **Living codebase**: migration modules evolve (plugins, derivers, migrations get
> added/renamed). Do **not** enumerate them here — point to the folders where they
> live and let the skill explore for the current state.

---

## Source System Overview

<!-- Describe the source so drupal-migrate-detect-source can confirm rather than guess.
     The source may be WordPress, Drupal 7, Drupal 8+, or another CMS. -->

| Property             | Value                                                        |
| -------------------- | ------------------------------------------------------------ |
| Source technology    | `<wordpress / drupal7 / drupal8+ / other>`                   |
| Topology             | `<single-site / multisite (N registered sites)>`             |
| Delivery             | `<full codebase + DB / DB-only / codebase-only>`             |
| DB access method     | `<drush sql:query / ddev wp db query / wp db query / mysql>` |
| Source codebase path | `<path, or "not delivered (DB-only)">`                       |
| Target stack         | `<e.g. Drupal 11>`                                           |

Example:

> The source is the old `<SITE>` running **WordPress 6.4 multisite** (345 subsites).
> Full codebase + DB delivered; the DB is queried via `ddev wp db query` (table prefix
> `<prefix>`, subsites `<prefix>{N}_`). The migration targets a new **Drupal 11** site.
> Source dumps live in `<path/to/seed>`; use the most recent dated file.

If the source is **Drupal**, also note the major version (or let
`drupal-migrate-detect-version` detect it). If there is **more than one** source
database, list each key/prefix and say which is primary.

---

## Database Connection

Consumed by `drupal-migrate-db-discover` and every skill that queries the source DB.
**The access method depends on the source technology** (see Source System Overview):

- **Drupal source** — `drush sql:query --database=<key>`; the DB is configured in
  `settings.php` (sections below).
- **WordPress source** — `ddev wp db query` / `wp db query`; the identifier is the
  `$table_prefix` from `wp-config.php`, not a `$databases` key. Fill the WordPress note
  below and skip the settings.php sub-sections.
- **Other CMS / raw dump** — a read-only `mysql`/`mariadb` client against the imported
  schema. Document the exact read-only command.

### WordPress source (delete if the source is Drupal)

| Parameter              | Value                         |
| ---------------------- | ----------------------------- |
| Table prefix (main)    | `<prefix>`                    |
| Subsite prefix pattern | `<prefix>{N}_`                |
| Query command          | `ddev wp db query '<SELECT>'` |

### Configuration in settings.php (Drupal source)

<!-- Where the source DB(s) are configured, and any feature flag that enables them. -->

```php
// Example: behind a feature flag
if (getenv('MIGRATE_ENABLE') === '1') {
  $databases['<DB_KEY>']['default'] = [ /* ... */ ];
}
```

### Connection details

| Parameter              | Value                 |
| ---------------------- | --------------------- |
| Database key (primary) | `<DB_KEY>`            |
| Host                   | `<DB_HOST>`           |
| Drush option           | `--database=<DB_KEY>` |

### Connection command

<!-- The exact command the skills must use to run a query. Replace the runner with
     your project's container/drush invocation. NEVER use the `mysql` client directly. -->

```bash
<DRUSH_RUNNER> "drush sql:query --database=<DB_KEY> 'SELECT 1'"
```

### Enabling migration mode (optional)

<!-- Steps to start the source DB container / set the feature flag, if any. -->

---

## Issue Tracker (optional)

<!-- Used by skills that read/write issues. -->

- **Tool**: `glab` (GitLab) / `gh` (GitHub)
- **Repository flag**: `<-R group/project  or  --repo owner/name>`
- **Auth check**: `<glab auth status / gh auth status>`

---

## Live URL Resolution

Used by `drupal-migrate-resolve-examples` to turn source node IDs into public URLs.

Pick the strategy your project uses and delete the others:

- **`path_alias`** (default, no config needed): the skill resolves `/node/{nid}` via the
  source `path_alias` table. Omit this section to use it.
- **`endpoint`**: the site exposes a JSON map of path → `entity_type/uuid`. Document:
  - **Base URL**: `<https://www.example.com>`
  - **Endpoint URL**: `<https://www.example.com/prod/uuid/it>`
  - **Response format**: keys are relative paths, values are `entity_type/uuid`.
  - **Steps**: get the node `uuid` from the source DB, match it in the JSON, prefix the
    base URL.

---

## Content Verification

Consumed by `drupal-migrate-verify-content`. Without these values the non-interactive
analyst cannot verify migrated pages.

| Setting                | Value                                                                     |
| ---------------------- | ------------------------------------------------------------------------- |
| Source base URL (base) | `<https://www.example.com>`                                               |
| Language URL rule      | `<separate domain / path prefix>`                                         |
| Other-language bases   | `<lang: https://en.example.com>` or `<lang: https://www.example.com/en>`  |
| Destination base URL   | `<https://new-site.loc>` or the discovery command that prints it          |
| Internal HTTP host     | `<http://web-container>` (destination reachable from the tools container) |

---

## URL Scope Support Table (optional)

Document only if your migration scope is driven by a support/lookup table.

- **Table name**: `<TABLE>`
- **Where the data lives / how it is built**: `<command or import process>`
- **Columns**: `<col1, col2, ...>`
- **Status semantics**: e.g. rows marked `<DO_NOT_MIGRATE_VALUE>` are skipped; pages with
  that status are expected to return `<410 Gone / redirect>`.
- **Scope-check query**:
  ```sql
  SELECT <status_col>, <action_col>, url, title
  FROM <TABLE>
  WHERE node_id = {nid};
  ```

---

## Source Database Entity Tables

Default Drupal 8+ table/column mapping lives in `entity-type-context.md` and needs no
copying. Override here only if your source is **Drupal 7** or uses non-standard tables.

---

## Migration Infrastructure — Where To Look

| What                               | Where                           | How to explore              |
| ---------------------------------- | ------------------------------- | --------------------------- |
| Module overview, patterns          | `<module>/README.md`            | read first                  |
| Migration execution order          | `<order file>`                  | authoritative run order     |
| Migration YAMLs                    | `<migrations dir>`              | per-entity migrations       |
| Source/process/destination plugins | `<src/Plugin/migrate/...>`      | read class `id` annotations |
| Run commands                       | `<Makefile / RoboFile / drush>` | how migrations are executed |

---

## Migration Patterns (project conventions, optional)

<!-- Numbered list of project conventions: multilingual ordering, file dedup,
     scope filtering, stub langcode overrides, config split, etc. -->

---

## Scope Exclusions (optional)

Fields/content explicitly excluded from migration by project decision.

| Field          | Decision                        | Reference     |
| -------------- | ------------------------------- | ------------- |
| `<field_name>` | **Do not migrate** — `<reason>` | `<issue ref>` |

---

## Base Content Language

The source site's base/default content `langcode` (e.g. `en`, `it`, `de`).
Skills use it to resolve path aliases and base-language content. Defaults to
`en` if unset.

- **Base content langcode**: `<langcode>`

---

## Output Language

- **Issue body**: `<language>`
- **Skill output / interactions**: `<language>`
