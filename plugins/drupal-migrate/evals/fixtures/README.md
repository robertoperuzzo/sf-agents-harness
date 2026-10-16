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
topology, delivery, database key or table prefix, the read-only runner, languages and
URL rules. It must not contain any value a grader checks (counts, bundle structure,
detection results), because the scaffold installs it in both eval arms. The `unknown`
fixture has no config file: the negative case that uses it must not be told what the
source is.

Both `generate` and `--check` scan the dump and `expected.json` for URLs and e-mail
addresses and fail on any host that does not end in `.example` or `example.com`.
`--check` also scans the committed files, so a hand edit that leaks a real host fails
even before the drift diff.

## Lifecycle: `bin/fixture`

`bin/fixture` is POSIX sh and runs on macOS and Linux. It needs Docker for every
command except `generate`.

```bash
fixture up drupal10                 # pull mariadb:10.11, start dm-fixture-drupal10, import dump.sql
fixture query drupal10 'SELECT 1'   # one read-only statement as `reader`, tab-separated with header
fixture status                      # state, host port and import marker of every fixture
fixture down drupal10               # remove the container and its data
fixture generate [name ...]         # python3 -I generate.py
fixture serve                       # host executor for eval workspaces (foreground, Ctrl-C to stop)
```

`up` is idempotent: a running, imported container is reported and left alone; a stopped
one is started without re-import. Each fixture has a default host port bound to
`127.0.0.1` (`drupal10` 5310, `drupal7` 5307, `wordpress` 5336, `unknown` 5399);
override with `FIXTURE_PORT_<NAME>`, for example `FIXTURE_PORT_DRUPAL10=53310`.

`query` refuses, before reaching Docker and with exit status 2:

- any statement whose first keyword (after leading whitespace and comments) is not
  `SELECT`, `SHOW`, `DESCRIBE`, `DESC`, `EXPLAIN` or `WITH`;
- more than one statement per call (a `;` anywhere but at the very end; a trailing `;`
  is fine);
- mariadb client commands: a backslash command such as `\!`, `\.`, `\T`, `\P` or `\G`
  anywhere, or `system`, `source`, `tee` and the other long-form commands at a line
  start;
- executable comments (`/*!` and `/*M!`), which the server runs instead of ignoring.

What passes runs as the unprivileged `mysql` OS user (`docker exec -u mysql`) with the
client in `--sandbox` mode, which disables every client escape on the server side as
well. The `reader` user holds `SELECT` only, so a write that reaches the server by any
other path fails with a privilege error. A missing `docker` binary exits 1 with a
message naming Docker. `bin/fixture-parser-test` exercises the refusals without Docker:

```bash
fixtures/bin/fixture-parser-test
```

## Inside an eval run: `fixture serve` and the queue client

The agent's shell in a `claude plugin eval` run is sandboxed: no network, no Docker
socket, no read access to the plugin checkout. So the runner an agent sees is not this
script but `bin/fixture-client`, which the case scaffold copies to
`.agents/bin/fixture` in the run workspace. `query` there writes the statement to
`.agents/queue/<id>.sql` (plus `<id>.fixture` with the fixture name; `<id>` comes from
`mktemp`, so concurrent calls and concurrent runs never collide), then waits for
`<id>.out` and `<id>.exit`, prints the output and exits with the recorded code
(poll 0.2 s; fails after 10 s without pickup or 60 s without a result, naming
`fixture serve`). `up`, `down` and `status` print "managed on the host" and exit 0.

`fixture serve` is the host side: a foreground process that writes
`~/.cache/dm-fixture/serve.pid`, polls every workspace registered under
`~/.cache/dm-fixture/workspaces/` (the scaffold registers the run workspace; a
registration whose directory is gone is dropped), and answers each request through
the same statement check and `docker exec -u mysql ... --sandbox` path as `query`.
Start it in a terminal before an eval run and stop it with Ctrl-C afterwards; the
scaffold refuses to run (exit 1, hint `fixture serve`) when no live pid is recorded.
`DM_FIXTURE_STATE_DIR` relocates the pid file and registry.

`serve` runs unsandboxed as the operator while the agent controls the workspace, so it
trusts nothing it finds there: a workspace is skipped unless `.agents` and
`.agents/queue` are real directories owned by the operator; only ids matching
`req.[A-Za-z0-9]{6}` are served; `<id>.sql` and `<id>.fixture` must be regular files
owned by the operator (a symlink is refused before it is read); `.working`, `.out` and
`.exit` are written through `mktemp` inside the queue and renamed into place, so a
planted link is replaced, never followed; an unknown fixture name is answered with a
fixed message, and the serve log never echoes request content.

`bin/fixture-bridge-test` round-trips the bridge with a private state dir: scaffold
without and with serve, `SELECT 1`, a count, a refused `UPDATE` and client command,
two concurrent requests, an empty queue afterwards, the planted-symlink and bad-id
scenarios above, and the client's fast failure (under 15 s, "not picked up") with
serve stopped. It needs Docker and the drupal10 fixture running;
`FIXTURE_UNDER_TEST` points it at another copy of the script.

```bash
fixtures/bin/fixture-bridge-test
```

## `spec.json` schema

### Keys shared by every kind

| Key        | Type   | Meaning                                                                                                                                   |
| ---------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `kind`     | string | builder to use: `drupal8` (Drupal 8+), `drupal7`, `wordpress` or `unknown`                                                                |
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

### `drupal7` keys

| Key                                    | Meaning                                                                                                                                                                    |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `source.drupal_major`                  | always 7; recorded in `expected.json`                                                                                                                                      |
| `site_name`, `site_mail`, `core_minor` | `variable` rows and the core version string in `system.info`                                                                                                               |
| `node_language`                        | `language` column of `node`, `url_alias` and every field row; `und` for a monolingual site                                                                                 |
| `modules`                              | list of `{name, status, core?, version?}`; one `system` row each, `status` 1 enabled, 0 disabled. Core modules live under `modules/`, others under `sites/all/modules/`    |
| `themes`                               | `system` rows of type `theme`; the first is `theme_default`                                                                                                                |
| `users`                                | `{name, mail, status}`; uid 0 is always added                                                                                                                              |
| `vocabularies`                         | optional `{machine_name: {label, terms}}`; `taxonomy_vocabulary` and `taxonomy_term_data` exist only when given                                                            |
| `fields`                               | `{field_name: {type, cardinality?}}`: one `field_config` row each. Types: `text`, `text_long`, `text_with_summary`, `taxonomy_term_reference` (`vocabulary`), `paragraphs` |
| `node_bundles`                         | `{type: {label, count, revisions, unpublished, alias_prefix, fields}}`; `fields` references names from `fields` and adds `label`, `population`, `children`                 |
| `paragraph_bundles`                    | `{bundle: {label, fields, orphans?, orphan_parent?}}`; bundles may have no fields                                                                                          |
| `menus`                                | optional `{menu_name: [{title, path or nid, parent?}]}` for `menu_custom` and `menu_links`                                                                                 |

Differences from `drupal8`: one `url_alias` row per node (`alias_prefix` is a string, no
leading slash in the alias); `node` holds one row per entity and the revision trap
lives in `node_revision` and `field_revision_*`; a `paragraphs` field row stores
`item_id` and `revision_id` in `field_data_<field>`; orphans are `paragraphs_item` rows
with the host `field_name` set but no `field_data_<field>` row pointing at them.
`expected.json` adds `fields` (the `field_config` list) and `url_aliases`.

### `wordpress` keys

| Key          | Meaning                                                                                                                                  |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `prefix`     | table prefix, `wp_`; recorded as `source.table_prefix`                                                                                   |
| `site`       | `blogname`, `blogdescription`, `admin_email`, `db_version`, `permalink_structure`, `theme`, `wplang`: rows of `{prefix}options`          |
| `plugins`    | list of `{file, name, active?}`; active ones form the serialized `active_plugins` option                                                 |
| `users`      | `{login, email, role}`; one `{prefix}users` row and a `{prefix}capabilities` usermeta row each                                           |
| `terms`      | `{taxonomy: [names]}` for `{prefix}terms` and `{prefix}term_taxonomy`                                                                    |
| `post_types` | `{type: {label, publish, draft?, revisions?, translations?, categories?, custom?, acf?}}` (see below)                                    |
| `menus`      | `{menu_name: [{title, url or post_type + index, parent?}]}`: a `nav_menu` term plus `nav_menu_item` posts with their `_menu_item_*` meta |

Post type keys: `publish` and `draft` count original posts in the default language;
`translations` (`{langcode: n}`) adds one translated post for each of the first `n`
originals and links them through `{prefix}icl_translations` with a shared `trid`;
`revisions` adds that many `post_type = revision`, `post_status = inherit` rows whose
`post_parent` is a published original; `categories` assigns originals round-robin;
`acf` (`{group, fields: [{name, type, key, sample}]}`) writes two postmeta rows per field
and post (`name` and `_name`) plus the `acf-field-group` and `acf-field` definition
posts. `expected.json` records `post_types.<type>` (publish, draft, originals,
translations, revision rows), `content_inventory.posts` keyed `type/status`,
`plugins`, `language_coverage.rows_by_language`, `options` and `menus`. No multisite
table is ever created.

### `unknown` keys

`source` (`delivery`, `base_url`, `default_langcode`, `languages`), `users`
(`{username, email, is_admin?}`) and `pages` (`{count, published}`). The dump holds
`cms_pages` and `cms_users` only; `expected.json.source.technology` is `other` and the
listed `absent` tables are every signature the detect-source skill knows.

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
