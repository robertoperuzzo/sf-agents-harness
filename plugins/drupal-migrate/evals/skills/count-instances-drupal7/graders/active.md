---
# Rendered by evals/scripts/render-cases.py from active.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: '(?:published|active|status)[^\n]{0,80}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])7(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)|(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])7(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)[^\n]{0,80}(?:published|active|status)'
---

Published `article` nodes: 7, stated next to a word such as published or active.
