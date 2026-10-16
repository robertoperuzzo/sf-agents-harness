---
type: regex
target:
  source: file
  path: doc/Migrate/as-is/ecosystem.md
flags: i
match: not_contains
pattern: 'salesforce|hubspot|mailchimp|stripe|paypal|google analytics|tag manager'
---

No integration is invented.
