# Agent context and memory

> Status: **design, not built yet**. This page extends the design PDF (§5.5 precedents, §12 MVP) to the
> engineer pipeline. Keep it current as we build.

Before the agent audits a system it needs four things:

1. **The rules:** what the regulation says (`reg-memory`).
2. **The system:** everything known about the system being audited (the **system dossier**, "the folder").
3. **The targets:** one **plugin** per model or endpoint: how to reach it, where it sits in the pipeline,
   what it should do, plus any docs and training-data descriptions added when the plugin was configured.
4. **The lessons:** what humans corrected before, for this system and for the whole organisation
   (**agent memory**, audited).

All four reach the agent the same way: as **files in a virtual filesystem stored in Postgres** (section 5).
The agent reads them with its normal file tools, and every file has an owner, a version and an audit trail.
`load_context` merges them into one run context. Every later step (scenarios, use cases, synthetic data,
tests, findings) uses it and cites the files it relied on.

![Agent context and memory](diagrams/agent-context.png)

## 1. `reg-memory`: all the regulation, in one place

The Regulatory Knowledge Service (RKS) holds **all** regulatory knowledge, versioned as one `kb_version`:

| Content | Binding | Notes |
| --- | --- | --- |
| AI Act, consolidated (post-Omnibus) | yes | Main working text, verbatim, one node per article / paragraph / point |
| Digital Omnibus on AI (Reg. (EU) 2026/1744) | yes | Provenance of amendments and new dates |
| Commission guidelines (AI system definition, prohibited practices, Art. 6) | no | Interpretations and worked examples |
| AI Act Service Desk FAQs, codes of practice | no | Watched for changes |
| Harmonised standards (CEN-CENELEC JTC 21) | n/a | Status and metadata only |
| National implementing law | yes | When available |
| Organisation's internal AI policies | internal | Stored as interpretations with `binding: internal` |
| Requirements, test templates | derived | Extracted from the above, human-checked |

Rules:

- **Agents only read it**, at `/regulation/` pinned to the run's `kb_version`. Changes come only through the
  watcher → diff → HITL accept (see [README § Regulation change](README.md#regulation-change--re-review-pdf-126)).
- Every provision carries `provision_id` + `kb_version`, so every finding can say which text it used.
- Agent memory (section 4) is **not** stored here: the RKS holds what the law says; memory holds how *we* apply it.

## 2. System dossier: "the folder" of an audited system

One versioned folder per system, with everything the agent needs about it. It is mounted read-only at
`/systems/<SYS-ID>/`:

```text
/systems/SYS-001/
├── system-card.yaml          # identity, role, risk class + basis, purpose, deployment, affected persons,
│                             # protected attributes, known proxies, declared metrics, org thresholds
├── architecture.yaml         # components and how they connect (the pipeline graph of plugins)
├── docs/                     # system-level docs: specs, instructions for use, DPIA/FRIA, policies
├── plugins/                  # one folder per configured plugin (section 3)
│   ├── cv-parser/
│   └── ranker/
├── evidence/                 # previous test runs (MLflow refs), findings, reports
└── gaps.yaml                 # open obligations without evidence
```

- **Versioned:** each audit locks `dossier_version` (with `card_version` and `kb_version`); findings record all three.
- **Provenance per fact:** `declared_by_human | extracted_from:<file> | estimated_by_agent`, as in the PDF §5.1.
- **Completeness check first:** if fields that the requirements need are missing, the agent asks for them
  before planning (HITL), instead of guessing.

## 3. Plugins: how to reach a model, what it is, what it should do

A **plugin** connects the agent to one testable thing: a model, an endpoint, an LLM app or a dataset. A system
can have several (a pipeline of models). When an engineer **configures a plugin** they:

1. pick the access type (MLflow model, REST endpoint, LLM chat, batch file, dataset only);
2. fill in the **target card** (`plugin.yaml`): access, place in the pipeline, inputs and outputs, expected behaviour;
3. **add any files the agent should read**: API docs, model card, training-data description, data dictionary,
   evaluation reports, known issues, free-text notes.

Everything is stored as one folder:

```text
/systems/SYS-001/plugins/ranker/
├── plugin.yaml               # the target card (below)
├── README.md                 # plain description: what this model does and why
├── docs/                     # API docs, model card, eval reports, known issues
├── data/
│   ├── training-data.md      # datasheet: sources, period, size, populations, labels, known biases
│   ├── data-dictionary.yaml  # features: type, range, meaning, protected / proxy flags
│   └── sample.csv            # optional synthetic or anonymised sample (never real personal data)
└── notes/                    # anything else the engineer wants the agent to know
```

The target card:

```yaml
# plugin.yaml
id: SYS-001.ranker
system: SYS-001
name: Candidate ranker
card_version: 3

# Where it sits
placement:
  kind: pipeline_stage              # standalone | pipeline_stage | ensemble_member | whole_system
  position: 2 of 3
  upstream: [SYS-001.cv-parser]     # produces this target's input
  downstream: [SYS-001.recruiter-ui]
  pipeline_summary: "CV parser → ranker → recruiter reviews the shortlist"
  end_to_end_entry: SYS-001.cv-parser   # call this one to test the whole chain

# How to reach it
access:
  type: mlflow_model                # mlflow_model | rest | llm_chat | batch_file | dataset_only
  uri: models:/cv-screener/3
  # type: rest
  # url: https://staging.example.internal/rank
  # method: POST
  # auth: {type: bearer, secret_ref: vault://targets/sys-001-ranker}   # a reference, never the secret
  environment: staging              # production needs explicit approval at the test-plan gate
  limits: {rps: 5, max_requests: 5000, timeout_s: 10}

# What goes in and out
io:
  input_schema: data/data-dictionary.yaml   # or from_mlflow_signature, or an inline JSON Schema
  example_input: docs/example-input.json
  output: {type: binary_classification, positive_label: shortlist, score_field: proba}

# What it should do (drives scenarios and pass/fail)
expected_behaviour:
  task: "Rank applicants for engineering roles; a recruiter reviews every shortlist"
  must: ["score in [0, 1]", "same input → same score"]
  must_not: ["use protected attributes directly", "auto-reject without human review"]
  known_limitations: ["CVs not in English are under-scored"]

# Hints for scenario and data generation
scenarios:
  personas: [junior engineer, career returner, non-EU applicant, senior with gaps]
  edge_cases: [missing fields, very long CV, non-English CV, out-of-range years]
  protected_attributes: [sex, age_band, nationality]
  known_proxies: [postcode_region, career_gap_months]
  training_data: data/training-data.md
  reference_sample: mlflow-dataset://cv-sample-v1      # optional, for SDV
  data_policy: synthetic_only                          # never send real personal data
```

How the agent uses a plugin:

| Step | Reads from the plugin |
| --- | --- |
| `plan_tests` | `placement` (test the stage alone, the whole chain, or both), `expected_behaviour`, `README.md`, `docs/` → which requirements apply and which templates fit |
| `generate_data` | `data/data-dictionary.yaml`, `data/training-data.md`, `example_input`, `scenarios.*` → personas, use cases, edge cases and counterfactual twins that are valid inputs and realistic against the training population |
| `execute` | `access.type` picks the sandbox adapter (MLflow load, HTTP, LLM chat, batch, dataset-only); `limits` set rate and volume |
| `analyse` / `critic` | `io.output` to read results; `must` / `must_not` as checks; `known_limitations` and the training-data description as counter-evidence ("synthetic population differs from training data") |

Security rules:

- **Secrets are references only** (`secret_ref`). The sandbox runner resolves them; the LLM never sees them,
  and plugin files are checked so no raw credential is stored.
- The sandbox's network egress is allow-listed to the target's host and MLflow only.
- Production endpoints, or anything over `max_requests`, need approval at the test-plan gate (G5).

## 4. Agent memory: general and per system, fully audited

The agent improves from human feedback without retraining. When the engineer or the AI Officer approves,
edits or rejects something, the reason is stored as **memory**: a file in Postgres. Later runs read it and
**cite** it.

### Two scopes

| Scope | Path | Example | Who approves it |
| --- | --- | --- | --- |
| **Per system** | `/memory/systems/SYS-001/` | "SYS-001: `postcode_region` is a proxy for nationality; always include it in counterfactual tests" | Engineer of that system |
| **General (org)** | `/memory/org/` | "For hiring systems, use equal opportunity, not demographic parity, as the primary fairness metric" | AI Officer, after a regression check on the eval set |

Per-system entries can be **promoted** to general. Promotion is a separate, logged decision.

### Where feedback comes from

| Trigger | Typical memory |
| --- | --- |
| Test-plan gate: test removed, added or edited | "Don't run adversarial tests on rule-based components" |
| Dataset audit: dataset rejected or regenerated | "Synthetic ages must match the applicant population (18–67)" |
| Finding overridden by a human | "Gap at ratio 0.78 is inconclusive when the CI crosses 0.8" |
| Change judge overridden | "Changes to Annex III §4 always mean `rerun_tests` for hiring systems" |
| Endpoint behaviour discovered during a run | "Ranker returns 429 above 5 rps" (system quirk, per system) |
| Like / dislike on a chat answer (already stored by the backend) | Low-weight signal; only becomes memory if a human writes a reason |

Every rejection asks for a **reason category** (`wrong_fact`, `wrong_interpretation`, `missing_info`,
`wrong_metric`, `unrealistic_data`, `org_policy`, `other`) plus free text.

### Memory files

Each entry is one file; each scope folder has an `INDEX.md` the agent reads first (one line per active entry):

```text
/memory/
├── org/
│   ├── INDEX.md
│   └── MEM-0042.yaml
├── systems/
│   └── SYS-001/
│       ├── INDEX.md
│       └── MEM-0057.yaml
└── proposals/               # the only place an agent may write: suggested entries, inactive until approved
```

```yaml
# /memory/org/MEM-0042.yaml
id: MEM-0042
scope: org                       # or: system:SYS-001
kind: precedent                  # correction | precedent | preference | quirk
applies_to: {step: plan_tests, requirement: REQ.AIA.10.2.f.bias-examination, sector: hiring}
proposed: "Primary metric: demographic parity"
human_decision: "Primary metric: equal opportunity"
reason_category: wrong_metric
rationale: "For shortlisting, qualified candidates must have equal chances; base rates differ by design."
author: engineer:alice
approved_by: ai-officer:bob      # engineer:<id> is enough for system scope
promoted_from: MEM-0039          # the per-system entry it generalises
status: active                   # proposed | active | retired | stale
kb_version: 2026.11.14-1
card_version: 3
source_trace: langfuse:<trace id>
supersedes: null
```

### Lifecycle

```text
human feedback at a gate → proposed → active (per system) ──promote + AI Officer + regression check──→ active (org)
                                         │
                       law change touching its provisions → stale (re-review)   ·   retire / roll back at any time
```

- **Agents never write active memory.** They can only write to `/memory/proposals/`; a human activates an entry,
  which moves it into its scope folder.
- An entry becomes **stale** when a regulation change touches a provision it relies on (same impact index as findings).

### How it is used

Before `plan_tests`, `generate_data`, `critic` and the change judge, the agent reads the system's `INDEX.md` and
**all active per-system entries**, plus the **top matching general entries** (by step, requirement and sector,
then similarity). They go into the prompt as numbered, citable items. When an entry changes what the agent
does, the output must cite it ("applied MEM-0042"), so the human sees *why* the plan differs.

### Audit

- **Append-only:** files are never edited in place. Every write creates a new version of the file, and every
  create, approve, promote, retire, stale and **every read during a run** is an event with who, what, why and when.
- **In the trace:** each memory read and use is a Langfuse span tagged with the memory ids, so a replayed run
  shows exactly which lessons shaped it.
- **Reviewable:** a memory view per system and for the org, filterable by status, author, reason, and usage
  count; any entry can be retired or rolled back to an earlier version.
- **Measured:** feedback is also written as Langfuse scores. We track rejection rate per step before vs after
  memory, and run the golden set as a regression gate before a general entry goes active.

## 5. The filesystem (stored in Postgres)

The agents service already exposes Postgres rows as files through one `CompositeBackend`
([agents service § Filesystem](../services/agents-service.md#filesystem)): `/conversation/…` paths are
`conversation_files` rows over encrypted, content-addressed blobs. We add these routes the same way:

| Path the agent sees | Backed by | Agent can write | Who writes it | Versioned |
| --- | --- | --- | --- | --- |
| `/regulation/` | RKS corpus, pinned to the run's `kb_version` | no | watcher + HITL (RKS) | per `kb_version` |
| `/systems/<SYS-ID>/` | `workspace_files`, namespace `system:<id>` | no | PM / AI Officer / engineer (UI, uploads) | per `dossier_version` |
| `/systems/<SYS-ID>/plugins/<plugin>/` | `workspace_files`, namespace `plugin:<system>/<plugin>` | no | engineer, when configuring the plugin | per `card_version` |
| `/memory/systems/<SYS-ID>/` | `workspace_files`, namespace `memory:system:<id>` | no | engineer approves | every write |
| `/memory/org/` | `workspace_files`, namespace `memory:org` | no | AI Officer approves | every write |
| `/memory/proposals/` | `workspace_files`, namespace `memory:proposals` | **yes** | agents (suggestions only) | every write |
| `/conversation/…`, scratch | existing tables (unchanged) | as today | as today | as today |

Tables (backend Postgres, one Alembic migration):

| Table | Holds |
| --- | --- |
| `workspace_file_blobs` | Content once per hash (`sha256`), AES-encrypted like conversation blobs |
| `workspace_files` | `(namespace, path, version)` → blob, plus `content_type`, `created_by`, `created_at`, `is_current`. A new version is a new row; old rows stay |
| `workspace_file_meta` | Indexed fields parsed from structured files (memory `scope`, `status`, `kind`, `applies_to`, `kb_version`; plugin `access.type`) and a pgvector embedding for similarity search |
| `workspace_events` | Append-only audit ledger: `(namespace, path, version, action, actor, reason, run_id, trace_id, at)`. Actions include `create`, `update`, `approve`, `promote`, `retire`, `stale`, `read` |

- **Mounting:** the backend passes the system id in the run's config; the agents service mounts
  `/systems/<id>/`, `/memory/systems/<id>/`, `/memory/org/` and `/regulation/` for that run only. A run never
  sees another system's files.
- **Pinning:** a run reads the versions current at its start and records them in the trace, so a replay sees
  exactly the same files.
- **Reads are logged** (`read` events), so the audit can show which files an audit actually used.
- **Uploads:** files added in the UI (plugin docs, training-data descriptions) go through the same checks as
  conversation uploads (hash, size limit, safe names), then into `workspace_files`.

## Demo moment

1. The engineer configures the `ranker` plugin: picks MLflow, fills the card, uploads the training-data
   description. The agent generates personas and counterfactual twins that match that population.
2. They reject a fairness test on SYS-001 ("wrong metric for hiring") → `/memory/systems/SYS-001/MEM-0039.yaml`.
3. They promote it; the AI Officer approves → `/memory/org/MEM-0042.yaml`.
4. A new hiring system is planned correctly first time, the plan cites `MEM-0042`, and the Langfuse trace and
   the file history show where the lesson came from and who approved it.

## Open questions

- Who may promote to general memory besides the AI Officer (a second reviewer)?
- How many general entries to inject per step before the prompt gets noisy (start with top 5)?
- Do quirks discovered automatically need approval, or only a notification?
- Does `/regulation/` read from RKS through an API at mount time, or does the RKS publish each `kb_version` into `workspace_files`?
