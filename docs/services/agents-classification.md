# Agents service: the risk-classification agent

`mnamon/agents/classification/` proposes a system's EU AI Act risk class from its card and documents
(plan 02, [plans/02-system-registration-and-risk-classification.md](../../plans/02-system-registration-and-risk-classification.md)).
It is a **separate agent from the audit pipeline** (`mnamon/agents/pipeline/`, [agents pipeline](agents-pipeline.md)):
it has its own prompts, step runner, tools, verifier, schemas and fakes, and only imports shared
infrastructure (the Gemini model factory and scripted fake in `harness/models`, deepagents + `ToolStrategy`,
the `RegMemory` and `IrisClient` clients, the Langfuse helpers). The audit pipeline's step tables are not
involved. The backend drives it ([backend § Risk classification](backend-systems.md#risk-classification)).

## Flow (one pass, not a graph; ~15 s live)

| # | Phase | Where | What |
| --- | --- | --- | --- |
| 1 | Pin | `agent.py` | `kb_version` = the request's, else reg-memory's active release |
| 2 | Pre-checks (code) | `prechecks.py`, `hints.yaml` | Annex III candidates (keyword table, top 3), Art. 5 flags (keyword groups per practice), Art. 50 features, profiling (`yes/no/unknown`), role hint from `acquisition`, Annex I flag, `ai_system_doubt`. Hints, never answers |
| 3 | Provision texts (code) | `prechecks.py` | Art. 3(1)/3(3)/3(4), 5(1) + flagged points, 6(1)-6(4) + 6(3)(a-d), 25(1), candidate Annex III points, 50(1-3) when features; related guidance ids (`/v1/interpretations?relates_to=`), fetched concurrently into a `KbCache` |
| 4 | `classify_risk` (Gemini, `reasoning` role) | `agent.py` `ClassifierStep`, `tools.py` | One deep agent, tools `lookup_provision`, `search_regulation` (ranked `/v1/provisions/search`), `read_guidance` (keyword windows of one guidance node, ≤ 4,000 chars, with `binding` / `status`); result `RiskProposal` via `ToolStrategy`; 2 attempts, recursion limit 24 |
| 5 | Verifier (code) | `verify.py` | Citations exist at the kb; class / route / basis consistent; 6(3) never with profiling, names a condition, cites AIA.6.3, lists the 6(4) duty; prohibited cites AIA.5.1.*; every flag and candidate addressed; guidance non-binding (draft when the kb says so); ≥ 1 counter-argument and `would_change_if`. Problems → one redo with them as feedback; still failing → kept in `verifier_problems`, `needs_human` |
| 6 | Iris (Oumi) | `prompts/risk_classification.yaml`, `claims.py` | One `IrisClient.ask` with a `choice` over six options (`prohibited, high_risk_annex_i, high_risk_annex_iii, not_high_risk_6_3, transparency_only, minimal`) + one `noul` per claim (keys `c01`, `c02`..., mapped back in code; see [Iris claims](#iris-claims)). **No Gemini fallback** (it would grade itself): unavailable → `iris: null`, claims unchecked, `needs_human` |
| 7 | Compare + dates (code) | `agent.py` | `needs_human` = disagreement, Iris or agent confidence < `CLASSIFY_IRIS_MIN_CONFIDENCE` (0.6), Iris profiling > 0.5 with a 6(3) claim, a strong claim disagreement, verifier problems, or no Iris; `key_dates` from each route provision's `valid_from` / `valid_from_by_basis` at the kb; citations get the kb's `kb_version`, `binding`, `status` |

Prompt layering (`compose_prompt`): `prompts/rules.md` (precedence, propose-only, cite or say uncertain) →
`prompts/classify_risk.md` (the job, ≤ 200 words) → `prompts/method.md` (verify, feedback, result tool) → the
date. The brief is YAML: `system` (card), `prechecks`, `provisions`, `related_guidance`, `documents` (the PM's
uploads, framed as data), `kb_version`; a human rejection reason rides in a `<feedback>` block, a non-human
note (e.g. a stale re-run) as `previous_run_note`.

## Route

`POST /systems/{system_id}/classify` (internal secret; `router/classifications.py` → `utils/classify_runs.py`
→ `classification/agent.py`). Synchronous, deadline 110 s (under the backend's `CLASSIFY_TIMEOUT_S`).

Request (`schema/classifications.py`, extra keys ignored):

```json
{
  "classification_id": "CLS-SYS-004-20261115-1405",
  "kb_version": null,
  "card": {"id": "SYS-004", "name": "CV Parser", "intended_purpose": "...", "profiling": "no",
           "acquisition": "in_house", "features": [], "annex_i_product": null},
  "documents": [{"path": "docs/system-specification.md", "version": 1, "text": "..."}],
  "feedback": {"source": "human", "reason": "It also ranks candidates"},
  "trace": {"name": "classify:CLS-SYS-004-20261115-1405", "trace_id": "<optional 32-hex>"}
}
```

`acquisition` is matched by words: `changed / modified / rebranded` → `provider_by_art25`;
`as_is / bought / licensed / vendor` → `deployer`; `in_house / built / developed` (or empty) → `provider`.
`profiling` accepts `yes / no / not_sure` (or booleans).

Response 200: `ClassificationResult` (`classification/schemas.py`, plan 02 §8.2), snake_case:
`risk_class, route, annex_basis, annex_basis_id, role, role_reasoning, art5_screening[], annex_iii_considered[],
art6_3, transparency, gpai, reasoning, counter_arguments[], would_change_if[], uncertainties[], next_steps[],
confidence, citations[] {id, kb_version, quote, binding, status}` + code-added `classification_id, system_id,
kb_version, prechecks, key_dates[] {what, date, provision_id, amended_by}, iris {choice, probabilities,
confidence, profiling, agent_choice} | null, iris_claims[], iris_summary {checked, agree, disagree}, agreement,
needs_human, needs_human_reasons[], verifier_problems[], decided_by (gemini+iris | gemini), trace_id`.

## Iris claims

Iris checks every article-level claim and premise of the proposal, not only the overall class, in the same
call. `claims.py` builds them in code, in priority order, capped at 20:

| `group` | `key` | Statement (`agent` = what the proposal holds) |
| --- | --- | --- |
| `art6_3` | `art6_3:condition` | "The Art. 6(3)(a) condition (narrow procedural task) holds" (`holds`), when 6(3) was considered |
| `art6_3` | `art6_3:profiling` | "The system profiles natural persons" (`profiling == yes`; also fills `iris.profiling`) |
| `annex_iii` | `annex_iii:AIA.ANNEX_III.4.a` | "Annex III 4(a) applies to this system" (rows with `applies` true first; false rows after Art. 50) |
| `role` | `role` | "The organisation is the provider of this system (Art. 3(3)), not only a deployer" |
| `annex_i` | `annex_i` | "The system is a safety component of a product under Annex I law" (only when flagged or routed) |
| `art5` | `art5:AIA.5.1.f` | "The system engages in the practice of Art. 5(1)(f)" (the screening row's `applies`) |
| `art50` | `art50:AIA.50.1` | "Art. 50(1) applies (…)" for 50(1), 50(2) and any 50(3)/50(4) in the brief or `transparency.provisions` |
| `assumption` | `assumption:ai_system`, `assumption:no_ranking` | "The system is an AI system under Art. 3(1)"; "does not rank, score, filter or reject people" (6(3) route) |
| `counter` | `counter:1`… | "This counter-argument holds: …" (`agent: false`, the agent rejected it) |

Each claim: `{key, group, provision_id, statement, agent, iris (P true | null), agrees (null when unchecked),
strong_disagreement}`. `agrees = (iris >= 0.5) == agent`; strong = agent true and P < 0.25, or agent false and
P > 0.75; each strong one adds `needs_human` with "Iris disagrees: <statement> (P=0.12)" (a weak one does not).
Iris down or not configured: the claims are still returned with `iris: null, agrees: null` and
`iris_summary.checked = 0`. The `iris.decide` span carries the questions, every claim and the counts.

Errors: 502 when reg-memory cannot pin a kb or serve any classification provision, when the Gemini step fails
twice, or at the deadline; 401/403 without the internal secret.

## Langfuse

Its own trace (never an audit's): a root span `classify:<CLS id>` (the request's `trace.name`), child spans
`classify.prechecks`, `classify.verify` (per attempt), `iris.decide`, and the Gemini step's LangChain run
nested under the root (`trace_run_config`, kind `classification`, tags `classification`, `system:<id>`).
`trace_id` is returned in the result.

## Settings

| Variable | Default | What |
| --- | --- | --- |
| `CLASSIFY_IRIS_MIN_CONFIDENCE` | 0.6 | below this (Iris's or the agent's confidence) → `needs_human` |
| `OUMI_API_KEY`, `OUMI_BASE_URL`, `OUMI_MODEL` | | Iris (empty = no independent check, `needs_human`) |
| `GEMINI_MODEL_REASONING` / `GEMINI_MODEL`, `AGENTS_FAKE_LLM` | | the step's model; the fake answers from the brief |

## Tests

`tests/agents/test_classify.py` (no paid API): pre-checks (CV → 4(a), emotion of employees → AIA.5.1.f, role
hints, profiling blocks 6(3)), every verifier rule, compare (agree / disagree / low confidence / no Iris),
Iris option mapping, Iris claims (built per group, priority and cap, agreement / strong disagreement, one call
for all, strong disagreement → `needs_human`, Iris down → unchecked claims), key dates, `read_guidance` windows and errors, full runs with the fake Gemini (CV parser →
6(3)(a), CV screener → 4(a), verifier redo, human feedback), and the route end to end over a reg-memory
`MockTransport` (200, 502, no secret).
