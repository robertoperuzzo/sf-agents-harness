---
# Rendered by evals/scripts/render-cases.py from tags-half.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: 'field_tags[^\n]{0,160}\b(49|50|51)(\.\d+)?\s*%'
---

`field_tags` is reported at 50.0 % within one point (the percentage is rendered as an integer, so `50%` and `50.0%` both match).
