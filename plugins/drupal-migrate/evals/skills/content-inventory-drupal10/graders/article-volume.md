---
# Rendered by evals/scripts/render-cases.py from article-volume.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/content-inventory.md
flags: i
pattern: 'article[^\n]*(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])12(?![\w.,]?\d)'
---

The inventory row for `article` carries the distinct total 12.
