---
# Rendered by evals/scripts/render-cases.py from none-found.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/ecosystem.md
flags: i
pattern: '(no|none|zero|0)\b[^\n]{0,80}(integration|external system|connector|analytics|crm|newsletter|payment|sso)|(integration|external system)s?[^\n]{0,80}\b(none|not found|no evidence|absent|: 0\b|found: 0\b)'
---

`expected.json` records `integrations: []` (count 0) for this
fixture: no connector config and no API endpoint exist. The document must state that
absence in its own words (none found, no analytics, integrations: 0) instead of listing
systems.
