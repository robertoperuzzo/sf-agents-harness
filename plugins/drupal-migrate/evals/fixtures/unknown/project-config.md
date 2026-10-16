# Migration Project Configuration — legacy source

This file provides project-specific values for the generic `drupal-migrate-*` skills.
It is installed at `.agents/references/migrate/project-config.md` in the analysis
workspace. Only a database dump of the old site was handed over; the technology of
that site has not been established yet.

---

## Source System Overview

| Property             | Value                                              |
| -------------------- | -------------------------------------------------- |
| Source technology    | `<to be detected>`                                 |
| Topology             | `<to be detected>`                                 |
| Delivery             | `DB-only`                                          |
| DB access method     | read-only fixture runner (`fixture query unknown`) |
| Source codebase path | not delivered (DB-only)                            |
| Target stack         | Drupal 11                                          |

---

## Database Connection

The dump is imported into a database container; the only way to read it is the
read-only runner below, which connects as a database user that holds `SELECT` only.

### Connection command

```bash
fixture query unknown 'SELECT 1'
```

---

## Base Content Language

- **Base content langcode**: `en`

---

## Output Language

- **Issue body**: English
- **Skill output / interactions**: English
