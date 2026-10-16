---
# Rendered by evals/scripts/render-cases.py from translations.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/content-inventory.md
flags: i
pattern: '(translat\w*|\bit\b|italian)[^\n]{0,120}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])10(?![\w.,]?\d)|(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])10(?![\w.,]?\d)[^\n]{0,120}(translat\w*|\bit\b|italian)|translat\w*[^\n]*\n[^\n]*\n[^\n]*(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])10(?![\w.,]?\d)'
---

WPML coverage: 10 Italian rows in `wp_icl_translations`, either
next to the word translation / it / Italian on the same line, or in the first row of a
table whose header names the translations.
