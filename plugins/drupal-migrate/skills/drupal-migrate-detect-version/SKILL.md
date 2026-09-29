---
name: drupal-migrate-detect-version
description: Detect the Drupal version of the source migration database (Drupal 7, 8, 9, or 10). Use after discovering the database connection with drupal-migrate-db-discover. Checks for version-specific table signatures.
---

# Detect Source Drupal Version

Determine whether the source migration database is Drupal 7 or Drupal 8+ by checking for version-specific table signatures.

> This is the **Drupal-source sub-step** of `drupal-migrate-detect-source`. Run it only
> once that gate has established the source technology is Drupal. For a WordPress or
> other-CMS source it does not apply.

---

## Prerequisites

- Source database connection verified (`drupal-migrate-db-discover`)
- You have the `db_key` / `drush_option` from the discovery step

---

## Steps

### Step 1 — Read project configuration

Read `.agents/references/migrate/project-config.md` for the source database key
and any schema name. Use the `drush_option` from `drupal-migrate-db-discover` output (e.g.
`--database={db_key}`). Do not hardcode a project's db key here.

### Step 2 — Query for version-specific tables

The signature is the field-metadata storage mechanism: D7 keeps field configs in the
`field_config_instance` table; D8+ stores them PHP-serialized in the `config` table.
Run against the source database:

```sql
SELECT IF(
  EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'field_config_instance'),
  'drupal7',
  IF(EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'config'), 'drupal8+', 'unknown')
) AS source_version;
```

Execute via (substitute the `{drush_option}` from Step 1):

```bash
docker compose run --rm <tools-container> ash -c "drush sql:query {drush_option} \"SELECT IF(EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'field_config_instance'), 'drupal7', IF(EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'config'), 'drupal8+', 'unknown')) AS source_version;\""
```

### Step 3 — Determine specific version (optional, Drupal 8+ only)

If the source is Drupal 8+, you can further identify the major version:

```sql
SELECT data FROM config WHERE name = 'core.extension' LIMIT 1;
```

The `core_version_requirement` in the serialized data indicates D8 (`^8`), D9 (`^9`), or D10 (`^10`).

Alternatively, check the `system` config:

```sql
SELECT data FROM config WHERE name = 'system.site' LIMIT 1;
```

### Step 4 — Report results

Output:

```
Source Drupal version: {version}
- Drupal 7: field metadata in the field_config_instance table
- Drupal 8+: field metadata PHP-serialized in the config table (major version from core.extension)
```

If `unknown`, warn:

> "⚠️ Could not detect Drupal version — neither `field_config_instance` (D7) nor `config` (D8+) tables were found. This may not be a standard Drupal database."

Then **STOP** and ask the user to confirm the source system.

---

## Output

- **source_version**: `drupal7`, `drupal8+`, or `unknown`
- **field_query_strategy**: `field_config_instance` (D7) or `config_table` (D8+)

---

## Guardrails

- This skill only detects the version — it does not query field data
- If version is unknown, stop and ask the user for clarification
- Use `DATABASE()` function instead of hard-coding the schema name when possible
