---
type: regex
target: last_message
flags: i
pattern: 'field_tags[^\n]{0,160}(unlimited|-1)'
---

`field_tags` is reported with unlimited cardinality (`-1`).
