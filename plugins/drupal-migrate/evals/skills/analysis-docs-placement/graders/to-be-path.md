---
type: regex
target: last_message
flags: i
pattern: 'doc/Migrate/to-be/|openspec/changes/[a-z0-9_./<>-]*(mapping|content[- ]type)'
---

The mapping lands where the documentation skill puts a to-be proposal with an approval
life cycle: an OpenSpec change when the project has `openspec/`, otherwise plain
markdown under `doc/Migrate/to-be/<name>.md` (the eval workspace has no `openspec/`
directory, so the fallback is the expected placement, with the OpenSpec form named
as the normal one).
