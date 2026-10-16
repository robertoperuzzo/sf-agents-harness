---
# Rendered by evals/scripts/render-cases.py from active.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: '(?:active|live|published|in use)[^\n]{0,80}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])8(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)|(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])8(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)[^\n]{0,80}(?:active|live|published|in use)'
---

Active `text` paragraphs: 8, stated next to a word such as active, live or published (small numbers are anchored to their label so a no-data message cannot match by coincidence).
