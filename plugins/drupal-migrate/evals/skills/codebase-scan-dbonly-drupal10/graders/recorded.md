---
type: regex
target: last_message
flags: i
pattern: '(record|note|document|wr(ite|itten|ote))[^\n]{0,160}(as-is|doc/Migrate|corpus|platform\.md|disposition)|(as-is|doc/Migrate|corpus|platform\.md)[^\n]{0,160}(record|note|document|wr(ite|itten|ote))'
---

The skip is recorded in the as-is corpus, as the skill's DB-only short-circuit asks,
rather than silently dropped.
