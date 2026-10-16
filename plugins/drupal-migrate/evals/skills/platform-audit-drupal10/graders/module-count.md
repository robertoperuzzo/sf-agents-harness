---
# Rendered by evals/scripts/render-cases.py from module-count.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/platform.md
flags: i
pattern: '(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])15(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)'
---

The enabled-module count 15 from `core.extension` appears in the document.
