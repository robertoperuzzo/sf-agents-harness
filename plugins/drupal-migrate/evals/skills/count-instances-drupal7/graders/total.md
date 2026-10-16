---
# Rendered by evals/scripts/render-cases.py from total.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: '(?:articles?|total|instances|distinct|nodes)[^\n]{0,80}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])8(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)|(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])8(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)[^\n]{0,80}(?:articles?|total|instances|distinct|nodes)'
---

Distinct `article` nodes: 8, stated next to a word such as article, total or distinct.
