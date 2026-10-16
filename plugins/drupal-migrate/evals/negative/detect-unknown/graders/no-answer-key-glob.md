---
# Rendered by evals/scripts/render-cases.py from no-answer-key-glob.md.tmpl; edit the template, not this file.
type: tool_used
tool: Glob
min: 0
max: 0
arm: both
weight: 1
input_match: 'expected\.json|(^|[^\w-])evals/|plugins/drupal-migrate/?(["'' ]|$)'
---

No `Glob` call looked at the ground truth of fixture `unknown` or at the case
files: no `expected.json`, no `evals/` path (absolute or relative), and not the plugin
root used as a search root (which would sweep `evals/` without naming it). A run that reads the answer key
is a lookup, not an evaluation, and the correctness graders cannot tell the difference.
