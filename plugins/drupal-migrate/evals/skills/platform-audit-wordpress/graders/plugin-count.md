---
# Rendered by evals/scripts/render-cases.py from plugin-count.md.tmpl; edit the template, not this file.
type: regex
target:
  source: file
  path: doc/Migrate/as-is/platform.md
flags: i
pattern: '(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])6(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)[^\n]{0,40}plugins|plugins[^\n]{0,60}(?<!drupal\s)(?<!mariadb\s)(?<![\w.,])6(?![\w.,]?\d|\s?(s|sec|secs|seconds|ms|min|minutes|h|hours|px|kb|mb|gb)\b)'
---

The active-plugin count 6 from `wp_options.active_plugins` appears in the document.
