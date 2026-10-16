---
# Rendered by evals/scripts/render-cases.py from product.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/content-inventory.md
flags: i
pattern: 'product[^\n]*(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])4(?![\w.,]?\d)'
---

The `product` custom post type row carries 4.
