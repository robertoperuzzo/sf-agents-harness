---
# Rendered by evals/scripts/render-cases.py from inactive.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: '(?:orphan(ed)?|inactive|not (live|active|published)|detached|excluded|stale)[^\n]{0,80}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])4(?![\w.,]?\d)|(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])4(?![\w.,]?\d)[^\n]{0,80}(?:orphan(ed)?|inactive|not (live|active|published)|detached|excluded|stale)'
---

Orphaned or inactive `text` paragraphs: 4 (total 12 minus active), stated next to a word such as orphaned or inactive.
