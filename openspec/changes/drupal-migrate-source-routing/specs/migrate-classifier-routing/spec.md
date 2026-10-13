# Spec Delta

## Purpose

Lets high-volume migration judgments (custom-code disposition, field mapping, page-fidelity verification) be pre-sorted by an external typed classifier that returns calibrated confidence, so only uncertain items reach the agent LLM, while keeping the integration optional, gated on data-processing approval, and measurable.

## ADDED Requirements

### Requirement: Classifier integration is off by default

The classifier integration SHALL be disabled unless `project-config.md` enables it and the classifier API key is present in the environment, and every skill that can use it SHALL behave exactly as before when it is disabled.

#### Scenario: No configuration

- **WHEN** `project-config.md` has no `Classifier` section
- **THEN** `codebase-scan`, `scan-destination` and `verify-content` run their LLM-only path and do not mention the classifier

#### Scenario: Enabled but key missing

- **WHEN** the `Classifier` section enables the integration and the API key environment variable is unset
- **THEN** the skill runs the LLM-only path and reports once that the classifier was skipped because the key is missing

### Requirement: Data-processing approval is a precondition

The plugin SHALL send source content to the classifier only when `project-config.md` records that a data-processing agreement covers the classifier provider for this project, and SHALL refuse to send content otherwise even if the integration is enabled.

#### Scenario: Agreement not recorded

- **WHEN** the `Classifier` section enables the integration and the `data_processing_approved` field is absent or not `yes`
- **THEN** no request is sent, the skill runs the LLM-only path, and the report states that the classifier is blocked pending data-processing approval

### Requirement: Questions are typed and batched

Each classifier request SHALL carry one typed question per item (a choice over a closed option set, a score on ordered levels, or a yes/no), with the item content as state, and SHALL batch all items of a skill run into as few requests as the provider's limits allow.

#### Scenario: Codebase scan with 50 custom plugins

- **WHEN** `codebase-scan` runs with the classifier enabled on 50 custom plugins
- **THEN** each plugin becomes one choice question over `replicate`, `triage`, `do_not_port` and `other`, and the questions are sent together rather than one request per plugin

#### Scenario: Field mapping with no plausible destination

- **WHEN** a source field is classified against the destination fields
- **THEN** the option set includes a `none` option, and a `none` answer leaves the field unmapped rather than forcing a destination

### Requirement: Items are routed by confidence

The plugin SHALL accept a classifier answer automatically only when its confidence meets the threshold set in `project-config.md` for that decision, SHALL send every other item to the existing LLM path, and SHALL mark in the output which path decided each item.

#### Scenario: High-confidence disposition

- **WHEN** a plugin's disposition answer has confidence at or above the configured threshold
- **THEN** the disposition is recorded with the marker "classifier" and the confidence value, and the LLM is not asked about that plugin

#### Scenario: Low-confidence page score

- **WHEN** a page-pair fidelity score has confidence below the configured threshold, or the score is below the configured pass level
- **THEN** the page is sent to the LLM comparison path, which produces the explanation of what differs, and the output marks the page as "LLM"

#### Scenario: Thresholds not configured

- **WHEN** the `Classifier` section enables the integration but sets no threshold for a decision
- **THEN** that decision uses the LLM path for every item and the report says the threshold is missing

### Requirement: Security disposition never comes from the classifier alone

The plugin SHALL NOT assign the `security` disposition to a custom-code unit on the classifier's answer alone; a `security` outcome SHALL always go through the LLM path.

#### Scenario: Classifier flags a plugin as risky

- **WHEN** the yes/no question "does this unit contain a security risk" answers above the threshold
- **THEN** the unit is routed to the LLM path for confirmation, and the classifier answer is recorded as a hint, not a disposition

### Requirement: Classifier failures fall back to the LLM path

The plugin SHALL treat a classifier request that fails, times out or returns an unparseable answer as "no answer" for every item in that request and SHALL route those items to the LLM path, without aborting the skill.

#### Scenario: Rate limit during verify-content

- **WHEN** a batched request returns HTTP 429 after the configured retries
- **THEN** every page in that batch is compared by the LLM path and the report counts how many pages fell back and why

### Requirement: Classifier use is measurable

Every skill run that uses the classifier SHALL report the number of items classified, the number accepted automatically, the number routed to the LLM, the classifier input tokens, and the model id, so the saving and the agreement with the LLM path can be measured.

#### Scenario: Measurement run on a past migration

- **WHEN** a skill runs with the `Classifier` section's `measure` flag set
- **THEN** every item is sent to both paths, the report lists per-item agreement between classifier and LLM, and only the LLM result is written to the migration documents

### Requirement: Non-English content is flagged

The plugin SHALL state in the report when the classified content's language is not English, because the classifier's accuracy on other languages is documented as lower, and SHALL NOT raise the acceptance threshold silently.

#### Scenario: Italian page pairs

- **WHEN** `verify-content` classifies page pairs whose base content language in `project-config.md` is not `en`
- **THEN** the report carries a note that the classifier was used on non-English content and points to the measurement run as the basis for the configured threshold
