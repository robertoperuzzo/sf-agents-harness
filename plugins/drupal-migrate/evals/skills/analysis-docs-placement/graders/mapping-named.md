---
type: regex
target: last_message
flags: i
pattern: 'openspec/changes/[a-z0-9_./<>-]*(mapping|content[- ]type)|(mapping|content[- ]type)[^\n]{0,160}openspec/changes'
---

The mapping proposal is tied to an OpenSpec change path in the same sentence, which is
the structured, reviewable form the documentation skill prescribes for a mapping with
an approval life cycle.
