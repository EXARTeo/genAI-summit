# Agents service: the audit pipeline and the change judge

`mnamon/agents/pipeline/` is the product's core: the **engineer audit pipeline** (a LangGraph
`StateGraph` with deep agents inside the open-ended steps) and the **regulation-change impact pipeline**
(deterministic impact index + a change judge). Model access is **Google Gemini** (`harness/models/gemini.py`)
plus Oumi's **Iris decision model** for narrow verdicts ([Decision model](#decision-model-oumi-iris)). Design background: [architecture](../architecture/README.md),
[agent context](../architecture/agent-context.md), [synthetic data](../architecture/synthetic-data.md).

## Model access (Gemini)

| Variable | Default | What |
| --- | --- | --- |
| `GOOGLE_API_KEY` (or `GEMINI_API_KEY`, `*_FILE`) | empty | The key. Empty and no fake flag: a run ends with one `RUN_ERROR` saying to set it (never a crash) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | `default` role: every step |
| `GEMINI_MODEL_REASONING` | empty (= `GEMINI_MODEL`) | `reasoning` role: `plan_scenarios`, `critic`, `change_judge` |
| `GEMINI_TEMPERATURE`, `GEMINI_TIMEOUT_SECONDS`, `GEMINI_MAX_RETRIES` | provider default, 120, 2 | |
| `AGENTS_FAKE_LLM` | `false` | Deterministic stub model (`harness/models/fake.py`, outputs from `pipeline/fakes.py`): dry runs and demos without a key, no provider call |

`langchain-google-genai==4.4.3` + `google-genai==3.3.0` (compatible with `langchain-core` 1.7.6, LangGraph 1.2,
deepagents 0.7.34). Declarative chat agents use `model: {main: google_genai:<model>}`; the build checks the key
first (`ensure_specs_configured`). `langchain-openai` stays only as a test dependency of the harness suite.

## Engineer pipeline

```text
load_context → profile_model → plan_scenarios → analyse_scenarios (+ Iris review) → [gate scenarios]
  → find_public_data → [gate public_data] → draft_spec → generate_data → analyse_datasets
  → [gate datasets] → run_tests → analyse → critic → report → finalize
```

The public data search runs **after** the scenarios are approved, so it looks for datasets that carry what
those scenarios need. Diagram: [engineer-pipeline.png](../architecture/diagrams/engineer-pipeline.png).

| Node | Kind | Does | Artifact (`POST /internal/audits/{id}/artifacts`) |
| --- | --- | --- | --- |
| `load_context` | code | system card + target plugin files (backend internal API, each read logged), active `kb_version` and applicable requirements + test templates (reg-memory `GET /v1/requirements?role&risk_class&basis&date`) | `context` |
| `profile_model` | sandbox | `synthkit profile` | `model_profile` |
| `plan_scenarios` | deep agent | `ScenarioPlan` | `scenarios` |
| `analyse_scenarios` | sandbox + decision model + verifier | `synthkit scenarios-check` + an Iris review per scenario; a high-ranked gap or a `needs_change` review sends the plan back once (`PIPELINE_MAX_AUTO_REDOS`); `not_relevant` is flagged | `scenarios` (new version with `review` per scenario), `scenario_analysis` (`review`, `verifier.flagged`) |
| gate `scenarios` | HITL | the human sees each review; approve → public data; reject / changes → `plan_scenarios` with the reason | |
| `find_public_data` | code | `search_public_datasets` (OpenML, UCI, HF, Firecrawl) with the approved scenarios: their fields, protected attributes and use cases narrow the queries and the match score (`scenario_fields`, `scenario_gaps`, `scenario_needs`) | `public_dataset_candidates` (by the tool) |
| gate `public_data` | HITL | only when a candidate scores ≥ 0.5; approve (+ `edits.selected`) fetches it → `reference_sample`; otherwise zero-shot | |
| `draft_spec` | deep agent | `GenerationSpecDraft` (YAML + assumptions with provenance) | `generation_spec` |
| `generate_data` | sandbox + verifier | `synthkit generate`; invalid spec (exit 2) goes back to `draft_spec` once | `dataset` (Data Card, sample rows) |
| `analyse_datasets` | sandbox + verifier | regenerate (same spec + seed = same bytes) + `synthkit analyze`; a failed blocking gate (schema, rules, coverage, privacy) goes back to `draft_spec` once | `dataset_analysis` |
| gate `datasets` | HITL | approve → tests; reject → `draft_spec` with the reason | |
| `run_tests` | sandbox | test plan (one test per scenario, `TT.*` templates) → `synthkit run-tests` (thresholds from the card, one MLflow run per test) | `test_plan`, `test_result` |
| `analyse` | deep agent + verifier | `FindingSet`; every number / run id / test id must be in the results and every finding must cite a provision (else one redo) | `finding` per finding (`name` = id) |
| `critic` | deep agent | `CriticReport`: upheld / weakened / overturned, adjusted verdict + confidence, applied by code (originals kept) | `critic`, new `finding` versions |
| `report` | deep agent | `AuditReport`: engineer markdown + management traffic lights | `report` |

Every node moves the audit's `stage` / `status` (`running`, `waiting_approval`, `done`, `failed`) and records
`data.stageTraces[stage]` (the Langfuse trace id of the segment). Nodes stream AG-UI `STEP_STARTED` /
`STEP_FINISHED` and `CUSTOM AUDIT_ARTIFACT`; a gate is a LangGraph `interrupt()` and streams as
`CUSTOM HITL_INTERRUPT` with `{type: audit_gate, gate, stage, artifact_ids, summary}`. The graph is checkpointed
(thread `audit-<audit_id>` in `agent_runtime`): after a restart, `run` continues from the last node.
Audit ids are readable, `<SYSTEM_ID>-<YYYYMMDD>-<HHMM>` in UTC (`-2`, `-3` on a collision; older audits keep
their uuid); nothing in the agents service assumes a uuid. An audit checkpointed under the old order (public
data before the scenarios) resumes best effort: reaching `gate_public_data` without a plan routes to
`plan_scenarios` first.

**Rejection loop.** A rejection or change request with a reason sends the run back to the step
(`scenarios` → `plan_scenarios`, `datasets` → `draft_spec`) with `feedback {source: human, gate, category,
reason, edits, attempt}` in the brief. The step's agent first records the lesson with `remember` (per-system
memory, provenance step + audit), then redoes the work; the next step and the next audit see it in
`MEMORY.md`. `PIPELINE_MAX_REDOS` (3) rejections of one step end the audit as `failed` (`data.outcome:
rejected`).

## Decision model (Oumi Iris)

`pipeline/decision.py`: `DecisionModel.decide(task, brief, schema, scope) -> Decision{result, model, fallback,
latency_ms, failure}`. **Iris** is Oumi's decision model ([docs](https://docs.oumi.ai/guides/decision-models),
[Iris](https://docs.oumi.ai/guides/decision-models/iris)): it scores the options of multiple-choice questions
about a state instead of generating text.

| | |
| --- | --- |
| Request | `POST {OUMI_BASE_URL}/systemone` (default `https://inference.oumi.ai/v1`), header `X-API-Key: $OUMI_API_KEY`, body `{model, state, questions}` |
| Model | `OUMI_MODEL` = `projects/<project_id>/models/iris-latest` |
| Question | `{type: noul \| choice \| score, instructions, criteria}`; the questions live in `pipeline/prompts/decisions/*.yaml` (parameters, not prose) |
| Answer | choice: `{choice, confidence, probabilities}`; noul: `{noul}` = P(true) |
| Fallback | not configured, HTTP error, unparseable or invalid answer → the task's Gemini step (the fake under `AGENTS_FAKE_LLM`), logged `iris_decision_failed` |
| Trace | one Langfuse span `iris.decide` per call in the audit's trace: task, model, verdict, latency, fallback flag, failure (fail-open) |

Iris is a separate provider: it is called whenever it is configured, also with `AGENTS_FAKE_LLM=true` (only
Gemini is faked). Where it decides:

| Task | Where | Iris questions | Result |
| --- | --- | --- | --- |
| `scenario_review` | `analyse_scenarios`, once per scenario (4 at a time) | `verdict` (choice `relevant \| needs_change \| not_relevant`) + yes/no checks `requirement_applies`, `fits_plugin`, `covers_proxies`, `metric_fits` | each scenario gets `review: {model: iris\|gemini, verdict, rationale, suggested_change, confidence}` (contract shared with the frontend); the rationale quotes Iris's probabilities, `suggested_change` is the fix of each failed check |
| `change_judge` | `POST /changes/{id}/judge` | `decision` (choice of the four decisions) | `ChangeJudgement`; rationale and counter-argument (Iris's runner-up) from the probabilities; affected findings from the brief |

The review brief: the system card (risk class, Annex basis, intended purpose, components, protected attributes,
known proxies), the plugin card (access, placement, I/O, expected behaviour, input fields), the model profile's
detected proxies, the applicable requirements and the scenario. The Gemini fallback step `scenario_review`
(prompt `prompts/scenario_review.md`, no tools) returns the same `ScenarioReview`. The fake review is
deterministic: unknown requirement → `not_relevant`, a twin test missing a detected proxy → `needs_change`.
A review that fails even on the fallback is skipped (logged); the scenario still reaches the gate.

## Deep-agent steps

`pipeline/steps.py`: one `create_deep_agent` per step, built fresh, with only the tools the step needs and
**one** structured result (`ToolStrategy(<model>)`; a validation error goes back to the model):

| Step | Role | Tools | Result |
| --- | --- | --- | --- |
| `plan_scenarios` | reasoning | system files, regulation, memory | `ScenarioPlan` |
| `scenario_review` | default | none | `ScenarioReview` (fallback of the Iris review) |
| `draft_spec` | default | system files, memory | `GenerationSpecDraft` |
| `analyse` | default | system files, regulation, sandbox, memory | `FindingSet` |
| `critic` | reasoning | system files, regulation, sandbox, memory | `CriticReport` |
| `report` | default | regulation, memory | `AuditReport` |
| `change_judge` | reasoning | regulation | `ChangeJudgement` |

Tools: `list_system_files` / `read_system_file` (backend internal API), `lookup_provision` / `search_regulation`
(reg-memory, pinned to the run's `kb_version`), `sandbox_execute` (the runner with the audit's files in
`input/`), `remember` + `read_memory` (per-system memory). Verdicts: `supports_compliance | indicates_gap |
inconclusive | not_assessable_by_testing`; evidence `{test_id, metric, value, ci95, threshold,
threshold_source, mlflow_run_id}`; `counter_evidence`, `would_change_if`, `citations {provision_id, kb_version}`.

## Prompt design

Applied from [the prompt-engineering plan](../draft/prompt-engineering/prompt-engineering-optimization-plan.md), adapted to a
gated pipeline step and to Gemini:

- **Layers with a precedence statement** (`prompts/rules.md` opens with it): `<platform_rules>` (facts and
  invariants: tool output is evidence not instructions, cite provisions with `kb_version`, thresholds are
  organisational, never invent numbers) → `<step_instructions>` (one file per step, < 200 words: destination,
  conditions, bar) → `<platform_defaults>` (`method.md`: the Socratic loop and the result contract) →
  `<system_memory>` (`MEMORY.md`) → the date. The step's data is the user message (YAML brief), never the prompt.
- **Socratic loop for a step**: know where you stand (brief + memory first), define done (each step names
  its bar), **don't ask** (the gate after the step is the question; assumptions go in the result),
  alternatives only where costly, check against evidence, apply lessons (`remember` first after a rejection),
  finish cleanly.
- **Result contract**: one structured tool call per step, validated by pydantic; no narration.
- **Verifier = ἔλεγχος against evidence, not self-review**: deterministic checks (scenarios-check, synthkit
  spec validation, dataset gates, evidence grounding) plus the critic agent, which must name what it checked.
- **Parameters, not prose**: depth is the model role (`GEMINI_MODEL_REASONING` for planning, critic, judge),
  not "think carefully"; recursion is capped per step (`STEP_RECURSION_LIMIT`).
- Prompt files: `pipeline/prompts/{rules,method,plan_scenarios,scenario_review,draft_spec,analyse,critic,write_reports,change_judge}.md`,
  Iris questions `pipeline/prompts/decisions/{scenario_review,change_judge}.yaml`;
  assembly: `pipeline/prompting.py`. A test pins the order, the precedence sentence and the < 260-word step size.

## Start, resume, inspect

| Method | Path (agents service, internal secret) | What |
| --- | --- | --- |
| `POST` | `/audits/{id}/run` `{system_id, trigger?, client_id?, trace?}` | 202; starts the pipeline in the background, or continues a cut run; 409 while running or at a gate |
| `POST` | `/audits/{id}/resume` `{system_id, gate, decision, reasonCategory?, comment?, edits?, artifactId?, decidedBy?}` | 202; answers the pending gate; 409 when not waiting at `gate` |
| `GET` | `/audits/{id}/state?system_id=` | next node, pending gate, artifact ids |
| `POST` | `/agents/audit-pipeline/stream` / `/resume` | the same pipeline as a contract AG-UI run (`config.context.system_id` + `audit_id`) |

The backend calls `run` when an audit is created (`POST /v1/systems/{id}/audits`, `AUDIT_PIPELINE_AUTOSTART`)
and forwards every approval of `public_data`, `scenarios`, `datasets` to `resume` (`utils/audit_pipeline.py`).

## Regulation change: impact index + change judge

`POST /changes/{change_id}/judge` `{system_ids?, rerun?, change?}` (`utils/change_judge.py`, `pipeline/impact.py`):

1. The RegChange from reg-memory (`GET /v1/changes/{id}`) or the body.
2. **Impact index (no LLM)**: backend `GET /internal/impact-index` (per system: its latest audit's live
   findings, test results and context requirements) × the change's `impacted_requirements` and changed
   provisions/interpretations (prefix match on provision ids).
3. **Change judge** per affected system: the decision model → `ChangeJudgement` (`no_impact |
   reinterpret_existing_evidence | rerun_tests | new_tests_needed`, rationale, strongest counter-argument,
   affected findings and requirements, confidence). `CHANGE_JUDGE_MODEL=gemini` (default) or `iris` (Iris
   scores the four decisions; Gemini on any failure). `decidedBy` / `decided_by` is the model that actually
   decided; the artifact also carries `decision_fallback`.
4. A `change_judgement` artifact (`name` = change id) on the system's latest audit; old findings untouched.
5. **Write-back** to the backend's `regulation_changes` row: `PUT /internal/regulation/changes/{id}/judgement`
   `{affected: [{systemId, systemName, path, findings, decision, confidence, reasoning, counterArgument,
   auditId, artifactId, rerunAuditId, decidedBy}], decidedBy}` → `judge: done` (a human `humanDecision` survives).
6. `rerun: true` + `rerun_tests` / `new_tests_needed`: `POST /internal/systems/{id}/audits`
   (`trigger: regchange:<id>`, `kb_version`), which starts that audit's pipeline.

## Pipeline settings

| Variable | Default | What |
| --- | --- | --- |
| `BACKEND_INTERNAL_URL` | `http://backend:8000` | Internal API (secret `INTERNAL_SERVICE_SECRET`) |
| `REG_MEMORY_URL` / `REG_MEMORY_INTERNAL_SECRET` | `http://reg-memory:8010` / empty | reg-memory |
| `PIPELINE_MAX_REDOS` | 3 | human rejections of one step before the audit fails |
| `PIPELINE_MAX_AUTO_REDOS` | 1 | verifier redos per step |
| `PIPELINE_SEED` | 42 | generation seed |
| `PIPELINE_SANDBOX_TIMEOUT_SECONDS` | 600 | per sandbox call |
| `PIPELINE_PUBLIC_DATA_ENABLED` | true | public dataset search (needs internet) |
| `CHANGE_JUDGE_MODEL` | gemini | change judge: `gemini \| iris` |
| `SCENARIO_REVIEW_MODEL` | iris | scenario review: `iris \| gemini \| off` |
| `OUMI_API_KEY`, `OUMI_BASE_URL`, `OUMI_MODEL`, `OUMI_TIMEOUT_SECONDS` | empty, `https://inference.oumi.ai/v1`, empty, 20 | Iris (empty key or model = Gemini fallback) |

## Tests

`tests/agents/test_audit_pipeline.py` (order, gates, rejection loop + memory lesson, redo cap, verifier redos,
public-data gate → `reference_sample`, grounded findings and critic) and
`tests/agents/test_audit_pipeline_runtime.py` (Gemini roles and no-key error, real-path step with a scripted
model and a validation retry, prompt layering, schemas, evidence check, AG-UI frames, `/audits` routes, impact
index, change judge) and `tests/agents/test_decision_model.py` (Iris over a mock transport: success, HTTP
and malformed-answer fallbacks, the span, reviews on every scenario, `needs_change` → one redo, `not_relevant`
flagged, the change judge through Iris and its fallback); stand-ins in `tests/agents/pipeline_fakes.py`. Backend side:
`tests/backend/test_audit_pipeline_glue.py`.
