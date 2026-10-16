---
# Rendered by evals/scripts/render-cases.py from no-answer-key.md.tmpl; edit the template, not this file.
type: tool_used
tool: Bash
min: 0
max: 0
arm: both
weight: 1
input_match: 'expected\.json|/evals/'
---

No `Bash` call looked at the ground truth of fixture `drupal10` or at the case
files: nothing under `/evals/` and no `expected.json`. A run that reads the answer key
is a lookup, not an evaluation, and the correctness graders cannot tell the difference.
