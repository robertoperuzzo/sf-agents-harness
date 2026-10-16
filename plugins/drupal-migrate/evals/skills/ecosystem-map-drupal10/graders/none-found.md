---
type: regex
target:
  source: file
  path: doc/Migrate/as-is/ecosystem.md
flags: i
pattern: '\b(no|none|zero|not? [a-z]+ )\b[^\n]{0,80}(integration|external system|connector)|(integration|external system)s?[^\n]{0,80}\b(none|not found|no evidence|absent)'
---

The document states that no external integration was found: the fixture has none, and a DB-only delivery offers only stored config as evidence.
