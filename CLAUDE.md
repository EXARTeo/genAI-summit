# genAI-summit — Claude instructions

Project for the GenAI Summit. Repo: `EXARTeo/genAI-summit`. Product chosen (2026-11-14): **AI Act Governance Copilot** (see "The product" below). Built so far: scaffold, `backend`, `agents` service, Langfuse; the product features are design only.

## The event (researched 2026-11-13; re-check the official pages, details change)

We are entering the **Gen AI Summit Hackathon**: a 36-hour build that runs alongside **GenAI Summit 5** (South-East Europe), the region's largest GenAI-only conference.

| | Hackathon | GenAI Summit 5 |
| --- | --- | --- |
| When | Sat 14 – Sun 15 Nov 2026 (36 h) | Mon 16 Nov 2026, from 09:00 |
| Where | Athens LifeTech Park, Spata (shuttle from Syntagma) | Stavros Niarchos Foundation Cultural Center (SNFCC), Kallithea, Athens |
| Organisers | Abed Hamami (polymath42), 100mentors, Panathēnea | 100mentors |
| Theme | Agents doing real work: "Can you build something that people and agents want?" | "Agents at Work": what comes after the pilot (production, governance, ROI) |
| Who | ~100–120 selected builders, teams of 1–5, free | 5,000+ attendees, 200+ speakers (PM Kyriakos Mitsotakis announced) |
| Links | [site](https://hackathon.polymath42.com) · [agenda](https://hackathon.polymath42.com/agenda) · [llms.txt](https://hackathon.polymath42.com/llms.txt) · [Luma](https://luma.com/x1wxi5sn) | [genaisummitseeurope.com](https://www.genaisummitseeurope.com) |

### Brief and judging

- **Brief:** agents that take a goal, work out the steps, use the tools available and **deliver real work end to end, proactively**, on tedious multi-step tasks people don't want to repeat. Specific challenges/tracks are announced at the kickoff.
- **"The only requirement: make it work and show us the demo."** "This is not a pitching competition, it's an agent at work."
- **Judged on usefulness, craft and aura points** (no weights published). Mentors come from the Summit speaker list.
- **Prepared in advance is fine for ideas, tooling and boilerplate** (this repo's scaffold, the backend port, branding, deck builder). **The product itself must be built in the window:** "Judges weigh what was made during the build window"; "a project that was substantially finished beforehand will not fare well." Do not build product features before 13:00 Sat 14 Nov.
- Partners (APIs/credits may be offered at kickoff): Google, fal, Firecrawl, Oumi, Wonderful, boxd, Quintessential, Big Pi Ventures, Endeavor, Wiserwork, others. Prizes are not published on the official site.

### Schedule (Athens time)

| When | What |
| --- | --- |
| Fri 13 Nov 19:00–22:00 | Pre-party (separate sign-up) |
| Sat 14 Nov 11:00 | Shuttle from Syntagma (meet 10:30) |
| Sat 12:00 / 12:30 | Arrival / kickoff: rules, tracks, how the weekend runs |
| Sat 13:00 | **Hacking starts**, team formation; through the night |
| Sun 15 Nov 18:00 | **Code freeze: submit repo, demo video and project details** |
| Sun 18:00–20:00 | Shortlist → semifinalists present to judges (19:00) → finalists announced (20:00) |
| Mon 16 Nov 18:00–18:30 | Finalists pitch on the Summit stage at SNFCC; winners 19:30 |

### What this means for the work

- Optimise for a **working end-to-end demo** of an agent doing a real job, then craft and polish. A recorded demo video is required at code freeze; `presentations/` builds the pitch deck from `branding/`.
- Keep the stack bootable with one command (`docker compose ... up`) so the demo never depends on a laptop's dev setup; Langfuse traces double as proof that the agent really did the work.
- Reply in plain, short status updates during the event; time is the constraint.

### Credits, tracks and competition (researched 2026-11-14; official = [credits](https://hackathon.polymath42.com/credits), the rest is an **unofficial fan recon**, [nikolas-sapa/genai-summit-hackathon-recon](https://github.com/nikolas-sapa/genai-summit-hackathon-recon): verify at kickoff)

- **Credits (official):** Google AI inference (all teams) · fal US$50/builder + US$1.5k fal-track prize · Oumi early access to *Iris* decision model + US$1,000/500/250 for top 3 teams using it · treg US$20/builder + US$500/250/100 top 3 · boxd €50 (forkable hardware-isolated VMs, agent-managed via CLI) · Wonderful (voice agents, multilingual) selected teams only, amount TBA. Claim links need the participant password from the organisers. What Iris and treg actually are is unverified. Firecrawl is a partner (web crawling) with no credit listed.
- **Prizes (unofficial):** €5k / €2.5k / €1k main pool (Quintessential + Wonderful) plus up to 4 sponsor-challenge prizes.
- **Tracks (unofficial, no official page; `/tracks` and `/challenges` are 404):** Voice & Enterprise (Wonderful), Biotech & AI (Athens LifeTech Park), Content & Digital Art (fal), Open (hardware bonus). Real briefs come at the Sat 12:30 kickoff; ask mentors. Sponsor deck: <https://hackathon.polymath42.com/deck>.
- **Wonderful track risks:** Wonderful owns anything built on its platform (agents, prompts, workflows), capped at 25 people, access ends with the event, terms can change. If we pick it, keep core logic and evals in our own repo and use the platform only as a thin demo layer; re-read the terms at kickoff.
- **Judging:** judges + a voting app + an **AI-assisted review of submissions**, so keep the README and repo clean. Semifinal and final pitches are 3 min each. Judges look at the whole picture: what shipped, how well it works, and team potential.
- **Competition:** ~100 selected, mostly web/full-stack/vibe coders (~70%), only ~10% agent-infra builders. Crowded: enterprise document/inbox bots. Open: voice agents with a live demo, agent eval and audit trails, hardware, proactive personal agents. Winners elsewhere showed a live result, used the sponsor tool deeply and solved a concrete problem. The recon's public "winning architecture" (planner → boxd workers → deterministic core for math → policy gate with human approval for writes → signed action log) will be copied by rivals, so differentiate.
- **Ideas shortlist** (superseded on 2026-11-14 by the AI Act Governance Copilot; kept for reference): (1) *Agent payslip*: per-run budget, treg receipts, timesheet and ROI review vs a human baseline (wrapper for any vertical); (2) *Black-box recorder*: signed action log, replay and live approve gate; (3) lab-notebook agent for Biotech (paper → protocol → rerun the stats); (4) messy document → personalised video briefing (fal); (5) proactive life-admin agent with approval gate; (6) physical/hardware agent; (7) Greek voice agent (riskiest because of the Wonderful terms); (8) agent-ready converter: site → MCP server + `llms.txt`; (9) Greek paperwork agent; (10) race-itself agent trying N approaches in parallel, with Iris picking the winner. Current favourite: 1 + 2 as a wrapper plus whichever vertical fits the brief.
- **Don't get biased by the sandbox/boxd:** it is optional and we may not use it at all. The core of the idea is **Langfuse**: easy to use, and it lets us (and the judges) **review the agent's work step by step at the end** (every plan step, tool call, cost and output). Design the demo around that replayable trace, not around any specific partner tool; use partner credits only where they genuinely fit.

## The product: AI Act Governance Copilot (design 2026-11-14)

Read first: [docs/architecture/README.md](docs/architecture/README.md) (summary + diagrams), [docs/architecture/agent-context.md](docs/architecture/agent-context.md) (context, plugins, memory, filesystem), full design PDF in Greek: `docs/architecture/ai-act-governance-copilot.pdf` (its §12 is the MVP and overrides §9 / §11.5).

- **What:** an agentic EU AI Act compliance assistant run in-house. **MVP = AI Engineer pillar only, for high-risk systems the org builds as provider.** Risk class and system card are seeded (as if PM + AI Officer made them). Given a system + its model(s), the agent derives the applicable requirements, plans tests, generates auditable synthetic data, runs tests in the sandbox, and returns findings with reasoning **and** counter-arguments, plus an engineer report and a management report. When the law/guidelines change it finds affected systems and re-runs what's needed.
- **Principles:** human-in-the-loop (agents write `proposed`, humans make `approved`); every claim cites a source; deterministic skeleton (code/YAML rules), LLM only for judgement; every finding locks `kb_version`; fairness thresholds are the org's, not the law's (say so in findings).
- **Containers:** existing `backend` (API, cards, runs, findings, webhooks, Telegram) and `agents` (LangGraph test + impact pipelines), `sandbox` (no network except target + MLflow), Postgres, Redis, Langfuse (trace = audit trail); new `frontend` (Vite + React engineer workspace), `reg-memory` / RKS (all regulation, versioned YAML corpus in git, watcher, diff, change judge), `mlflow` (models + test runs).
- **Engineer pipeline:** `load_context → plan_tests → [HITL approve plan] → generate_data → [HITL audit datasets] → execute (sandbox, one MLflow run per test) → analyse → critic (tries to overturn each finding) → report`. Verdicts: `supports_compliance | indicates_gap | inconclusive | not_assessable_by_testing`.
- **Regulation change:** Firecrawl monitor → RKS provision-level diff (`content_hash`) → LLM classifies change → `RegChange` + candidate `kb_version` → HITL accept → impact index (no LLM) → change judge per system (`no_impact | reinterpret_existing_evidence | rerun_tests | new_tests_needed`) → inbox + Telegram → re-run → delta report. Old decisions are marked `stale`, never rewritten.
- **Agent context = 4 sources, all files in a Postgres-backed virtual filesystem** (extends the agents service's `CompositeBackend`; tables `workspace_file_blobs`, `workspace_files` (versioned), `workspace_file_meta` (+pgvector), `workspace_events` (append-only audit, logs reads too)):
  - `/regulation/`: all regulation (AI Act, Omnibus, guidelines, FAQs, standards, national law, internal policies), read-only, pinned to the run's `kb_version`.
  - `/systems/<id>/`: the **system dossier** ("the folder"): `system-card.yaml`, `architecture.yaml`, docs, evidence, gaps.
  - `/systems/<id>/plugins/<name>/`: a **plugin** = configured connection to one model/endpoint: `plugin.yaml` (target card: access type `mlflow_model | rest | llm_chat | batch_file | dataset_only`, pipeline placement, I/O, expected behaviour, scenario hints; secrets only as `secret_ref`) + docs, `data/training-data.md`, `data/data-dictionary.yaml`, notes the engineer uploads at configuration. Drives scenarios, use cases and synthetic data.
  - `/memory/systems/<id>/` (engineer approves) and `/memory/org/` (AI Officer approves, regression-checked): **self-improving memory** from human feedback at gates (rejections with reason category). One YAML file per entry + `INDEX.md`; lifecycle `proposed → active → (promote) → stale/retired`; agents may write only `/memory/proposals/`; outputs must cite memory ids ("applied MEM-0042"); every use is a Langfuse span.
- **Seed data:** SYS-001 CV Screener (Annex III 4(a), biased via postcode proxy), SYS-002 Credit Scorer (Annex III 5(b), nearly clean), prior runs/findings for both.
- **Demo spine:** live test run with HITL gates → finding + critic → reject a test → memory → promote → next system planned right, citing the memory → live regulation change (mirrored guideline page + Firecrawl "Check now") → Telegram alert → re-run → delta report. Langfuse shows every step.
- **Open:** which "decision model" for the change judge (Oumi *Iris* candidate); LLM provider; whether the Omnibus changed ex-Art. 10(5) (protected attributes in bias tests).

## Layout

- The product (name and branding still to be decided) goes in its own folder named after it: one subfolder per service, each with its own Dockerfile, and a `docker-compose.yaml` in the product folder wrapping them.
- Root `pyproject.toml` + `uv.lock` hold **repo tooling only** (ruff, pytest, pre-commit); service dependencies live inside each service.
- `branding/brand.json` is the brand source of truth (name, semantic colour tokens light + dark, fonts, logos). Never hard-code brand values elsewhere; read them from there (`export_tokens.py` → CSS vars).
- `presentations/decks/<deck>/deck.yaml` → `presentations/build.py` → `presentations/dist/<deck>.pptx` (git-ignored). New layouts go in `LAYOUTS` + `RENDERERS` and the README table.
- `product/` (placeholder name until the product is named) holds the services and `docker-compose.yaml`: `backend` (FastAPI, ported from mAgenticX's dialogue bridge), `agents` (port 8003, internal), `reg-memory` (port 8010, internal: downloads the AI Act + supporting documents into one versioned `/data` volume with text and diffs; `docs/services/reg-memory.md`, tests in `tests/reg_memory/`), `model-gateway` (port 8000, host 8200: seed models from MLflow as bearer-auth, rate-limited REST endpoints + the simulated SYS-004 chatbot with planted flaws; `docs/services/model-gateway.md`, tests in `tests/model_gateway/`), `mlflow` (tracking server + registry, host 5500, `mlflow` database on Postgres, `mlflow_artifacts` volume) and `mlflow-seed` (one-shot: synthetic data → train → register `sys-00X-*@champion`, idempotent by `seed_hash`; case dossiers in `product/mlflow-seed/cases/`, answer keys in `_answer-key/`, exported to the `seed_cases` volume; `docs/services/mlflow.md`, tests in `tests/mlflow_seed/`), `sandbox` runner, `frontend` (Vite + React + Tailwind SPA served by nginx on host 8080, proxies `/api` → backend; design system in `src/shared/ui` (import from `@/shared/ui`, colours only via brand tokens), features in `src/features/<name>/{components,hooks,handlers,lib}`, thin `src/pages/*View.tsx`, mock mode `VITE_USE_MOCKS=true` with handlers auto-loaded from `src/shared/lib/mocks/handlers/`; checks `npm run typecheck|lint|test|build` in `product/frontend/`; `docs/services/frontend.md`), Postgres, Redis and a self-hosted Langfuse.
- **Backend rules:** no login; callers are an anonymous `X-Client-Id` (UUID), and every conversation query is scoped by `client_id` (miss = 404). **Exception (deliberate, for now):** systems, audits and memory (`/v1/systems`, `/v1/audits`, `/v1/memory`) are not scoped by client id; the client id is still the actor of every write ([backend systems](docs/services/backend-systems.md)). Rate limiting + structured logging on every endpoint. Routers thin → `utils/` logic → `schema/` (import from leaf modules; the `__init__` barrels stay empty). All imports at module top. Schema changes: edit `core/database/models.py` + a new Alembic migration (`alembic check` must pass). One `requirements.txt` (runtime + tests). Backend tests live in `tests/backend/` (own `pytest.ini`, run with the backend venv: `product\backend\.venv\Scripts\python -m pytest tests/backend`); docs live in the root `docs/`. The agents-service contract is `docs/contracts/agents-contract.md`; AG-UI is always the run protocol.
- Repo-level tests in `tests/`; docs in `docs/` (`guides/`, `architecture/`, `services/`, `contracts/`; index in `docs/README.md`); helper scripts in `scripts/` (bash + PowerShell pairs).
- Diagrams: `docs/architecture/diagrams/build.py` draws every diagram as SVG + PNG from `brand.json` (Pillow; headless Edge is blocked on this PC). Edit the shapes there, never the PNGs, and rebuild; check the PNGs by eye.

## Commands

| Task | Command |
| --- | --- |
| Install | `uv sync` |
| All checks (same as CI) | `.\scripts\check.ps1` |
| Run the product | `.\scripts\stack.ps1 up` (= `docker compose --env-file .env -f product/docker-compose.yaml up -d --build`; WSL Docker on this PC) |
| Tests | `uv run python -m pytest` |
| Lint / format | `uv run ruff check .` / `uv run ruff format .` |
| Rebuild diagrams | `.\scripts\build-diagrams.ps1` |

## Rules

- **Commit on the go** (user decision 2026-11-14, many agents run in parallel): small Conventional Commits per finished piece, staging **only your own paths** (`git add <paths>`, never `git add -A` / `.`), retry if `.git/index.lock` is busy. **Commit message = one title line only**: no body, no Co-Authored-By or any other trailer/attribution. Shared files (compose, `.env.example`, CHANGELOG, READMEs, CI, CLAUDE.md) are committed by whoever finishes last touching them. **Never push, force, rebase or open PRs**; the user does all git remote work.
- Keep `scripts/*.sh` and `scripts/*.ps1` in sync: a change to one goes in the other.
- Tests must not call paid LLM APIs; mock provider clients.
- **One env file for everything:** repo-root `.env` (git-ignored) from `.env.example`, in compact sections (sponsor API keys and integrations first). Never add another `.env.example`; add every new variable to its section there. Secrets only in `.env`.
- Update `CHANGELOG.md` under `[Unreleased]` and the relevant `docs/` page with each change.
- **End-of-day reminder (hackathon, 14-15 Nov):** the user is working from a borrowed PC. Before they finish for the day, remind them to log out of everything: GitHub (`gh auth logout`), git credentials (Windows Credential Manager) and `git config user.name/email`, Docker, browser sessions and any other signed-in accounts. Also clear `.env` secrets and the cloned repos if they should not stay on this machine.
