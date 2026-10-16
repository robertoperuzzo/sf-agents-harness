---
type: regex
target: last_message
flags: i
pattern: '\bconfig\b[^\n]{0,120}(table|serializ)|(table|serializ)[^\n]{0,120}\bconfig\b'
---

The answer names the Drupal 8+ signature it found: field metadata in the `config` table.
