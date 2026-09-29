---
name: drupal-migrate-verify-content
description: >-
  Verify migrated content by navigating source and destination website pages,
  comparing content through LLM reasoning, checking HTTP redirects, and
  validating translations. Use this skill whenever the user asks to "verify
  migration", "check migrated content", "compare source and destination pages",
  "verify redirects", or provides a source URL to validate after migration.
  Also trigger when the user mentions "migration QA", "migration acceptance",
  "content verification", "post-migration check", or wants to confirm that
  content from the old site was correctly imported. This includes
  checking multilingual translations, verifying 301 redirect chains, and
  confirming 410 Gone responses for non-migrated pages.
---

# Migration Content Verification

You are a migration QA agent. Your job is to verify that content has been correctly
migrated from the old site to the new Drupal site by **navigating both sites and comparing
what you see**, much like a human reviewer would. You use browser automation to visit
pages on both sites, then apply judgment to decide whether content was faithfully
preserved. You also verify HTTP redirects and translations.

This skill is **project-agnostic**: all project-specific values come from the project
configuration file. Read it first.

---

## Phase -1 — Load project configuration

Read **`.agents/references/migrate/project-config.md`** before anything else. Resolve
these variables from it; if the file is missing or a value is absent, ask the user and
do not guess:

| Variable                                  | Source section in project-config.md             | Example                                                                       |
| ----------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------- |
| `{drush_runner}`                          | Database Connection → Connection command        | `docker compose run --rm <tools> ash -c`                                      |
| `{migrate_db_key}`                        | Database Connection → Database key              | `<source_db_key>`                                                             |
| `{source_bases}`                          | Source System / Live URL Resolution             | `https://www.example.com` (+ secondary-lang domain/prefix)                    |
| `{dest_base_url}`                         | ask, or run the project's URL-discovery command | `https://<new-site>.loc`                                                      |
| `{internal_http_host}`                    | Database Connection / infra notes               | `http://<web-container>`                                                      |
| `{languages}` + URL rule                  | Source System / Output Language                 | base lang + secondary lang (path prefix or separate domain)                   |
| `{scope_table}` + columns + status values | URL Scope Support Table                         | table `<scope_table>`; `<action_col>` ∈ {migrate, no-migrate}; `<status_col>` |
| `{url_map_table}` _(optional)_            | Migration Infrastructure                        | `<source_url_map>`                                                            |

If the project defines **no scope/support table**, skip Phase 0's table lookup and instead
derive intent directly: treat a provided URL as expected-to-exist unless the user says it
should be gone, and confirm redirects/aliases against the live destination.

---

## Prerequisites

1. **Old site reachable**: every base in `{source_bases}` responds.
2. **New site reachable**: `{dest_base_url}` resolved (discovery command or user).
3. **Source DB reachable** (only if `{scope_table}`/`{url_map_table}` are used):
   ```bash
   {drush_runner} "drush sql:query --database={migrate_db_key} 'SELECT 1'"
   ```
4. **playwright-cli available**: `command -v playwright-cli`; fallback `npx -y @playwright/cli`.

If any prerequisite fails, inform the user and stop. Do not work around missing infra.

---

## Input

One or more **source URLs** from the old site, or an issue reference whose body lists
example URLs. Accepted: a single URL, a list of URLs, or an issue id (use `glab`/`gh` to
fetch the body and extract URLs matching the `{source_bases}`).

---

## Workflow Overview

```
Phase 0: Resolve intent     -- What SHOULD have happened to this URL?
Phase 1: Redirect checks    -- Do all old paths land correctly?
Phase 2: Base-lang compare  -- Is the base-language content preserved?
Phase 3: Translations       -- Are other-language versions correct?
Phase 4: Non-migrate check  -- Do out-of-scope URLs return Gone?
Phase 5: Produce report     -- Structured verification output
```

---

## Phase 0 — Resolve Intent

If `{scope_table}` is defined, query it to learn the migration plan for this URL. Strip a
base in `{source_bases}` from the URL to get the relative path, then:

```bash
{drush_runner} "drush sql:query --database={migrate_db_key} \"SELECT <action_col>, <status_col>, node_id, content_type, final_url, langcode FROM {scope_table} WHERE url LIKE '%{relative_path}%' AND langcode='<base_lang>' LIMIT 5\""
```

Interpret using the status values from project-config.md:

| `<action_col>` value                  | Meaning                      | Next phases       |
| ------------------------------------- | ---------------------------- | ----------------- |
| migrate value (e.g. `Migrare`)        | should have been migrated    | Phases 1, 2, 3, 5 |
| no-migrate value (e.g. `Non Migrare`) | should NOT exist on new site | Phase 4, then 5   |

No row found → tell the user the URL may be out of scope; ask how to proceed.

Also query the other-language row(s) to know which translations to expect in Phase 3.

---

## Phase 1 — Redirect Verification (migrate only)

### 1a. Resolve the destination entity

If `{url_map_table}` is defined:

```bash
{drush_runner} "drush sql:query --database={migrate_db_key} \"SELECT destination_entity_id, destination_entity_type, destination_url FROM {url_map_table} WHERE source_url LIKE '%{source_path}%' LIMIT 5\""
```

Otherwise resolve via the `final_url`/`node_id` from Phase 0, or ask the user. Result is
the destination node ID.

### 1b. Destination URL alias

```bash
{drush_runner} "drush path:lookup /node/{nid} --language=<base_lang>"
```

### 1c. Collect redirects for this entity

```bash
{drush_runner} "drush sql:query \"SELECT redirect_source__path, status_code, language FROM redirect WHERE redirect_redirect__uri = 'internal:/node/{nid}' ORDER BY language, redirect_source__path\""
```

> If the query errors with an unknown `redirect` table, the Redirect module is not
> installed on the destination. Skip redirect collection, record redirects as
> `N/A — Redirect module absent`, and continue with the remaining phases.

### 1d. HTTP-check each redirect path

For each redirect path plus the original source path, check the response on the **new
site** from inside the container network (avoids SSL/DNS issues):

```bash
{drush_runner} "curl -sI -o /dev/null -w '%{http_code} %{redirect_url}' {internal_http_host}/{redirect_path}"
```

Expected: preserved alias → `200`; redirected path → `301`→`200` at target. `404` =
**FAIL** (missing redirect). `301` to wrong target = **FAIL**. Record path, expected,
actual, target, PASS/FAIL.

---

## Phase 2 — Base-Language Content Verification (migrate only)

LLM comparison. Navigate both pages and compare substance, not structure.

### 2a. Source page (old site)

```bash
playwright-cli open {source_base}/{source_path}
playwright-cli snapshot --filename=.playwright-cli/verify-source-base.yaml
```

Note: page title (`<h1>`/main heading), body text (main content area; ignore nav/footer/
sidebar), images (alt text, content vs decorative), links (text + href), video embeds,
meta info (dates, categories).

### 2b. Destination page (new site)

```bash
playwright-cli goto {internal_http_host}/{destination_alias}
playwright-cli snapshot --filename=.playwright-cli/verify-dest-base.yaml
```

### 2c. Compare content

Semantic comparison. The old and new sites have different layouts, paragraph types, and
media handling. Focus on whether the **content substance** survived.

| Check         | What to look for             | PASS                                            | WARN                                       | FAIL                            |
| ------------- | ---------------------------- | ----------------------------------------------- | ------------------------------------------ | ------------------------------- |
| **Title**     | same page title/heading      | exact/near-exact                                | minor case/punctuation                     | missing or completely different |
| **Body text** | text preserved               | all meaningful text present                     | minor decorative omission                  | significant blocks missing      |
| **Images**    | content images accounted for | all present (alt/visual)                        | replaced by placeholder (flag, don't fail) | missing with no placeholder     |
| **Links**     | links preserved              | present, correct target (URL format may differ) | target changed but equivalent              | missing/broken                  |
| **Videos**    | embeds preserved             | present                                         | referenced differently but accessible      | completely missing              |
| **Documents** | downloadable files linked    | present                                         | different path, file accessible            | missing                         |

Comparison guidelines:

- **Layout differences are expected and OK.** Source-to-destination paragraph-type
  restructuring is intentional. Confirm the project's specific transformations against the
  "Migration Patterns" section of project-config.md when present.
- **Documented HTML tag transformations are intentional** — not content loss. (project-config.md may list them, e.g. `<u>`→`<em>`.)
- **Placeholder images → WARN, not FAIL** when the project uses placeholders for broken
  source files.
- **Content may be split differently.** One source paragraph → several destination
  paragraphs is fine if all text is present.
- **Minor whitespace/entity/formatting differences are OK.**

### 2d. Close browser before Phase 3

```bash
playwright-cli close
```

---

## Phase 3 — Translation Verification

For each non-base language in `{languages}`:

### 3a. Is a translation expected?

From Phase 0 you know whether an other-language row exists in `{scope_table}` (or, with no
table, whether the user expects a translation). If not expected, confirm none was created:

```bash
{drush_runner} "drush sql:query \"SELECT langcode FROM node_field_data WHERE nid={dest_nid} AND langcode='<lang>'\""
```

- not expected AND absent → **PASS**
- not expected BUT present → **WARN** (investigate)
- expected → continue

### 3b. Source URL for the language

Build from the language's URL rule in project-config.md — a separate domain
(`https://www.example.edu/{path}`) or a prefix (`{source_base}/en/{path}`).

### 3c. Destination URL for the language

```bash
{drush_runner} "drush path:lookup /node/{dest_nid} --language=<lang>"
```

### 3d. Navigate + compare

Same process as Phase 2, adapted to the language:

```bash
playwright-cli open {lang_source_url}
playwright-cli snapshot --filename=.playwright-cli/verify-source-<lang>.yaml
playwright-cli goto {internal_http_host}{lang_destination_alias}
playwright-cli snapshot --filename=.playwright-cli/verify-dest-<lang>.yaml
```

Apply the Phase 2 checklist.

### 3e. Language-specific redirects

```bash
{drush_runner} "drush sql:query \"SELECT redirect_source__path, status_code FROM redirect WHERE redirect_redirect__uri = 'internal:/node/{dest_nid}' AND language = '<lang>'\""
```

HTTP-check each like Phase 1d. If the `redirect` table is absent (see Phase 1c), skip this step.

---

## Phase 4 — Non-Migrate Verification

For URLs marked with the no-migrate value:

### 4a. Expected status

The `<status_col>` in `{scope_table}` says what HTTP code the old URL should return on the
new site (typically `410`).

### 4b. HTTP-check on the new site

```bash
{drush_runner} "curl -sI -o /dev/null -w '%{http_code}' {internal_http_host}/{source_path}"
```

| Actual | Expected | Verdict                                      |
| ------ | -------- | -------------------------------------------- |
| 410    | 410      | **PASS** — correctly Gone                    |
| 404    | 410      | **FAIL** — should be 410 (map entry missing) |
| 200    | 410      | **FAIL** — page exists but shouldn't         |
| 301    | 410      | **FAIL** — redirects instead of Gone         |

---

## Phase 5 — Produce Report

### Single URL Report

```markdown
## Migration Verification: {source_url}

**Source node ID:** {node_id}
**Destination:** /node/{dest_nid} ({content_type})
**Action:** {action_value}
**Date:** {current_date}

### Redirects ({base_lang})

| Old Path | Expected | Actual | Target | Status |
| -------- | -------- | ------ | ------ | ------ |

### Content ({base_lang})

| Check | Status | Notes |
| ----- | ------ | ----- |

### Translations

| Language | Check | Status | Notes |
| -------- | ----- | ------ | ----- |

### Overall: {PASS|WARN|FAIL} ({summary})
```

### Batch Report

Summary table first (one row per URL: redirects / base content / translations / overall),
then individual reports. Surface FAILs and WARNs prominently.

### Overall Verdict Logic

- **PASS**: all checks pass.
- **WARN**: critical checks pass, but placeholder images or minor notes — human review
  recommended.
- **FAIL**: any redirect 404s, significant content missing, or an expected translation
  absent.

---

## Batch Mode

1. Collect all URLs (from the issue body via `glab`/`gh`, or the user's list).
2. Process sequentially (one browser at a time).
3. Produce the batch summary at the end.
4. Highlight FAILs/WARNs so they are not buried.

---

## Error Handling

- **Old page 404/500**: "Source page not accessible" — skip content compare; redirects can
  still run.
- **New page 404**: likely **FAIL** (not migrated / alias missing). Report it.
- **No scope-table row**: tell the user the URL is out of scope; ask before manual check.
- **No URL-map entry**: try `final_url` from the scope table; else "No URL mapping found".
- **Browser timeout**: report and continue; do not auto-retry.
- **Multiple scope-table matches**: show them; ask which to verify.

---

## Guardrails

- **Read-only.** No DB writes, no entity saves, no redirect creation.
- **Resolve config first.** Never hardcode domains, DB keys, or table names — read them
  from project-config.md.
- **Never skip the intent check** when a scope table exists.
- **Close the browser** between URLs in batch mode.
- **Query via `{drush_runner}` + `drush sql:query`.** Never use the `mysql` client directly.
- **Internal HTTP checks via `{internal_http_host}`.** Old-site URLs via playwright-cli
  from the host.
- **Report honestly.** Ambiguous comparison → WARN, not a forced PASS/FAIL.
- **Do not fabricate content.** If a page is unreadable, say so.
