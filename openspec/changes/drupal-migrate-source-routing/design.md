# Design

## Context

See `proposal.md` for motivation and
`plugins/drupal-migrate/docs/jev-classifier-routing-analysis.md` for the per-decision
analysis this design implements.

Current state that shapes the approach:

- The plugin is prose only: one agent file, 21 `SKILL.md` files, two reference
  templates. No hooks module, no scripts. Skills read project values from
  `.agents/references/migrate/project-config.md` in the host project.
- `drupal-migrate-detect-source` already returns the routing enum
  (`source_tech`, `topology`, `delivery`, `db_access_method`) and
  `drupal-migrate-detect-version` returns `source_version`. The enum is reported in
  prose and re-read by every later skill.
- 7 skills branch on Drupal 7: 5 carry a literal "Drupal 7 differences" block
  (`count-instances`, `field-population`, `parent-context`, `resolve-examples`,
  `verify-active`) and 2 branch under "Drupal 7" / "Drupal 8+" step headings
  (`detect-container`, `query-fields`). 5 skills carry WordPress and Drupal blocks side
  by side; 4 of them are split in this change (`content-inventory`, `db-discover`,
  `ia-audit`, `platform-audit`) and the fifth, `detect-source`, keeps its branches
  because it is the detector. `drupal-migrate-verify-content` is the largest skill
  (about 3,300 words) and the highest-volume runtime step.
- The agent file tells the model that when a skill is not loaded it must perform the
  skill's documented logic inline (`drupal-migration-analyst.agent.md`, "If a skill is
  not loaded"). Any refusal mechanism has to override that rule.
- `drupal-migrate-verify-content` reaches destination pages through `{dest_runner}`
  (a container-side `curl`) and the browser tool; page snapshots land in the agent
  context. No main-content extraction step exists today; the comparison is "substance,
  not structure" by the LLM.
- The plugin is installed with `/plugin install` in Claude Code, but its skill files
  are also readable by other hosts. Claude Code mods (hooks modules) run only in the
  Claude Code CLI and desktop app, and the `$.process` noun is documented as CLI only;
  the mod API is early access and changes between releases (checked against build
  2.1.296: `skill.prompt`, `tool.call`, `session.start`, `$.process.run`,
  `$.http.fetch`, `$.fs.read`, `$.state`).
- Jev is reachable at `POST https://api.typesafe.ai/v1/systemone` with a bearer key,
  takes a `state` and a map of typed questions, and returns per-question
  `choice`/`score`/`noul` with `probabilities` and `confidence`. Limits: 255 options
  per choice, 2 to 10 score levels, context length not published. Documented rough
  edges: literal reading, first-option bias, lower non-English accuracy, state not
  treated as hostile.

## Goals / Non-Goals

**Goals:**

- One place that establishes routing facts; every skill consumes, none re-detects.
- A skill loads one variant. The loaded text for a given source is identical whether
  the variant is read from a file or served by the mod.
- The classifier path is additive: disabled, the plugin behaves as today; enabled, it
  only removes work from the LLM path and never changes what is written to the
  migration documents except through the LLM path or an accepted high-confidence
  answer.
- Everything the classifier decides is visible and measurable in the skill report.

**Non-Goals:**

- Replacing the agent LLM for phase/intent inference, module-to-contrib mapping, or
  any decision that needs ecosystem knowledge or the doc corpus.
- Running Jev locally, caching its answers across runs, or fine-tuning it.
- Supporting the mod in Copilot or OpenCode profiles.
- Changing the content or structure of the as-is / to-be document corpus.

## Architecture

```mermaid
flowchart TB
    subgraph host["Host project"]
        PC[".agents/references/migrate/project-config.md"]
        SRC[("Source DB / codebase")]
    end

    subgraph plugin["drupal-migrate plugin"]
        subgraph routing["Routing layer"]
            DET["detect-source + detect-version\n(file + table signatures)"]
            FACTS["Routing facts\nsource_tech · topology · delivery\ndb_access_method · source_version"]
        end
        subgraph skills["Skills"]
            BODY["SKILL.md body\n(source-independent)"]
            VAR["variants/wordpress.md\nvariants/drupal7.md\nvariants/drupal8.md"]
        end
        subgraph mod["Hooks module (Claude Code only)"]
            SS["facts loader\nfirst drupal-migrate Skill call\n(or session.start when\nproject-config.md exists):\nread config, detect (CLI only),\nstore facts in $.state"]
            SP["skill.prompt\nbody + one variant"]
            TC["tool.call Skill\nrefuse Drupal-only skill\non non-Drupal source"]
            CL["classifier client\nfetch + strip items,\n$.http.fetch to Jev,\nconfidence routing"]
        end
    end

    JEV[("Jev API")]
    LLM["Agent LLM"]

    PC --> DET
    SRC --> DET
    DET --> FACTS
    FACTS --> VAR
    BODY --> LLM
    VAR -->|"file read\n(any host)"| LLM
    FACTS --> SS
    SS --> SP
    SP -->|"served text\n(Claude Code)"| LLM
    FACTS --> TC
    CL <-->|"batched typed questions"| JEV
    CL -->|"low confidence"| LLM
```

### Run flow

```mermaid
sequenceDiagram
    participant U as Invocation
    participant M as Hooks module
    participant A as Agent LLM
    participant S as Skill (file path)
    participant J as Jev

    U->>A: prompt
    A->>M: first drupal-migrate-* Skill call
    M->>M: read project-config.md
    alt facts declared
        M->>M: store facts (from project-config)
    else detect (CLI only)
        M->>M: $.process.run signature checks
        M->>M: store facts (detected)
    else desktop app
        M->>M: leave facts unset; detect-source fills them
    end
    M->>M: tool.call: allowed for source_tech?
    M->>M: skill.prompt: body + variants/<source_tech>.md
    M-->>A: skill text (one variant)
    A->>S: run queries with db_access_method
    opt classifier enabled and approved
        A->>M: item references (paths, URL pairs) via skill step
        M->>M: fetch and strip items (never through the agent)
        M->>J: batched requests of batch_size items
        J-->>M: answers + confidence
        M-->>A: accepted items, items for LLM path
    end
    A-->>U: report + routing marker per item
```

### Confidence routing

```mermaid
flowchart LR
    IN["Items from skill\n(plugins, fields, page pairs)"] --> GATE{"enabled AND key\nAND approved?"}
    GATE -->|no| LLM["LLM path\n(current behaviour)"]
    GATE -->|yes| BATCH["Batch typed questions"]
    BATCH --> JEV[("Jev")]
    JEV -->|"error / 429 / timeout"| LLM
    JEV --> ANS["answer + confidence"]
    ANS --> SEC{"security hint?"}
    SEC -->|yes| LLM
    SEC -->|no| TH{"confidence ≥ threshold\nAND score ≥ pass?"}
    TH -->|yes| ACC["accept, mark 'classifier'"]
    TH -->|no| LLM
    LLM --> OUT["migration docs + report"]
    ACC --> OUT
```

## Decisions

### D1. Variant files are the primary mechanism; the mod is an optimisation

Each source-dependent skill becomes `SKILL.md` (body, prerequisites, steps with
placeholders) plus `variants/<source>.md` holding the tables and queries for one
source. The body says: "Load `variants/{source_tech}.md` (or
`variants/drupal7.md` when `source_version` is `drupal7`) before Step 1." In Claude
Code the mod's `skill.prompt` hook appends the variant to the body so the model never
issues the read; elsewhere the model reads the file.

The agent rule "if a skill is not loaded, perform its documented logic inline" is
narrowed to skills that were not loaded for a technical reason. A skill that refused
to run (Drupal-only on a non-Drupal source, variant missing) is never performed
inline; the agent records the refusal and moves on. Without this, a `tool.call`
denial would be answered by the agent running the Drupal queries itself.

Why: the plugin's skills must keep working in any host that reads skill files. A
mod-only mechanism would make the WordPress path depend on an early-access API.
Alternative considered: one `SKILL.md` per source per skill (`count-instances-d7`),
rejected because it triples the skill catalog and breaks the agent's skill table.

### D2. Routing facts live in one record, written once

The facts record is the output block `detect-source` already prints, made canonical:
in Claude Code it is stored in `$.state` by the mod; in other hosts the agent writes
it into the roadmap block and skills read it from there. `project-config.md` values
win over detection; a detected value is marked "detected" with its evidence.

When the mod loads the facts:

- Lazily, on the first `tool.call` for a `drupal-migrate-*` skill in the session. A
  `session.start` load happens only when `.agents/references/migrate/project-config.md`
  exists in the working directory. Sessions in projects without the file run no
  detection commands and touch no host state.
- Detection through `$.process.run` runs only in the CLI (`$.process` is documented
  CLI only). In the desktop app the mod reads declared facts from `project-config.md`
  and leaves undeclared facts unset; `detect-source`'s own Bash steps detect them, and
  the mod reads the facts block from that skill's `tool.call` result to fill `$.state`.
  This result hook is also what refreshes the facts whenever `detect-source` runs.

Why: the agent prompt today repeats "pass `source_version: drupal7` to every step".
One record removes the repetition and the chance of a skill defaulting to D8+.
Alternative: have each skill re-run the cheap signature check, rejected because it
costs a tool call per skill and still leaves the branch text loaded. Alternative:
unconditional `session.start` detection, rejected because it probes the filesystem
and database of every project the plugin is installed in.

### D3. Entity type by DB lookup, not name heuristic

The lookup queries the bundle configuration entities, not the field configuration.

Drupal 8+:

```sql
SELECT name FROM config WHERE name IN (
  'node.type.{bundle}',
  'paragraphs.paragraphs_type.{bundle}',
  'taxonomy.vocabulary.{bundle}',
  'media.type.{bundle}',
  'block_content.type.{bundle}'
);
```

The prefix maps to the entity type: `node.type` is `node`,
`paragraphs.paragraphs_type` is `paragraph`, `taxonomy.vocabulary` is
`taxonomy_term`, `media.type` is `media`, `block_content.type` is `block_content`.

Drupal 7: `node_type.type` (node), `paragraphs_bundle.bundle` (paragraphs_item),
`taxonomy_vocabulary.machine_name` (taxonomy_term), `file_type.type` (file, when the
`file_entity` module is present), each queried with `WHERE <column> = '{bundle}'`.

`project-config.md` may declare a mapping that wins. Zero rows across the bundle
tables means the bundle does not exist; more than one match means ask. The field
configuration (`field.field.%.{bundle}.%`, `field_config_instance`) may be read
afterwards for the field list but never decides whether the bundle exists.

Why: the heuristic ("name contains group/modal/card → paragraph") is wrong whenever
a project names bundles differently, which the skill itself admits. The lookup is one
query against tables every Drupal source has. An earlier draft of this decision looked
up the field configuration instead; it returns zero rows for a bundle with no
configurable fields (a node type with only base fields, an empty vocabulary) and
would have reported an existing bundle as missing.

### D4. Classifier client lives in the mod, with a Bash fallback

In Claude Code the mod exposes the classifier through a skill step that the agent
runs as a tool call, passing item references only (file paths for `codebase-scan`,
field names for `scan-destination`, URL pairs for `verify-content`). The mod reads
or fetches the content itself, strips it, calls `$.http.fetch`, and returns only the
routing result (accepted items, items for the LLM). Outside Claude Code the same step
runs `scripts/classify.sh`, which fetches, strips and posts with `curl` and prints the
same routing result.

The token saving exists only when the agent never opens the item for the classifier
path:

- `codebase-scan`: the mod reads plugin files with `$.fs.read`; the script reads them
  from disk.
- `verify-content`: the mod fetches the source page with `$.http.fetch` and the
  destination page through `{dest_runner}` `curl` via `$.process.run` (the
  destination host is container-internal); in the desktop app, or when
  `$.http.fetch` is blocked by policy, the step runs `classify.sh` instead. Both
  strip navigation, header, footer, script and style elements and keep the main
  content region. A page that needs JavaScript rendering, needs authentication the
  fetch cannot carry, or yields no main content is routed to the LLM path, which
  keeps today's browser-tool comparison. Items the classifier accepts are never
  opened by the agent.

Why: a mod call keeps page bodies and plugin source out of the model context, which
is where the token saving is. The Bash fallback keeps behaviour identical in other
hosts at a higher token cost. Alternative: Python SDK, rejected because the plugin
would gain a runtime dependency on every workstation; `curl` is already required by
the repo's sync scripts.

### D5. Thresholds and gates are per-decision config in `project-config.md`

New optional section:

```markdown
## Classifier (optional)

| Setting                  | Value                                  |
| ------------------------ | -------------------------------------- |
| Enabled                  | `yes` / `no`                           |
| Provider                 | `typesafe-jev`                         |
| Model id                 | `jev-1.13` (pin it)                    |
| API key variable         | `TYPESAFE_API_KEY`                     |
| data_processing_approved | `yes` / `no` (reference to the DPA)    |
| Threshold codebase-scan  | `0.85`                                 |
| Threshold field-mapping  | `0.80`                                 |
| Threshold verify-content | confidence `0.80`, pass score `4` of 5 |
| Batch size               | `50` items per request (default)       |
| measure                  | `yes` / `no` (run both paths, compare) |
```

Why: TypeSafe's own guidance is that thresholds depend on the domain and must be
tuned on your data; a missing threshold routes everything to the LLM, so an
under-configured project loses nothing. `data_processing_approved` is a hard gate
because the state is client content. `Batch size` bounds two unknowns: Jev's
context length is not published, and a failed request routes every item in it to the
LLM path, so a smaller batch limits both the chance of a 422 and the blast radius of
a 429. The client halves the batch and retries once on 422 before falling back.

### D6. Question design follows Jev's documented rough edges

- Choice options are listed with descriptions and always end with `other` or `none`.
- The first option is never the "default" answer; option order is randomised per
  request in the client, and a measurement run checks answer stability under reorder.
- No counting, dates or arithmetic go to Jev; those stay in SQL and code.
- Page bodies are stripped of navigation, header, footer, script and style elements
  before they become state. This extraction is new work in the classifier client
  (D4); `verify-content` today compares whole page snapshots by LLM and has no
  extraction step.
- Instructions and criteria are literal and name the state fields they refer to.

### D7. Measurement before trust

The `measure` flag runs both paths on every item and writes a per-item agreement table
to the report. The pilot runs on one completed migration with Italian content and one
with English content before any threshold is recommended as a default in the
template.

## Risks / Trade-offs

- [Mod API changes between Claude Code releases] → the mod is optional; the file-based
  path is the contract. Pin the checked build in the plugin README. No CI job
  validates plugins today (`test-sync-skills.yml` triggers on `plugins/**` but checks
  only the upstream-skills manifest), so add a new step that runs
  `claude plugin validate plugins/drupal-migrate` when the Claude Code CLI installs on
  the runner, and otherwise `tsc -p plugins/drupal-migrate` against the declaration
  file checked in with the plugin.
- [Agent performs a refused skill inline] → the agent rule is narrowed in D1; the
  WordPress refusal eval in task 2.3 asserts that no Drupal query follows the refusal.
- [Client content sent to a second processor] → hard gate on
  `data_processing_approved`; the gate is a spec requirement, not a convention; the
  report always states when content was sent.
- [Lower accuracy on Italian content] → non-English note in every report; measurement
  run required before a threshold is set; `verify-content` low scores always reach
  the LLM, so a false "not faithful" costs tokens, not correctness. A false
  "faithful" is the real risk; the pilot measures it against the LLM path.
- [First-option bias and literal reading] → D6 mitigations; measurement checks
  reorder stability.
- [Variant split changes 11 skills at once] → one skill first
  (`drupal-migrate-count-instances`), its evals extended for D7 and WordPress refusal,
  then the pattern applied to the rest.
- [Token saving smaller than expected when many items fall below threshold] → the
  report counts accepted vs routed items; if the accepted fraction stays under about
  half on the pilot, the classifier is not worth enabling for that decision and the
  template says so.
- [Jev early access, waitlist] → the integration is dormant until a key exists;
  nothing in the plugin requires it.

## Migration Plan

1. Land the variant split and routing facts (spec `migrate-source-routing`) as a
   plugin version bump; existing projects need no config change because the facts
   already come from `project-config.md` or detection.
2. Land the mod in the same plugin version, disabled by nothing: it only serves what
   the files already contain. Users on hosts without mods see no difference.
3. Land the classifier capability dormant (no `Classifier` section means off). Enable
   it per project after the DPA is recorded and a measurement run has been reviewed.
4. Rollback: remove the `Classifier` section from `project-config.md` (classifier off)
   or disable the plugin's mod in `/plugin` (file-based variants remain).

## Open Questions

- Which past migration serves as the Italian measurement set, and who approves
  sending its content to TypeSafe for the pilot. This changes neither the specs nor
  the tasks; it decides when task group 6 can run.
- Whether `$.http.fetch` is allowed by the organisation's web-fetch policy on managed
  workstations. If not, the Bash `curl` fallback is used in Claude Code too.
- Whether the `skill.prompt` hook receives the plugin root (the input carries only
  `skill` and `text`). If `register`'s `options` does not expose it, the hook derives
  the `variants/` path from the module's own location. Task 5.2 settles this first.
