---
type: regex
target: last_message
flags: i
pattern: '`config`|\bconfig\s+table\b|\btable\s+`?config`?\b'
---

The answer names the Drupal 8+ signature it found: the `config` table (written as a
table name, in backticks or next to the word table), not the word config in another
sense.
