---
type: regex
target: last_message
flags: i
match: not_contains
pattern: 'drupal\s?8\+?\b(?![^\n]{0,40}(not|no|neither|absent|missing|instead))'
---

The source is not reported as Drupal 8+.
