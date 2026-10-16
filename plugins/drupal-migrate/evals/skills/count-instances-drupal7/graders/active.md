---
# Rendered by evals/scripts/render-cases.py from active.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: '(?:published|active|status)[^\n]{0,80}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])7(?![\w.,]?\d)|(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])7(?![\w.,]?\d)[^\n]{0,80}(?:published|active|status)'
---

Published `article` nodes: 7, stated next to a word such as published or active.
