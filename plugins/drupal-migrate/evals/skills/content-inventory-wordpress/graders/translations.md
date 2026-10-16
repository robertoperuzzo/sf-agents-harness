---
# Rendered by evals/scripts/render-cases.py from translations.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/content-inventory.md
flags: i
pattern: '(\bit\b|italian)[^\n]{0,120}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])10(?![\w.,]?\d)'
---

WPML coverage: 10 Italian rows in `wp_icl_translations`.
