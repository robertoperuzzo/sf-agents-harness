---
# Rendered by evals/scripts/render-cases.py from total.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: '(?:articles?|total|instances|distinct|nodes)[^\n]{0,80}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])8(?![\w.,]?\d)|(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])8(?![\w.,]?\d)[^\n]{0,80}(?:articles?|total|instances|distinct|nodes)'
---

Distinct `article` nodes: 8, stated next to a word such as article, total or distinct.
