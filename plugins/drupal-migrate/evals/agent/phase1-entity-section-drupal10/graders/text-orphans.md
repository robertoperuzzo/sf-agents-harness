---
# Rendered by evals/scripts/render-cases.py from text-orphans.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: '(?:orphan(ed)?|inactive|not (live|active|published)|detached|excluded|stale)[^\n]{0,80}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])4(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)|(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])4(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)[^\n]{0,80}(?:orphan(ed)?|inactive|not (live|active|published)|detached|excluded|stale)'
---

The recursive analysis of the `text` child reports 4 orphaned or inactive instances (12 total, 8 active).
