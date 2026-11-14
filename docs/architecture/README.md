# Architecture

> Keep this page current as the design changes. The full design document (Greek, 24 pages) is
> [ai-act-governance-copilot.pdf](ai-act-governance-copilot.pdf); this page is the English summary
> of what we build. Its §12 (AI Engineer MVP) replaces the earlier scope in §9 and §11.5.

## Overview

**AI Act Governance Copilot**: an agentic EU AI Act compliance assistant an organisation runs in-house.
The hackathon MVP covers one pillar only: the **AI engineer of a high-risk system the organisation
builds as a provider**. Given a registered system (a seeded *system card*) and a model in MLflow, the
agent derives the applicable AI Act requirements, plans tests, generates auditable synthetic datasets,
runs the tests in an isolated sandbox, and returns findings with reasoning **and** counter-arguments,
plus an engineer report and a management report. When the regulation or its guidelines change, it
works out which systems are affected and re-runs what is needed.

Design principles (PDF §1):

- **Human in the loop by design**: agents write `proposed` results; only a person makes them `approved`.
- **Every claim has a source** (article / paragraph / Annex / guideline); no source → the agent says it is uncertain.
- **Deterministic skeleton, LLM for judgement**: the order of steps and the rules are code/YAML; the LLM interprets and explains.
- **Versioned law**: every finding locks the `kb_version` it was produced with; a law change triggers impact analysis, never a silent rewrite.

## Layout

The product lives in one folder named after it. Each service is a subfolder with its own Dockerfile, and the folder's `docker-compose.yaml` wraps them all:

```text
<product>/
├── <service-a>/
│   └── Dockerfile
├── <service-b>/
│   └── Dockerfile
└── docker-compose.yaml
```

## Services

### Running today

The product folder is `product/` until a name is chosen. Full table (images, networks, healthchecks): [product/README.md](../../product/README.md).

| Service | Folder | Port (host → container) | Responsibility |
| --- | --- | --- | --- |
| `backend` | `product/backend/` | 8100 → 8000 | FastAPI API; runs `alembic upgrade head` on start: [backend](../services/backend.md) |
| `agents` | `product/agents/` | not published (8003) | Runs the agents (OpenAI, deep agents, async sub-agents, MCP, sandbox) and streams AG-UI to the backend: [agents service](../services/agents-service.md), [contract](../contracts/agents-contract.md) |
| `postgres` | (image) | not published | Backend database + `agent_runtime` (checkpoints, conversation files, tasks) |
| `redis` | (image) | not published | Backend cache (`volatile-lru`) |
| `langfuse-web` + `langfuse-worker` | (images) | 3400 → 3000 | Langfuse v4: trace UI, ingestion API, async processing |
| `langfuse-postgres`, `-clickhouse`, `-redis`, `-minio` | (images) | not published | Langfuse's own datastores |

### Planned for the MVP (PDF §12.2)

| Container | Role | Tech (proposal) | Maps to |
| --- | --- | --- | --- |
| `frontend` | Engineer workspace: systems, system card, test plan, dataset auditor, findings, reports, regulation-change inbox | Next.js | new |
| `backend` | API, system cards, runs, findings, evidence, notifications, webhooks (Firecrawl, Telegram), job queue | FastAPI + Postgres + Redis | existing `backend` |
| `agent` | Test pipeline and impact pipeline | LangGraph + hackathon LLM provider | existing `agents` |
| `reg-memory` (RKS) | Regulatory Knowledge Service: codified AI Act / guidelines / Omnibus, versions, diff, watcher, change judge | FastAPI + Postgres/pgvector + YAML corpus in git | new |
| `mlflow` | Tracking server, model registry, artifacts (test runs are logged here) | MLflow + local volume | new |
| `sandbox` | Runs test code; no network except MLflow; CPU/RAM/time limits | Python image with sklearn, fairlearn, sdv, ART | existing sandbox runner |

The sandbox is separate from the agent so LLM-written test code never runs next to credentials or the database.

## Data flow

### Engineer pipeline (PDF §12.5)

```text
system card + MLflow model
  → load_context     card, model signature/metrics/lineage, applicable requirements from RKS
  → plan_tests       requirement → test templates, parameterised from the card      [HITL: approve plan]
  → generate_data    one DatasetSpec per test (schema-driven, counterfactual twins,
                     perturbation; adversarial = stretch) + Data Card per dataset   [HITL: audit datasets]
  → execute          sandbox; each run = MLflow run tagged req_ids, card_version, kb_version, dataset_id
  → analyse          findings (verdict, confidence, evidence with CI, reasoning)
  → critic           separate agent tries to overturn each finding; verdict adjusted
  → report           engineer report (reproducible) + management report (traffic light per requirement)
```

Finding verdicts: `supports_compliance | indicates_gap | inconclusive | not_assessable_by_testing`.
Fairness thresholds on the system card are **organisational** (`org_thresholds`), not legal; the
AI Act sets no numbers, and findings must say so.

### Regulation change → re-review (PDF §12.6)

```text
Firecrawl monitor (EUR-Lex, Service Desk, guidelines) → webhook → RKS
  → re-parse, provision-level diff by content_hash → LLM classifies change type → RegChange + candidate kb_version
  → impact index (no LLM): provision → requirements → findings/test runs → systems
  → change judge per (system, change): no_impact | reinterpret_existing_evidence | rerun_tests | new_tests_needed
  → notify (inbox + Telegram with inline buttons) → optional re-run → delta report vs previous kb_version
```

Every step is traced in Langfuse, which doubles as the audit trail in the demo.

### RKS corpus (PDF §12.3)

YAML in git, four entities: `provisions/` (verbatim text, `valid_from`, `content_hash`, `kb_version`),
`requirements/` (actor, `applies_if`, modality, testability, `test_templates`), `interpretations/`
(guidelines, `binding: false`), `test_templates/` (`supports`, `needs`, metric, `limitations`).
MVP scope: Art. 6, 9–15, 17, Annex III, Annex IV.

### Seed data (PDF §12.7)

- **SYS-001 CV Screener** (Annex III 4(a)): biased through a proxy (postcode ↔ nationality).
- **SYS-002 Credit Scorer** (Annex III 5(b)): nearly clean, the contrast case.
- A previous test run and findings for both, so the regulation-change flow has something to affect.

## Open questions (PDF §12.9)

- Which "decision model" is meant for the change judge (Oumi *Iris* is a candidate).
- LLM provider and sponsor tools beyond Firecrawl.
- Whether the Omnibus changed the special-category-data rule for bias detection (former Art. 10(5)); it decides whether tests may use protected attributes.

## Decisions

| Date | Decision | Why |
| --- | --- | --- |
| 2026-11-13 | Services run in Docker, wrapped by one compose file in the product folder | One command starts the whole product, locally and on a server |
| 2026-11-13 | Repo tooling: Python 3.12 + uv, pytest, ruff | Fast, reproducible checks with one lockfile |
| 2026-11-13 | Self-hosted Langfuse v4 in the product compose, with its own Postgres and Valkey | Full traceability without a SaaS; v3 is deprecated; Langfuse's queues need `noeviction` and its migrations stay off the product database |
| 2026-11-14 | Product: AI Act Governance Copilot, MVP = AI Engineer (provider) pillar only | Classification and system card are seeded; the testing + regulation-change loop is the demoable, differentiated part |
