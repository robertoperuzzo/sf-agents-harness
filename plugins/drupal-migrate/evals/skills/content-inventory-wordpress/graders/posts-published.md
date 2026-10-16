---
# Rendered by evals/scripts/render-cases.py from posts-published.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/content-inventory.md
flags: i
pattern: 'post[^\n]*(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])25(?![\w.,]?\d)'
---

The `post` row carries 25 published rows: this is `wp_posts` grouped by type and status, so it counts the 18 originals' published subset plus the 10 published Italian translation posts (design D3: 15 published originals plus 10 `it` translation posts).
