# Eval fixtures

Synthetic source databases for the `drupal-migrate` eval suite. Each fixture is a
directory with four files:

| File                | Origin               | Purpose                                                  |
| ------------------- | -------------------- | -------------------------------------------------------- |
| `spec.json`         | hand-written         | the single declarative description of the fixture        |
| `dump.sql`          | generated, committed | MariaDB dump imported by `fixture up <name>`             |
| `expected.json`     | generated, committed | ground truth the eval graders read                       |
| `project-config.md` | hand-written         | installed by the case scaffold as the plugin config file |

`generate.py` writes `dump.sql` and `expected.json` from `spec.json` in one run, from
one in-memory model, so the two cannot disagree. Regenerate whenever the spec changes
and commit all three files together:

```bash
python3 -I generate.py drupal10        # or: fixture generate drupal10
python3 -I generate.py --check         # exit 1 when committed files are stale
```

The generator is standard-library Python and deterministic: a fixed seed drives every
random choice, tables are emitted sorted by name, and the only timestamps derive from
the spec `epoch`. The dump preamble creates the SELECT-only `reader` user that
`fixture query` connects as, so the dump must be imported as root.

`project-config.md` declares only what a real project would declare: technology,
topology, delivery, database key, the read-only runner, languages and URL rules. It
must not contain any value a grader checks (counts, bundle structure, detection
results), because the scaffold installs it in both eval arms.

## `spec.json` schema

### Keys shared by every kind

| Key        | Type   | Meaning                                                                                                                                   |
| ---------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `kind`     | string | builder to use: `drupal8` (Drupal 8+). `drupal7`, `wordpress` and `unknown` are added with their fixtures                                 |
| `database` | string | schema name created by the dump and granted to `reader`                                                                                   |
| `seed`     | int    | seed of the `random.Random` instance behind every sampled choice and UUID                                                                 |
| `epoch`    | int    | base Unix timestamp; every `created`/`changed` value is `epoch` plus a fixed offset                                                       |
| `source`   | object | copied into `expected.json.source`: `technology`, `topology`, `delivery`, `base_url`, `default_langcode`, `languages`, plus per-kind keys |

`expected.json` always carries `fixture`, `kind`, `generator_version`, `source`,
`tables` and `signature` (tables whose presence or absence identifies the technology).

### `drupal8` keys

| Key                            | Meaning                                                                                  |
| ------------------------------ | ---------------------------------------------------------------------------------------- |
| `source.drupal_major`          | integer recorded in `expected.json`; the database itself cannot reveal it                |
| `site_name`, `site_mail`       | values of `system.site`                                                                  |
| `profile`, `modules`, `themes` | content of `core.extension`. List every module whose tables or config appear in the dump |
| `users`                        | list of `{name, mail, status}`; uid 0 (anonymous) is always added                        |
| `vocabularies`                 | `{vid: {label, terms: [names]}}`                                                         |
| `node_bundles`                 | `{type: {label, count, revisions, unpublished, languages, alias_prefix, fields}}`        |
| `paragraph_bundles`            | `{type: {label, fields, orphans?, orphan_parent?}}`                                      |
| `redirects`                    | list of `{source, nid, language?, status_code?}` rows of the `redirect` table            |
| `menus`                        | `{menu_name: [{title, uri or nid, parent?}]}`; `parent` names an earlier link title      |

Node bundle keys:

- `count`: distinct entities. `unpublished`: how many of them, taken from the end of the
  nid range, get `status = 0`.
- `revisions`: rows per entity in `node_revision`; the last one is current.
- `languages`: langcodes with a translation row; the default language is always first.
- `alias_prefix`: `{langcode: prefix}` used to build one `path_alias` row per node and
  language, `/<prefix>/<slug of title>`.

Field keys (`fields` is `{field_name: {...}}` on node and paragraph bundles):

- `type`: `string`, `text_long`, `text_with_summary`, `entity_reference` or
  `entity_reference_revisions`. The type decides the value columns of the field table
  and the `field.storage.*` config row.
- `population`: fraction of the bundle's distinct entities that get a value, `0.0` to
  `1.0`. The populated subset is sampled once per field; a populated entity has the
  value in every revision and language. The count is `round(count * population)` with
  Python's banker's rounding: `0.5 * 5` gives 2, `0.5 * 12` gives 6.
- `entity_reference`: `target_type` and `target_bundles`; `population` selects the
  entities, each gets two terms from the first target vocabulary.
- `entity_reference_revisions` (node or paragraph): `children` lists the paragraph
  bundles created for each populated entity, in delta order, one paragraph per entry.
  Paragraph trees and reference rows exist only for populated entities. Child
  paragraphs recurse through their own `entity_reference_revisions` fields.
- `label`, `cardinality`, `translatable`: optional, config only.

Paragraph bundle keys:

- `orphans`: how many extra instances to create with no referencing row in any
  reference table. `orphan_parent` (`{type, bundle, field}`) is the parent they claim in
  `paragraphs_item_field_data`: the last instance of that paragraph bundle, or the last
  node of that node bundle. A join on `parent_id` finds them; a join through the
  reference table does not, which is the trap the orphans exist for.

### Ground truth produced for `drupal8`

- `entities.<entity_type>.<bundle>`: `distinct`, `active`, `fields` (per field `type`,
  `populated`, `population_pct`, reference targets), `parent_bundles`, `child_bundles`;
  nodes add `unpublished`, `revisions_per_entity`, `languages`, `field_data_rows`,
  `field_revision_rows`; paragraphs add `attached`, `orphans`, `is_container`,
  `root_node_bundles`. A paragraph is active when it hangs, through current-revision
  references only, from a published node.
- `content_inventory.node.<bundle>`: `total`, `published`, `languages`.
- `language_coverage`, `modules`, `redirects`, `path_aliases`, `menus`, `examples`
  (first published node per bundle with its aliases and public URL).

After building, the generator recounts every field table against `expected.json` and
aborts on any mismatch, so a builder bug cannot ship inconsistent files.
