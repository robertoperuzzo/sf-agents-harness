---
# Rendered by evals/scripts/render-cases.py from page-volume.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/content-inventory.md
flags: i
pattern: 'page[^\n]*(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])5(?![\w.,]?\d)'
---

The inventory row for `page` carries the distinct total 5.
