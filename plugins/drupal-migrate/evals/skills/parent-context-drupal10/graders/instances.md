---
# Rendered by evals/scripts/render-cases.py from instances.md.tmpl; edit the template, not this file.
type: regex
target: last_message
flags: i
pattern: '(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])12(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)'
---

The instance count for the `paragraph` / `field_items` parent is 12 (every row of `paragraphs_item_field_data` with that parent, orphans included).
