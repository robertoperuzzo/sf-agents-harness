---
# Rendered by evals/scripts/render-cases.py from pages.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/content-inventory.md
flags: i
pattern: 'page[^\n]*(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])6(?![\w.,]?\d)'
---

The `page` row carries 6.
