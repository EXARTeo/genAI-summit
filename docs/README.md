# Documentation

```text
docs/
├── guides/          # How to install, configure and run
├── architecture/    # System design: summary page + full design PDF
├── services/        # How each service is built
├── contracts/       # Cross-service contracts (APIs, events, streams)
└── draft/           # Work in progress: status page, prompt-engineering drafts
```

| Folder | Page | What it covers |
| --- | --- | --- |
| `guides/` | [Getting started](guides/getting-started.md) | Install, configure and run the project locally |
| `guides/` | [Deploying to Dennis](guides/deploy-denis.md) | CI/CD: CI jobs, ARM64 images to GHCR, the deploy repo, the Portainer stack, secrets and variables, the public hostname |
| `guides/` | [Telegram approvals](guides/telegram.md) | Create the bot, get the chat id, approve/reject HITL gates from Telegram |
| `architecture/` | [Architecture](architecture/README.md) | AI Act Governance Copilot: MVP scope, containers, pipelines, decisions |
| `architecture/` | [Agent context and memory](architecture/agent-context.md) | reg-memory scope, system dossier, plugins (target card + docs + training-data description), per-system + general memory, Postgres-backed filesystem and audit ledger |
| `architecture/` | [Synthetic test data](architecture/synthetic-data.md) | How `generate_data` builds schema-correct, business-realistic test data: LLM-drafted GenerationSpec → DAG sampler + rule enforcement, twins and edge cases per template, validation gates, Data Card, sandbox libraries, MVP cut |
| `architecture/` | [Diagrams](architecture/diagrams/) | PNG + SVG: containers, engineer pipeline, regulation change, traceability (rebuild: `scripts/build-diagrams.*`) |
| `architecture/` | [Design document (PDF, Greek)](architecture/ai-act-governance-copilot.pdf) | Full system design: personas, layers, agents, HITL gates, data model, eval, MVP |
| `services/` | [Frontend](services/frontend.md) | Engineer workspace scaffold: structure, design system (`@/shared/ui`), motion, brand tokens and palette (logo TODO), API client + mock mode, systems feature, how to add a feature, Docker/nginx |
| `services/` | [Frontend: audit workflow](services/frontend-audit-workflow.md) | Audit run page (live pipeline stepper, artifacts, Langfuse links), approvals inbox + drawer, memory ledger, regulation changes |
| `services/` | [Backend: systems, files, memory, audits](services/backend-systems.md) | Systems, versioned workspace files, memory, audits, approvals, seed import and the agents' internal API |
| `services/` | [Backend: async sub-agents](services/backend.md) | The backend's task mirror, task routes and sockets, channel frames, the wake-up flow and its settings |
| `services/` | [Agents classification](services/agents-classification.md) | The risk-classification agent (plan 02): pre-checks, one Gemini step, verifier, Iris check, `POST /systems/{id}/classify` |
| `services/` | [Agents pipeline](services/agents-pipeline.md) | The audit pipeline (gates, deep-agent steps, verifiers, prompt design), Gemini access, the impact index and change judge |
| `services/` | [Agents service](services/agents-service.md) | How the agents service is built: run path, filesystem and uploads, tools and approvals, MCP, sandbox, tracing, env vars |
| `services/` | [reg-memory](services/reg-memory.md) | The regulation store: source catalog, Cellar/HTTP fetching, versioned file store (raw, text, diffs, manifests, runs), incremental stages, API, env vars, how to add a source |
| `services/` | [model-gateway](services/model-gateway.md) | Seed models as production-style REST endpoints (bearer auth, per-token rate limit, latency, signature validation), the SYS-001 parser→ranker pipeline |
| `services/` | [MLflow and the seed job](services/mlflow.md) | MLflow tracking server + registry, the one-shot seed job (causal-graph synthetic data, training, per-subgroup metrics, registration, idempotent `seed_hash`), the four demo system dossiers and their planted issues, the model naming contract, how to add a case |
| `services/` | [sandbox_runner and synthkit](services/sandbox.md) | The `execute` runner (`POST /v1/exec`: files in/out, time/memory/output/disk limits, no internet) and synthkit: profile the model → check scenarios → generate (DAG, rules, twins, boundary-aware) → analyze (five gates), Data Card |
| `contracts/` | [Agents-service contract](contracts/agents-contract.md) | What the agents service must implement for the backend: endpoints, request JSON, AG-UI events, errors |
| `draft/` | [Project status (2026-11-14 evening)](draft/status/README.md) | WIP: what works live, in tests only or is missing, ranked gaps, next steps; containers, demo-spine and pipeline status diagrams (`draft/status/build.py`) |
| `draft/` | [Prompt-engineering plan](draft/prompt-engineering/prompt-engineering-optimization-plan.md) | WIP: the Socratic agent loop and layered prompts every step prompt follows (+ the *Beyond Socrates* PDF) |

Put a new page in the folder that matches it and add a row here.
