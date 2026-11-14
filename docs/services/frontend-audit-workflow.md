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

- **Header**: system · title, status, ids (system, kb, card version, trigger) and *Full trace*, *Replay run* or
  *Review & decide*. A finished run adds a summary strip: gaps, supports, inconclusive, not assessable, total agent time.
- **Left: the pipeline console** (`AuditPipeline`): a progress bar with "Step n of 13 · elapsed", then one compact
  row per step (node, label, GATE tag, duration or *running* / *waiting*); the selected and the current step expand
  with their description. The engineer pipeline has 13 steps in `lib/pipeline.ts` (`STAGES`):
  `load_context → profile_model → plan_scenarios → analyse_scenarios → ⏸ approve_scenarios → draft_spec →
  generate_data → analyse_datasets → ⏸ approve_datasets → run_tests → analyse → critic → report`.
  `stepState(stage, audit)` maps the audit's `(stage, status)` onto `done | active | pending | blocked |
  needs-approval`; backend stage names may also be artifact kinds (`dataset_analysis` → `analyse_datasets`).
  Running steps show a spinner and shimmer; a step that turns done flashes once and draws its check; an open
  gate is the only amber thing on the page, with a "Review & decide" button. Done gates look like any done step.
  The step header on the right shows its duration and Langfuse trace link (`audit.data.stageTraces[stage]`). The page polls every 1.5 s while the run is live and follows the live
  step until the user pins another one. A finished audit has **Replay run** (client-side walk through every
  step, pausing on the gates) for the demo.
- **Right: the selected step's artifact** under a step header ("Step n of 13", label, description, duration,
  trace); latest non-superseded version per `kind/name`, with version, status and author. A running step shows a
  spinner over a skeleton of the artifact:
  - `context`: system, requirements (test vs document review), plugins, files read with versions.
  - `model_profile`: feature-sensitivity bar chart (neutral bars; protected proxies in amber with ⚠, so the problem
    reads at a glance), decision-boundary flip rates.
  - `scenarios` / `scenario_analysis`: test table; coverage per requirement, diff vs last plan, risks, not-testable list.
  - `generation_spec`: YAML with each node's `provenance` block tinted (`dictionary`, `training_doc`, `business_rule`), `llm_assumption` in amber, plus the assumption list and the spec diff.
  - `dataset_analysis`: the five gates as calm cards (status icon + label, the gate's note; warn/fail get a tinted border; metrics in tooltips), coverage heatmap (teal tint by count, cells under `min_per_cell` ringed red), twin modes a/b/c with mean Δ (red when the CI excludes 0), flip rate and CI, and a side-by-side twin-pair viewer.
  - `finding`: a verdict-mix bar, then one card per finding: verdict pill, confidence bar, metric CI on a number line with the org threshold, evidence, counter-evidence, "would change if", provision citations, critic adjustment badge.
  - `critic`: upheld / weakened / overturned per finding with confidence deltas.
  - `report`: Engineer and Management tabs; management shows traffic lights per requirement.
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
