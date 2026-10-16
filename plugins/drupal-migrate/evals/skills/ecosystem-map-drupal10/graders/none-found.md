---
type: regex
target:
  source: file
  path: doc/Migrate/as-is/ecosystem.md
flags: i
pattern: '(no|none|zero|not)\b[^\n]{0,80}(integration|external system|connector|analytics|crm|newsletter|payment|sso)|(integration|external system)s?[^\n]{0,80}\b(none|not found|no evidence|absent|were found: 0|found: 0)'
---

The document states the absence of integrations in its own words (none found, no
analytics, no external system, integrations: none). The fixture has no integration and a
DB-only delivery offers only stored config as evidence, so a correct document is one
that says so instead of listing systems.
