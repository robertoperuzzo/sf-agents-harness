---
# Rendered by evals/scripts/render-cases.py from db-only.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: 'db\-only|db only|database[- ]only|no (source )?code(base)? (was )?delivered|not delivered'
---

The final message states the delivery recorded in `expected.json`
(`db-only`): the custom-code scan has no codebase to read.
