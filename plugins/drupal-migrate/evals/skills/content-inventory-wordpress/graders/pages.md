---
# Rendered by evals/scripts/render-cases.py from pages.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/content-inventory.md
flags: i
pattern: 'page[^\n;]{0,80}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])6(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)'
---

The `page` row carries 6.
