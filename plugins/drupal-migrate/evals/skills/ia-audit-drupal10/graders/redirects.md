---
# Rendered by evals/scripts/render-cases.py from redirects.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: 'redirect[^\n]{0,80}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])3(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)'
---

The redirect count 3 from the `redirect` table is reported next to the word redirect.
