# Frontend: audit workflow UX

The audit-workflow pages of `mnamon/frontend/` (see the frontend page for the scaffold, information
architecture, design rules and mock mode). Three features, each `src/features/<feature>/{components,hooks,handlers,lib,pages}`;
pages are mounted by thin route views in `src/pages/*View.tsx`. Agent memory is not shown in the UI: the agents
decide what to remember.

| Route | Feature | What |
| --- | --- | --- |
| `/audits` | `audits` | Audit runs table: system and title, id, kb_version, trace, current step (live spinner or status), trigger, progress bar, updated |
| `/audits/:auditId[?step=<stage>]` | `audits` | **Audit run page** (below); `?step=` deep-links and pins a step |
| `/approvals` | `approvals` | Inbox of every open HITL gate; opens the approval drawer |
| `/regulation?tab=changes\|sources&source=…` | `regulation` | Regulation-change inbox and reg-memory sources with versions, text and diffs |

## Audit run page

- **Header**: system · title, status, labels (system, kb, card version, trigger) and *Full trace*, *Replay run* or
  *Review & decide*. **No raw UUIDs or hashes are printed anywhere** (`shared/lib/labels.ts`): a readable audit id
  (`SYS-002-20261115-0930`) shows as is, an older UUID audit as `<SYSTEM_ID> · <started>`; actors show a role
  (`client:<uuid>` → "Engineer"), dataset content hashes, MLflow run ids and check ids are hidden; Langfuse links keep
  the trace id only in the href. A finished run adds a summary strip: gaps, supports, inconclusive, not assessable,
  total agent time.
- **The pipeline graph** (`PipelineFlow`, React Flow, at 1024 px and wider), ported from mAgenticX's workflow
  run view (node card, edges, status language; `styles/audit-flow.css`) onto the brand tokens. The 14 steps of
  `lib/pipeline.ts` (`STAGES`) sit in three phase lanes that fill the card (`lib/graph.ts: laneLayout`), drawn at
  zoom 1 so card text is its real size: Understand & plan (`load_context → profile_model → plan_scenarios →
  analyse_scenarios → ⏸ approve_scenarios`), Synthetic data (`find_public_data ⏸ → draft_spec → generate_data →
  analyse_datasets → ⏸ approve_datasets`), Test & judge (`run_tests → analyse → critic → report`). Each lane
  shows its done count and hands over to the next with a chevron. A card (`pipeline_parts/StepCard`) has a step
  icon, its title and one line on what it produced (`lib/stepMeta.ts: stepSummary`, e.g. "28 requirements · 15
  testable", "3,654 rows · 3,123 twins"), and a status chip. Done steps have a check, a running step a light
  travelling round its border, a waiting gate an amber pulse with *Review & decide* inside the card, a failed
  step is red and pending steps are dimmed. Gates use the approval chrome (amber, hand tile, pill shape, dashed
  until reached). Edges are short beziers down each lane: solid primary when done, flowing dashes into the live
  step, faint dashes ahead. A **redo loop** (`redo ×n`) arcs back on the right when a gate rejection or a
  verifier redo sent a step back. Cards are focusable; Enter or a click opens the step, and the selected card
  gets a primary ring. Reduced motion stops every animation. Below 1024 px the page uses the same cards as a
  vertical stepper grouped by phase (`AuditPipeline`). The card header (`PipelineHeader`) shows a run chip
  (Live, Waiting for you, Finished, Failed), "Step n of 14", a progress bar and *Follow live*.
- **Step panel** (below the graph): step header ("Step n of 14", duration, trace link), then **step facts**
  (`StepFacts`): status, timestamps, memory read (`memory_applied`) and written (`lessons_recorded`), redo
  history (every version of the artifact the step rewrites), gate decisions (decision, reason, comment, who, when),
  the scenario relevance review on the scenario steps, and on `find_public_data` the scenarios that drove the
  dataset search (the artifact's own list, else derived from the fields the scenarios need).
- **The selected step's artifacts**, after the facts; every artifact goes through `lib/adapters.ts`, which maps the
  pipeline's snake_case shapes (and the mock shapes) onto the view models with lenient Zod parsing, so a missing
  field renders "–" and never crashes; latest non-superseded version per `kind/name`, with version, status and author. A running step shows a
  spinner over a skeleton of the artifact:
  - `context`: system, requirements (test vs document review), plugins, files read with versions.
  - `model_profile`: feature-sensitivity bar chart (neutral bars; protected proxies in amber with ⚠, so the problem
    reads at a glance), decision-boundary flip rates.
  - `scenarios` / `scenario_analysis`: test table; coverage per requirement, diff vs last plan, risks, not-testable list.
  - `generation_spec`: YAML with each node's `provenance` block tinted (`dictionary`, `training_doc`, `business_rule`), `llm_assumption` in amber, plus the assumption list and the spec diff.
  - `dataset_analysis`: the five gates as calm cards (status icon + label, the gate's note; warn/fail get a tinted border; metrics in tooltips), coverage heatmap (teal tint by count, cells under `min_per_cell` ringed red), twin modes a/b/c with mean Δ (red when the CI excludes 0), flip rate and CI, and a side-by-side twin-pair viewer.
  - `public_dataset_candidates`: recommendation, sources searched, one card per candidate (score, licence, rows,
    mapped fields, missing protected attributes).
  - `dataset`: Data Card summary (rows, composition, twins per mode, population vs training-data.md, sample rows).
  - `test_result`: one row per test and metric (value, CI, threshold, status).
  - `scenarios`: each scenario's relevance review when present: "Reviewed by Iris (Oumi)" or "Reviewed by Gemini",
    verdict `relevant | needs_change | not_relevant`, rationale and suggested change; `memory_applied` shows as a
    "learned from memory" citation.
  - `finding`: one artifact per finding (`F-01`, …) merged into one list, latest version wins; a verdict-mix bar, then one card per finding: verdict pill, confidence bar, metric CI on a number line with the org threshold, evidence, counter-evidence, "would change if", provision citations, critic adjustment badge.
  - `critic`: upheld / weakened / overturned per finding with confidence deltas.
  - `report`: Engineer and Management tabs from the single `main` report (`engineer_markdown` + `management`:
    headline, traffic lights, decisions needed, next steps); a lone plain-markdown report renders as Engineer.
  - Unknown kinds fall back to JSON.

## Approval drawer

Sheet with a one-line context (audit id, kb, trigger, step trace), Summary (gates + "check these" LLM
assumptions, or the scenario summary), Analysis (the reviewed artifacts), Diffs (spec / plan diff), then
**Your decision**: three decision cards (**Approve / Request changes / Reject**, each with its consequence),
a **mandatory reason category** as chips (`wrong_fact`, `wrong_interpretation`, `missing_info`, `wrong_metric`,
`unrealistic_data`, `org_policy`, `other`), and a comment (required to reject or request changes); no "save as memory"
switches, the agents decide what to remember. The submit button names the action
and takes its colour ("Approve and continue", "Request changes", "Reject run"). Approve is disabled when a
blocking dataset gate failed. Approval shows a calm success state (one ripple, a drawn check) and a toast. The drawer also opens from Home and the approvals inbox.
Body: `POST /v1/audits/{id}/approvals` (`lib/approvals.ts: toApprovalIn`).

- **Scenarios gate**: the scenario relevance review (Iris or Gemini) is listed with `not_relevant` and
  `needs_change` first, each with its rationale and suggested change.
- **Public data gate** (`public_data`, waits in `find_public_data`): pick one candidate (or none) and approve
  ("Use this dataset"); the pick goes to the pipeline as `edits.selected`. Anything else continues zero-shot from
  the data dictionary; the run does not stop at this gate.

**Start audit** (system page header, and the Audits page header / empty state with a system picker):
`POST /v1/systems/{id}/audits` with `{stage: "load_context", data: {title, systemName, trigger: "manual"}}`, then
opens the new audit. **Systems** read the seeded card from `data.card` (`systems/lib/adapters.ts`), and the
gallery fills each system's last audit from the audits list. **Regulation → Check now** queues a reg-memory
watch check (`POST /v1/regulation/check-now`, `wait: false`) and refreshes sources and changes as it lands.

## API and mocks

| Feature | Calls | Backend |
| --- | --- | --- |
| audits, approvals | `GET /v1/audits`, `GET /v1/audits/{id}`, `GET/POST /v1/audits/{id}/approvals` | exists |
| regulation | `GET /v1/regulation/sources`, `…/documents/{id}/text?version=`, `…/documents/{id}/diff?from&to`, `GET /v1/regulation/changes`, `POST …/changes/{id}/decision`, `POST …/changes/{id}/systems/{systemId}` | exists ([backend regulation proxy](backend-systems.md#regulation-proxy-v1regulation)); the per-system change judge is pending (`affected: []`) |

Mock mode serves all of them from the feature fixtures (`lib/mocks.ts`, `lib/mockStore.ts`, `lib/mockRoutes.ts`,
registered by `src/shared/lib/mocks/handlers/{audit-workflow,regulation-memory}.ts`): a finished
SYS-001 CV Screener audit (postcode_region proxy, findings with counter-evidence, critic, two reports), a SYS-001
re-run paused at the dataset gate (approve it and it runs to the end, one step every 3.5 s), a SYS-002 run and RC-0007 / RC-0006 regulation changes.

Langfuse links use `VITE_LANGFUSE_URL` (default `http://localhost:3400`) and `VITE_LANGFUSE_PROJECT_ID` (default `product`).

## Tests

Pure logic in `lib/*.test.ts` (Vitest): stage mapping and step states, gate status, verdict and traffic-light
styling, provenance parsing, open gates and decision validation, business-rule append,
regulation diff parsing and judge decisions, and the mock run simulation.
