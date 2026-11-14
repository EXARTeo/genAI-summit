# Synthetic test data

> Status: **MVP built** in `synthkit` inside the sandbox runner ([sandbox.md](../services/sandbox.md)): profiling,
> DAG sampler, safe rules, twins, edge cases, perturbations, boundary-aware sampling, five gates, Data Card.
> **Public data first** (§ 2a): before anything is generated, the agents service searches public catalogues for
> a dataset that matches the case; a human-approved match feeds synthkit's `reference_sample` mode.
> The sections below marked *Later* are not built yet. Extends `generate_data` in the
> [engineer pipeline](README.md#engineer-pipeline-pdf-125) and the plugin files in
> [agent-context.md § 3](agent-context.md#3-plugins-how-to-reach-a-model-what-it-is-what-it-should-do).

## 1. Recommendation

**Spec first, solver-backed, LLM-assisted.** The LLM never writes rows directly for tabular targets. It reads the
plugin (`data-dictionary.yaml`, `training-data.md`, `expected_behaviour`, `scenarios`) and memory, and drafts a
**GenerationSpec**: marginals, conditional distributions (a small causal DAG: who depends on whom), hard rules and
value sources. A human sees that spec at the dataset audit. Deterministic code then samples the base population
from the DAG (no real data needed), repairs or rejects rows that break hard rules (Z3 for hard boundary cases), fills
realistic surface fields with Faker/Mimesis, and applies **test-specific transforms** (counterfactual twins with and
without proxy propagation, boundary and missing-value perturbations). Every dataset passes five gates (schema,
business rules, realism vs the training-data description, coverage, privacy) and ships with a **Data Card**.
**Public data first:** when a public dataset matches the case (found and scored deterministically, picked by a
human, § 2a), synthkit fits the dictionary's DAG to it (`reference_sample`: marginals and conditionals by
counting, no SDV) and the same rules and transforms apply; otherwise the DAG is zero-shot from the dictionary. For LLM chat targets the LLM *does* write the text, but inside a deterministic **persona × intent ×
attack** coverage grid, with name-swap twins built by templates, not by the LLM. Result: schema-correct by
construction, business-realistic by an auditable spec, and reproducible from `(spec, seed)`.

Why not the alternatives alone:

| Approach | Good at | Fails at (for us) |
| --- | --- | --- |
| LLM writes rows (JSON Schema structured outputs) | Plausible text, semantics, zero data | Weak marginals/correlations, mode collapse, low diversity, hallucinated combos, not reproducible, costly per row |
| Fine-tuned LLM generators (GReaT, TabuLa, Tabby, GReaTER, LLM-TabLogic) | Fidelity when trained on real data | Need real training data and GPU; we usually have none |
| CLLM (LLM generates + curation by learning dynamics) | Low-data augmentation | Needs a small real set and a downstream model |
| SDV GaussianCopula / CTGAN / TVAE + constraints | Fidelity to a reference sample, conditional sampling | Need a reference sample; CTGAN/TVAE slow and noisy on small data |
| Faker / Mimesis | Realistic surface fields (names, addresses) | No joint distribution, no business logic |
| Constraint solvers (Z3, OR-Tools CP-SAT) | Hard rules, exact boundary cases | Not a distribution; use for edge cases and repair only |
| **Hybrid (ours): LLM drafts rules/DAG → sampler + solver enforce** | Zero-data realism, auditable, reproducible, cheap | Realism only as good as the spec, hence the HITL audit and realism gate |

## 2. Generation pipeline

```text
P0 profile model    code → model-profile.json (synthkit profile): signature, output, sensitivity,
                           monotonicity, decision boundary + surrogate, which protected/proxy fields move it
P0b find_public_data code (agents service, internet) → dataset-candidates.json/.md, artifact
                           public_dataset_candidates → [HITL pick] → fetch → datasets/public/<slug>/
P1 scenarios        LLM  → scenarios.yaml, checked by code (synthkit scenarios-check) against plugin + profile
plan_tests (one TestSpec per test)
 → generate_data, per TestSpec:
   G0 read context      plugin.yaml, data-dictionary.yaml, training-data.md, example_input, scenarios, memory,
                        model-profile.json
   G1 draft spec   LLM  → GenerationSpec (YAML, validated against its JSON Schema)          cites files + MEM ids
   G2 compile      code → DAG sampler + rule checker + value sources; reject unknown fields/ops
   G3 base sample  code → N rows from DAG (fitted to the public reference if reference_sample); seed fixed;
                          boundary-aware: a share of rows picked near the threshold via the profile's surrogate
   G4 enforce      code → hard rules: repair (resample offending node) → reject; Z3 for boundary rows
   G5 surface      code → Faker/Mimesis/LLM-text fields (names, CV text) conditioned on the row
   G6 transform    code → template-specific: twins, perturbations, boundaries, attack prompts
   G7 gates        code → schema · rules · realism · coverage · privacy  (fail → back to G1 with the report, max 2)
   G8 data card    code+LLM → DataCard.yaml (numbers by code, narrative by LLM)
 → [HITL audit datasets]  spec diff, gate report, sample rows, twin pairs, realism charts
 → execute
```

| Step | Reads | LLM does | Deterministic code does | Output |
| --- | --- | --- | --- | --- |
| P0 | `plugin.yaml` (`access`, `io`), `data-dictionary.yaml`, optional `sample.csv` | – | ~256 valid probe rows (half DAG samples, half Latin hypercube with hard rules enforced) → model calls (rate-limited for REST) → sensitivity (one-at-a-time + permutation), monotonicity vs `monotone`, boundary band + linear surrogate on logit(score), positive rate per group, proxy association, notes | `model-profile.json` |
| P1 | Plugin, memory, profile | Draft `scenarios.yaml` (requirement, target, template, data needs, expected behaviour) | Completeness, unknown fields, coverage of protected/proxies/monotone/edge cases, missing cases ranked by the profile | `scenario-analysis.json/.md` |
| G0 | `plugin.yaml` (`io`, `expected_behaviour`, `scenarios`, `placement`), `data/*`, `/memory/systems/<id>/`, top `/memory/org/` | – | Load, pin versions, log reads | Run context |
| G1 | Context + TestSpec (template, metric, groups, N) | Infer missing marginals/conditionals from `training-data.md`; propose personas, edge cases, inter-field rules; mark each with `provenance: dictionary \| training_doc \| memory \| llm_assumption` | Validate spec against JSON Schema; refuse fields not in the dictionary | `GenerationSpec` |
| G2 | Spec | – | Topological sort of DAG; parse rules with a safe expression evaluator (no `eval`) | Compiled sampler |
| G3 | Spec (+ reference sample, + model profile) | – | Ancestral sampling, optionally balanced per stratum; **boundary-aware oversampling**: `boundary.share` of rows are each the best of `pool` valid candidates by the surrogate's distance to the threshold (rows that discriminate most per model call); in `reference_sample` mode the mapped fields' tables and empirical quantiles are fitted from the approved public dataset (§ 2a) | Base rows |
| G4 | Hard rules | – | Vectorised check; resample violating node up to k times; drop the rest; Z3 to construct exact boundary rows | Valid rows + reject log |
| G5 | Surface fields | Short free text only (CV summary, chat utterance), batched, structured output, row as input | Faker/Mimesis with locale from row (e.g. nationality → locale); names from curated per-group lists | Full rows |
| G6 | Template | Attack/persona utterances for `llm_chat` | Twins, perturbations, boundaries (section 3) | Test dataset(s) |
| G7 | Rows + spec + `training-data.md` stats | – (LLM may *explain* a failed gate) | Gates below | Gate report |
| G8 | All of the above | Plain-language limitations | Counts, hashes, metrics | `DataCard.yaml` |

## 2a. Public data first (`find_public_data`)

User decision: **before generating dummy data, look for public datasets that match the case exactly**, then
generate synthetic data with the public data as the reference where it fits, zero-shot from the dictionary
otherwise. Pipeline order:

```text
profile_model → find_public_data (+ HITL pick) → plan_scenarios → … → draft_spec (reference_sample | zero_shot)
  → generate → analyze
```

| Step | Where | What |
| --- | --- | --- |
| Search | agents service, `harness/tools/public_datasets` (pure Python + httpx, no LLM) | Queries from the system card (Annex III point, purpose) and the plugin's `data-dictionary.yaml` (fields, protected/proxy, label) → OpenML, UCI, Hugging Face, optional Firecrawl (Kaggle, data.europa.eu, Zenodo, data.gov) |
| Score | same, deterministic | `0.30 schema + 0.15 protected/proxy + 0.15 label + 0.10 relevance + 0.10 task + 0.05 size + 0.10 licence + 0.05 recency`; per candidate the column mapping (name/synonym similarity × type fit; `bin` for numeric age → bands, `value_map` for categories; coded values without a map count half), gaps, flags. Licence allow-list CC0 / CC-BY(-SA) / ODbL / ODC-By / PDDL / MIT / Apache-2.0; NC = score halved and not fetchable; unknown = `licence_unclear` |
| Explain | optional Gemini (`GOOGLE_API_KEY`) | Adds `llm_rank` and a one-line note per candidate; never changes the score |
| HITL | audit artifact `public_dataset_candidates` (`name` = plugin) | `data` = the candidates JSON (`candidates`, `candidates_full`, `recommendation`). The human **approves** it and may set `data.selected` to one id. A rejection, or a `zero_shot` recommendation (no fetchable candidate ≥ 0.5), means zero-shot |
| Fetch | `fetch_public_dataset` | Only for an approved artifact (and the selected id). Row cap 5,000, byte cap 20 MB (cut at a row), PII columns dropped (names, e-mails, phones, addresses…) and recorded, stored through `PUT /internal/audits/{id}/datasets/public/{slug}/{file}`: `data.csv`, `mapping.yaml`, `datasheet.md` (source, licence, citation, columns, mapping, representation of protected groups, known biases, who approved), `source.json` |
| Fit | sandbox, synthkit `generation.mode: reference_sample` | Below |

**`reference_sample` fit** (synthkit `reference.py`, deterministic, numpy/pandas only): `mapping.yaml` renames and
recodes the reference to our fields (value maps, age → band bins, optional `scale`). For each mapped field, in
DAG order, categories get P(field | mapped category parents) by counting (Laplace α 0.5; cells under 20 rows
fall back to the marginal) and numbers get empirical quantiles (`dist: empirical`, per parent cell when big
enough). A field is **not** fitted (kept zero-shot, reason recorded) when its column is missing, under 50 % of
its values map, or over 20 % of its numbers fall outside the dictionary range (a semantic or unit mismatch, e.g.
credit-g's `installment_commitment` 1-4 class vs our `debt_to_income` ratio). Unmapped fields keep their
dictionary definition and still condition on the fitted ones; hard rules, strata, boundary sampling, twins and
edge cases run unchanged. The Data Card gets `generation.method: reference_sample`, a `reference` block (source,
licence, sha256, fitted vs zero-shot fields, fit report, dropped PII columns, reference label rate,
`realism_vs_reference`) and `reference_data: public:<licence>`; the realism gate compares the base rows with the
reference as well as with `population.stats`.

Live run on the seed cases (2026-11-14; Firecrawl skipped, no key on this machine):

| Case | Top candidates (score) | Result |
| --- | --- | --- |
| SYS-002 credit | OpenML `credit-g` 0.75 (CC-BY-4.0, mirrored from UCI), UCI Statlog German Credit 0.74 (coded values: needs a value map), HF credit-scoring-training-dataset 0.55 | `reference_sample` from `openml:31`: sex, age_band, loan_amount, loan_term_months fitted; `debt_to_income` refused (range mismatch); TV/KS vs reference 0.95-1.0; the stated 46 % women vs 31 % in credit-g is flagged by the realism gate |
| SYS-003 benefits | UCI Census Income 0.63, UCI Adult 0.60, HF census-income 0.60 | Sex, age, nationality (native-country) and employment status map; household fields stay zero-shot |
| SYS-001 hiring | best 0.38 (HF recruitment profiles) | No good match: `zero_shot` recommended |

### Why profile the model first (P0)

Test data is only useful if it can move the model's decision. Before any spec is drafted, `synthkit profile`
shows what the model really uses. For SYS-001 the model never sees `sex` or `nationality`, so attribute-only
twins would show nothing. `postcode_region` and `career_gap_months` do move the output, and the profile says
so in its notes. The scenarios and spec then ask for causal and proxy-only twins. The boundary estimate makes
the dataset informative: rows far from the threshold rarely flip, so a share of the base rows is chosen near
it (G3), and `analyze` reports that share as *informativeness*. The profile is evidence too: it is
written to `output/`, logged with the run and cited by the Data Card (`inputs_used`).

### Validation gates

| Gate | Checks | Tool | Fail action |
| --- | --- | --- | --- |
| Schema | Types, enums, ranges, required, nullability, model input signature | pydantic / `jsonschema` (from dictionary), pandera for frames | Block |
| Business rules | Every `hard` rule = 0 violations; `soft` rules within declared tolerance | Rule evaluator | Block (hard) / warn (soft) |
| Realism | Marginals and stated stats vs `training-data.md` (e.g. "38% women", "median 6y experience"); pairwise correlations vs declared conditionals; TVComplement, KSComplement, ContingencySimilarity; with a reference sample also SDMetrics quality report | SDMetrics, scipy | Warn + show at HITL (realism is evidence for the critic) |
| Coverage / diversity | Every protected group × outcome-relevant stratum has ≥ `min_per_cell` rows (power for the test's CI); pairwise coverage of persona/edge-case factors; duplicate rate; for text: distinct-n / embedding spread | pandas, allpairspy | Top-up sampling (conditional), else block |
| Privacy | No real PII: names/emails/phones from synthetic sources only, Presidio scan of free text; with a reference sample: DCR (distance to closest record), no exact copies, optional DP synthesizer | Presidio, SDMetrics privacy metrics, smartnoise-synth | Block |

### HITL dataset audit (what the engineer sees)

- The **spec diff** vs the last approved spec for this plugin, with each `llm_assumption` highlighted.
- Gate report (green/amber/red), realism charts per protected attribute, 20 sample rows, 5 twin pairs.
- Buttons: approve · edit spec · regenerate · reject with reason category (`unrealistic_data`, …) → memory proposal
  (e.g. "Synthetic ages must match the applicant population (18–67)").
- Approval stores `dataset_id = sha256(spec + seed + generator_version)`; the dataset is logged to MLflow with the Data Card.

## 3. Strategies

### Per access type

| Access type | Input form | Base generation | Notes |
| --- | --- | --- | --- |
| `mlflow_model` | DataFrame matching the MLflow signature | DAG sampler (fitted to a public reference in `reference_sample` mode) | Check signature vs dictionary at G2; mismatch = ask the engineer |
| `rest` | JSON body per `io.input_schema` / `example_input` | Same rows, rendered to JSON by a field mapping; validate with JSON Schema | Respect `limits` (rps, `max_requests`) when sizing N; cache responses by input hash |
| `llm_chat` | Conversations (single or multi-turn) | Coverage grid persona × intent × attack/edge, LLM writes turns with structured output | Twins by template name/pronoun/dialect swap; judge per rubric (below) |
| `batch_file` | File in the target's format (CSV/JSONL) | As `mlflow_model`, written to file; one file per test | Hash the file into the Data Card |
| `dataset_only` | No model: audit the data itself (Art. 10) | No generation for the main test; synthetic only as a *reference population* to compare representativeness | Tests: representation, label rates by group, missingness by group, proxy strength (mutual information protected ↔ feature) |

### Per test template

| Template | Data recipe | Metric (examples) |
| --- | --- | --- |
| Group fairness | Stratified sample: fixed `min_per_cell` per protected group (and intersections if N allows), other fields from the DAG *conditioned on the group* (realistic population, not identical copies) | Selection rate ratio, equal opportunity diff (needs a synthetic ground-truth label from a declared `label_rule`), CI by bootstrap |
| Counterfactual twins | For each base row, flip one protected attribute in two modes: **(a) ceteris paribus** (only the attribute changes) and **(b) causal** (re-sample its descendants in the DAG, e.g. `postcode_region`, name). Plus **proxy-only twins** (flip the proxy, keep the attribute). Name-swap for text inputs | Flip rate, mean score delta, max delta; (a) tests direct use, (b) and proxy-only expose proxy discrimination (SYS-001) |
| Search-based discrimination | Start from twins; then search (ExpGA/Aequitas-style: random global + local perturbation around discriminatory seeds) inside rule-valid space only | Number of discriminatory instances per 1k queries; reported as *found* instances, not a rate |
| Accuracy per subgroup | Rows with ground truth from `label_rule` (deterministic, from the spec) or from an upstream labelled test set; stratified as group fairness | Accuracy/F1/AUC per group, gap, CI |
| Perturbation / robustness (Art. 15) | Metamorphic relations from `expected_behaviour.must` (e.g. "same input → same score", "+1 year experience never lowers score" if declared monotone); small noise on numeric fields within rules; typos/format variants on text | Violation count per relation, score stability |
| Edge cases | Boundary values (min, max, min−1, max+1 via Z3 so other rules still hold), missing fields per `nullable`, out-of-range, wrong types, very long/empty text, non-English text (from `known_limitations`) | Error handling: graceful error vs crash vs silent garbage |
| Adversarial (stretch) | ART evasion attacks (HopSkipJump, boundary) for tabular; for LLM apps garak / PyRIT / promptfoo red-team plugins (prompt injection, jailbreak, PII leak) | Attack success rate |

### LLM chat apps

- **Grid:** personas (from `scenarios.personas`, LLM expands each into a short profile) × intents (from
  `expected_behaviour.task`) × modifiers (edge cases, attack families). Pairwise coverage (allpairspy) keeps it small.
- **Fairness:** same conversation, names/pronouns/dialect swapped by template (GenFair/CAFFE-style metamorphic tests).
- **Judging:** deterministic checks first (regex, JSON validity, refusal markers), then LLM-as-judge with a rubric
  per `must`/`must_not` item, score + quote of evidence; calibrate on 10 human-labelled samples; the critic re-judges
  disagreements. Judge model ≠ target model.

### Pipelines of models (`placement`)

| Mode | How | Finds |
| --- | --- | --- |
| Stage alone | Generate in the stage's *input* schema (= upstream's output schema) | Bias added by this stage |
| End to end | Generate the structured row, then **render** it into the raw input of `end_to_end_entry` (row → CV text/PDF by LLM), keep the row as ground truth | Bias of the whole chain; plus upstream extraction error (parsed vs ground-truth row) |
| Both (default for high-risk) | Same base rows for both modes | Which stage introduces the gap |

## 4. Additions to `data-dictionary.yaml`

New keys (all optional except `type`): per field `nullable`, `range`, `values` + `distribution`, `depends_on` +
`conditional`, `source` (Faker/Mimesis/list/llm_text), `role` (`protected | proxy | feature | label | id | surface`),
`provenance`, `monotone`; file-level `rules` (hard/soft, safe expressions), `label_rule`, `population` (stats from
`training-data.md`, for the realism gate) and `dag` order implicitly from `depends_on`.

```yaml
# /systems/SYS-001/plugins/ranker/data/data-dictionary.yaml
version: 2
population:                         # stated in training-data.md; realism gate compares against these
  n_described: 48000
  period: 2019-2024
  stats: {sex.female: 0.38, years_experience.median: 6, nationality.non_eu: 0.12}
fields:
  sex:
    type: category
    role: protected
    values: [female, male]
    distribution: {female: 0.38, male: 0.62}
    provenance: training_doc
  age_band:
    type: category
    role: protected
    values: ["18-24", "25-34", "35-44", "45-54", "55-67"]
    distribution: {"18-24": 0.14, "25-34": 0.41, "35-44": 0.27, "45-54": 0.13, "55-67": 0.05}
  nationality:
    type: category
    role: protected
    values: [GR, EU_other, non_EU]
    distribution: {GR: 0.80, EU_other: 0.08, non_EU: 0.12}
  postcode_region:
    type: category
    role: proxy                     # proxy_for: nationality (declared in scenarios.known_proxies)
    proxy_for: [nationality]
    values: [athens_centre, athens_north, athens_west, piraeus, thessaloniki, other]
    depends_on: [nationality]
    conditional:                    # P(postcode_region | nationality)
      GR:       {athens_centre: 0.15, athens_north: 0.30, athens_west: 0.15, piraeus: 0.10, thessaloniki: 0.20, other: 0.10}
      EU_other: {athens_centre: 0.35, athens_north: 0.30, athens_west: 0.10, piraeus: 0.05, thessaloniki: 0.15, other: 0.05}
      non_EU:   {athens_centre: 0.30, athens_north: 0.05, athens_west: 0.40, piraeus: 0.15, thessaloniki: 0.05, other: 0.05}
    provenance: llm_assumption      # shown highlighted at the dataset audit
  education:
    type: category
    values: [secondary, bachelor, master, phd]
    depends_on: [age_band]
    conditional:
      "18-24":   {secondary: 0.45, bachelor: 0.50, master: 0.05, phd: 0.00}
      default:   {secondary: 0.15, bachelor: 0.45, master: 0.32, phd: 0.08}
  years_experience:
    type: integer
    range: [0, 45]
    depends_on: [age_band, education]
    conditional: {dist: poisson, mean_expr: "max(0, age_min(age_band) - 22) * 0.7"}
    monotone: increasing            # metamorphic relation: more experience must not lower the score
  career_gap_months:
    type: integer
    role: proxy
    proxy_for: [sex, age_band]
    range: [0, 120]
    nullable: true                  # null = no gap
    depends_on: [sex]
    conditional:
      female: {p_zero: 0.55, dist: lognormal, median: 14}
      male:   {p_zero: 0.80, dist: lognormal, median: 8}
  full_name:
    type: string
    role: surface                   # not a model feature for the ranker; used when rendering CVs end to end
    source: {kind: faker, locale_from: nationality, locale_map: {GR: el_GR, EU_other: [de_DE, it_IT, fr_FR], non_EU: [ar_AA, hi_IN, en_PH]}}
rules:
  - id: R1
    severity: hard
    expr: "years_experience <= age_max(age_band) - 16"
    why: "Nobody works before 16"
  - id: R2
    severity: hard
    expr: "career_gap_months is null or career_gap_months <= years_experience * 12 + 24"
  - id: R3
    severity: hard
    expr: "not (education == 'phd' and age_band == '18-24')"
  - id: R4
    severity: soft
    tolerance: 0.05
    expr: "not (education == 'secondary' and years_experience == 0 and age_band in ['45-54', '55-67'])"
label_rule:                         # synthetic ground truth for equal opportunity / accuracy per group
  name: qualified
  expr: "years_experience >= 3 and education in ['bachelor', 'master', 'phd']"
  provenance: declared_by_human     # must be human-approved; never inferred silently
```

Expression language: comparisons, `and/or/not`, `in`, `is null`, arithmetic, `min/max/abs` and declared helper
functions (`age_min`, `age_max`). Parsed by a whitelist evaluator; the LLM can propose rules but cannot run code.

Proposed `plugin.yaml` additions under `scenarios`: `generation: {mode: zero_shot | reference_sample, seed, min_per_cell, n_max}`
and `metamorphic_relations: [...]` (or derive from `monotone` + `expected_behaviour.must`).

## 5. Data Card schema

```yaml
# DataCard.yaml, one per dataset, logged to MLflow next to the dataset
dataset_id: ds-sha256:…            # hash(spec + seed + generator_version)
name: SYS-001.ranker.counterfactual-twins
created_at: 2026-11-15T10:12:00Z
run_id: run-…
trace: langfuse:<trace id>
purpose:
  test_spec: TS-004
  template: counterfactual_twins
  requirements: [REQ.AIA.10.2.f.bias-examination, REQ.AIA.15.1.accuracy]
  kb_version: 2026.11.14-1
target: {plugin: SYS-001.ranker, card_version: 3, dossier_version: 7, access_type: mlflow_model}
inputs_used:                        # files read, with versions (pins replay)
  - {path: /systems/SYS-001/plugins/ranker/data/data-dictionary.yaml, version: 2}
  - {path: /systems/SYS-001/plugins/ranker/data/training-data.md, version: 1}
memory_applied: [MEM-0057]
generation:
  method: dag_sampler               # dag_sampler | reference_sample | llm_text | template
  generator_version: synth 0.1.0
  seed: 1729
  spec: spec/TS-004.generation.yaml
  llm: {model: <id>, used_for: [spec_draft, cv_text], prompts: langfuse:<ids>}
  assumptions:                      # every llm_assumption in the spec
    - {field: postcode_region, what: "P(region | nationality)", provenance: llm_assumption}
composition:
  rows: 2400
  pairs: 1200
  strata: {sex: {female: 600, male: 600}, nationality: {GR: 400, EU_other: 400, non_EU: 400}}
  transforms: [ceteris_paribus_flip:nationality, causal_flip:nationality, proxy_flip:postcode_region]
  label: {name: qualified, rule: "…", positive_rate: 0.46}
gates:
  schema: {status: pass}
  business_rules: {status: pass, hard_violations: 0, soft_violations: {R4: 0.01}, rejected_rows: 37}
  realism: {status: warn, metrics: {TVComplement.sex: 0.97, KSComplement.years_experience: 0.88}, note: "non_EU oversampled by design"}
  coverage: {status: pass, min_cell: 50}
  privacy: {status: pass, real_pii: false, pii_scan: presidio, dcr_min: null, dp: null}
limitations:
  - "No reference sample: realism checked only against stated statistics in training-data.md"
  - "Groups deliberately balanced; rates are not population rates"
data_policy: synthetic_only
review:
  status: approved                  # proposed | approved | rejected
  by: engineer:alice
  at: 2026-11-15T10:20:00Z
  comments: ""
storage: {mlflow_dataset: mlflow-dataset://…, sha256: …}
```

## 6. Libraries for the sandbox image

| Library | For | Licence | Maturity | Cut |
| --- | --- | --- | --- | --- |
| numpy, pandas, scipy | DAG sampling, stats, KS/TV tests | BSD | Stable | **MVP** |
| pydantic, jsonschema | Spec + row schema validation | MIT | Stable | **MVP** |
| pandera | DataFrame schemas from the dictionary | MIT | Stable | **MVP** |
| simpleeval (or our own small parser) | Safe rule expressions | MIT | Stable, small | **MVP** |
| Faker | Names, addresses per locale | MIT | Stable | **MVP** |
| fairlearn | MetricFrame, selection rate, equalized odds | MIT | Stable | **MVP** |
| sdmetrics | Realism metrics (TVComplement, KSComplement, quality report) | MIT | Stable | **MVP** |
| allpairspy | Pairwise coverage of persona/edge factors | MIT | Stable, small | **MVP** |
| z3-solver | Boundary rows that still satisfy all other rules; repair | MIT | Stable | Later (MVP: closed-form boundaries) |
| SDV (GaussianCopula, CTGAN, TVAE, CAG constraints) | Base population from a reference sample | **BSL 1.1** (check terms; some constraints are Enterprise-only) | Stable | Not used: `reference_sample` fits the DAG itself (numpy/pandas) |
| synthcity | Alternative generators incl. DP and fairness-aware | Apache-2.0 | Research-grade | Later |
| smartnoise-synth | DP synthesizers (MST, AIM) when a real sample is used | MIT | Stable | Later |
| Mimesis | Faster Faker alternative, more locales | MIT | Stable | Later |
| presidio-analyzer | PII scan of generated text | MIT | Stable | Later (MVP: no free text with PII sources) |
| great_expectations | Heavier data-quality suites | Apache-2.0 | Stable, heavy | Later (pandera is enough) |
| hypothesis | Property-based perturbation search | MPL-2.0 | Stable | Later |
| aif360 | Extra fairness metrics, reweighing | Apache-2.0 | Stable, slow-moving | Later |
| adversarial-robustness-toolbox (ART) | Evasion attacks on tabular models | MIT | Stable | Later (stretch) |
| garak | LLM vuln scanner (injection, leakage) | Apache-2.0 | Active | Later (`llm_chat`) |
| PyRIT | Multi-turn red-teaming orchestration | MIT | Active | Later (`llm_chat`) |
| promptfoo | Red-team plugins + LLM-judge evals (Node) | MIT | Active | Later (`llm_chat`, separate image) |
| giskard | LLM scan + RAG eval | Apache-2.0 | Active | Later |
| deepeval | LLM-as-judge metrics (G-Eval) | Apache-2.0 | Active | Later |

The sandbox has no internet: LLM calls (spec drafting, CV text) happen in the `agents` service, not the sandbox; the
sandbox receives the approved spec and runs only deterministic code.

## 7. Hackathon MVP cut (~6 h)

| Build now | Later |
| --- | --- |
| GenerationSpec JSON Schema + LLM drafting step (structured output) for SYS-001/SYS-002 | SDV/CAG path for reference samples, DP |
| DAG ancestral sampler (categorical conditionals, poisson/lognormal/normal, `p_zero`) | CTGAN/TVAE, LLM fine-tuned generators |
| Rule evaluator (hard = resample/reject, soft = tolerance) | Z3 repair and boundary construction |
| Twins: ceteris paribus, causal (re-sample descendants), proxy-only | ExpGA-style search, CausalFT-style causal perturbation |
| Edge cases: min/max/null/out-of-range per field | Metamorphic suites from `monotone`, Hypothesis |
| Gates: schema (pandera), rules, realism vs `population.stats` (TV/KS), min cell coverage, "no PII source" check | Presidio, DCR, full SDMetrics reports, embedding diversity |
| Data Card YAML + MLflow log; HITL audit shows spec assumptions, gate report, 5 twin pairs | `llm_chat` grid, red-team tools, LLM judge calibration, end-to-end CV rendering |

Demo: the causal twin flip on `nationality` (postcode re-sampled) shows a score gap while the ceteris-paribus flip
shows none, which is exactly the SYS-001 proxy story; the Data Card and Langfuse trace show how the data was made.

## 8. Sources

- SDV constraint-augmented generation (CAG): <https://docs.sdv.dev/sdv/concepts/constraint-augmented-generation-cag/predefined-constraints/fixedcombinations>, <https://docs.sdv.dev/sdv/concepts/constraint-augmented-generation-cag/predefined-constraints/range>
- SDMetrics: <https://docs.sdv.dev/sdmetrics>
- GReaT, "Language Models are Realistic Tabular Data Generators" (ICLR 2023): <https://arxiv.org/abs/2210.06280>
- TabuLa: <https://arxiv.org/abs/2310.12746>
- CLLM, "Curated LLM: synergy of LLMs and data curation for tabular augmentation in low-data regimes" (ICML 2024): <https://arxiv.org/abs/2312.12112>
- Tabby (2025): <https://arxiv.org/abs/2503.02152>; LLM-TabLogic / LLM-TabFlow (Long et al., 2025, inter-column logic; link not verified, search arXiv)
- Survey: LLMs on tabular data: <https://arxiv.org/abs/2402.17944>; deep tabular generation survey (2025): <https://arxiv.org/abs/2503.05954>
- FairCauseSyn, causally fair LLM-augmented synthetic data (2025): <https://arxiv.org/abs/2506.19082>
- Themis, fairness testing: <https://arxiv.org/abs/1709.03221>; Aequitas (Udeshi et al.): <https://arxiv.org/abs/1807.00468>; ExpGA (ICSE 2022): <https://doi.org/10.1145/3510003.3510137>
- Causally Perturbed Fairness Testing (CausalFT, 2025): <https://arxiv.org/abs/2510.18719>
- GenFair, metamorphic fairness tests for LLMs (2025): <https://arxiv.org/abs/2506.03024>; CAFFE counterfactual fairness for LLMs (2025): <https://arxiv.org/abs/2512.16816>
- Fairlearn: <https://fairlearn.org>; AIF360: <https://github.com/Trusted-AI/AIF360>; ART: <https://github.com/Trusted-AI/adversarial-robustness-toolbox>
- garak: <https://github.com/NVIDIA/garak>; PyRIT: <https://github.com/Azure/PyRIT>; promptfoo: <https://github.com/promptfoo/promptfoo>; Giskard: <https://github.com/Giskard-AI/giskard>; DeepEval: <https://github.com/confident-ai/deepeval>
- Z3: <https://github.com/Z3Prover/z3>; OR-Tools: <https://developers.google.com/optimization>; Faker: <https://github.com/joke2k/faker>; Mimesis: <https://github.com/lk-geimfari/mimesis>
- pandera: <https://pandera.readthedocs.io>; Great Expectations: <https://greatexpectations.io>; Presidio: <https://github.com/microsoft/presidio>; SmartNoise: <https://github.com/opendp/smartnoise-sdk>; synthcity: <https://github.com/vanderschaarlab/synthcity>
- Datasheets for Datasets (Data Card basis): <https://arxiv.org/abs/1803.09010>; Google Data Cards Playbook: <https://sites.research.google/datacardsplaybook/>
- EU AI Act Art. 10 and 15 (consolidated text in `reg-memory`): <https://eur-lex.europa.eu/eli/reg/2024/1689/oj>
