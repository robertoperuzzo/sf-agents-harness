---
type: regex
target:
  source: file
  path: doc/Migrate/as-is/platform.md
flags: i
pattern: 'unknown|not (available|delivered|recoverable|known)'
---

The exact core release is recorded as unknown for a DB-only delivery, not invented from `system.schema`.
