---
# Rendered by evals/scripts/render-cases.py from subtitle-empty.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: 'field_subtitle[^\n]{0,160}(\b0\s*%|\b0\s*/|\bempty\b|\bunused\b|\bnever\b|\bno values\b|not populated|zero)'
---

`field_subtitle` is reported at 0.0 % (empty) and flagged as a candidate to leave out.
