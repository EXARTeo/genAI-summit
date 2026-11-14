# Frontend: audit workflow UX

The audit-workflow pages of `product/frontend/` (see the frontend page for the scaffold, design
system and mock mode). Four features, each `src/features/<feature>/{components,hooks,handlers,lib,pages}`,
mounted by thin route views in `src/pages/*View.tsx`.

| Route | Feature | What |
| --- | --- | --- |
| `/audits` | `audits` | Audit runs with progress ring, status, current step, kb_version, trigger, Langfuse link |
| `/audits/:auditId` | `audits` | **Audit run page** (below) |
| `/approvals` | `approvals` | Inbox of every open HITL gate; opens the approval drawer |
| `/memory?entry=MEM-…` | `memory` | Memory ledger (org + per system), entry detail, approve / promote / retire / re-activate |
| `/regulation?tab=changes\|sources&source=…` | `regulation` | Regulation-change inbox and reg-memory sources with versions, text and diffs |

## Audit run page

- **Left: live vertical Stepper** of the engineer pipeline, 13 steps in `lib/pipeline.ts` (`STAGES`):
  `load_context → profile_model → plan_scenarios → analyse_scenarios → ⏸ approve_scenarios → draft_spec →
  generate_data → analyse_datasets → ⏸ approve_datasets → run_tests → analyse → critic → report`.
  `stepState(stage, audit)` maps the audit's `(stage, status)` onto `done | active | pending | blocked |
  needs-approval`; backend stage names may also be artifact kinds (`dataset_analysis` → `analyse_datasets`).
  Running steps show `AgentThinking`; a step that turns done flashes once and draws its check; gates pulse
  amber with a "Review & decide" button. Each step shows its duration and a Langfuse trace link
  (`audit.data.stageTraces[stage]`). The page polls every 1.5 s while the run is live and follows the live
  step until the user pins another one. A finished audit has **Replay run** (client-side walk through every
  step, pausing on the gates) for the demo.
- **Right: the selected step's artifact** (latest non-superseded version per `kind/name`), with version,
  status, author and trace link:
  - `context`: system, requirements (test vs document review), plugins, memory applied, files read with versions.
  - `model_profile`: feature-sensitivity bar chart (protected proxies in amber with ⚠), decision-boundary flip rates.
  - `scenarios` / `scenario_analysis`: test table with memory chips; coverage per requirement, diff vs last plan, risks, not-testable list.
  - `generation_spec`: YAML with each node's `provenance` block tinted, `llm_assumption` in amber, plus the assumption list and the spec diff.
  - `dataset_analysis`: the five gates as animated pass/warn/fail cards (metrics in tooltips), coverage heatmap (cells under `min_per_cell` ringed red), twin modes a/b/c with mean Δ, flip rate and CI, and a side-by-side twin-pair viewer.
  - `finding`: verdict pills, confidence bar, metric CI on a number line with the org threshold, evidence, counter-evidence, "would change if", provision citations and `applied MEM-…` chips (link to the ledger), critic adjustment badge.
  - `critic`: upheld / weakened / overturned per finding with confidence deltas.
  - `report`: Engineer and Management tabs; management shows traffic lights per requirement.
  - Unknown kinds fall back to JSON.

## Approval drawer

Sheet with Summary (gates + LLM assumptions, or the scenario summary), Analysis (the reviewed artifacts),
Diffs (spec / plan diff), then **Approve / Request changes / Reject**, a **mandatory reason category**
(`wrong_fact`, `wrong_interpretation`, `missing_info`, `wrong_metric`, `unrealistic_data`, `org_policy`,
`other`), a comment (required to reject or request changes) and "save as memory for this system / propose
org-wide" switches (sent as `edits.memory.scope`). Approve is disabled when a blocking dataset gate failed.
Approval plays a check-and-ripple animation; a toast shows the memory proposal path the backend returns.
Body: `POST /v1/audits/{id}/approvals` (`lib/approvals.ts: toApprovalIn`).

## API and mocks

| Feature | Calls | Backend |
| --- | --- | --- |
| audits, approvals | `GET /v1/audits`, `GET /v1/audits/{id}`, `GET/POST /v1/audits/{id}/approvals` | exists |
| memory | `GET /v1/memory/ledger[/{id}]`, `POST /v1/memory/ledger/{id}/{approve\|promote\|retire\|reactivate}` | **pending** (parsed view over the memory files) |
| regulation | `GET /v1/regulation/sources`, `…/documents/{id}/text?version=`, `…/documents/{id}/diff?from&to`, `GET /v1/regulation/changes`, `POST …/changes/{id}/decision`, `POST …/changes/{id}/systems/{systemId}` | **pending** (backend proxy to reg-memory + change judge) |

Mock mode serves all of them from the feature fixtures (`lib/mocks.ts`, `lib/mockStore.ts`, `lib/mockRoutes.ts`,
registered by `src/shared/lib/mocks/handlers/{audit-workflow,memory-ledger,regulation-memory}.ts`): a finished
SYS-001 CV Screener audit (postcode_region proxy, findings with counter-evidence, critic, two reports), a SYS-001
re-run paused at the dataset gate (approve it and it runs to the end, one step every 3.5 s), a SYS-002 run, the
memory ledger (MEM-0039 → MEM-0042 promotion, stale and retired entries) and RC-0007 / RC-0006 regulation changes.

Langfuse links use `VITE_LANGFUSE_URL` (default `http://localhost:3400`) and `VITE_LANGFUSE_PROJECT_ID` (default `product`).

## Tests

Pure logic in `lib/*.test.ts` (Vitest): stage mapping and step states, gate status, verdict and traffic-light
styling, provenance parsing, open gates and decision validation, memory filters and lifecycle actions,
regulation diff parsing and judge decisions, and the mock run simulation.
