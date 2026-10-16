---
type: llm
focus: last_message
weight: 1
---

Judge only the final message, which must be the analyst's Phase 1 as-is report. Rate
it on this five-level scale and answer PASS only for level 4 or 5:

1. No report, or a report that admits it did not reach the database, or one that
   contains invented systems, modules or numbers.
2. A report that names the written documents but gives no numbers, or whose numbers
   contradict each other.
3. A report with the platform, content-inventory and ecosystem findings but mixed with
   target decisions (what Drupal will do) or missing the roadmap / next-step state.
4. A report that states the frozen as-is facts (platform and module inventory, content
   volumes per type with published versus total, languages, ecosystem result) in plain
   terms, points to the files under doc/Migrate/as-is/, keeps mapping decisions out,
   and ends with the roadmap state.
5. Level 4 plus explicit caveats where the DB-only delivery limits the evidence (exact
   release unknown, custom code not scannable, integrations only from stored config).

Do not reward length. A short report that meets level 4 passes; a long one that invents
a fact fails.
