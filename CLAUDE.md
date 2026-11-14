# genAI-summit — Claude instructions

Project for the GenAI Summit. Repo: `EXARTeo/genAI-summit`. Currently scaffolding only.

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

## Layout

- The product (name and branding still to be decided) goes in its own folder named after it: one subfolder per service, each with its own Dockerfile, and a `docker-compose.yaml` in the product folder wrapping them.
- Root `pyproject.toml` + `uv.lock` hold **repo tooling only** (ruff, pytest, pre-commit); service dependencies live inside each service.
- `branding/brand.json` is the brand source of truth (name, semantic colour tokens light + dark, fonts, logos). Never hard-code brand values elsewhere; read them from there (`export_tokens.py` → CSS vars).
- `presentations/decks/<deck>/deck.yaml` → `presentations/build.py` → `presentations/dist/<deck>.pptx` (git-ignored). New layouts go in `LAYOUTS` + `RENDERERS` and the README table.
- `product/` (placeholder name until the product is named) holds the services and `docker-compose.yaml`: `backend` (FastAPI, ported from mAgenticX's dialogue bridge), Postgres, Redis and a self-hosted Langfuse. The agents service and maybe a UI come next.
- **Backend rules:** no login; callers are an anonymous `X-Client-Id` (UUID), and every conversation query is scoped by `client_id` (miss = 404). Rate limiting + structured logging on every endpoint. Routers thin → `utils/` logic → `schema/` (import from leaf modules; the `__init__` barrels stay empty). All imports at module top. Schema changes: edit `core/database/models.py` + a new Alembic migration (`alembic check` must pass). One `requirements.txt` (runtime + tests). Backend tests live in `tests/backend/` (own `pytest.ini`, run with the backend venv: `product\backend\.venv\Scripts\python -m pytest tests/backend`); docs live in the root `docs/`. The agents-service contract is `docs/agents-contract.md`; AG-UI is always the run protocol.
- Repo-level tests in `tests/`; docs in `docs/`; helper scripts in `scripts/` (bash + PowerShell pairs).

## Commands

| Task | Command |
| --- | --- |
| Install | `uv sync` |
| All checks (same as CI) | `.\scripts\check.ps1` |
| Run the product | `docker compose -f <product>/docker-compose.yaml up -d --build` |
| Tests | `uv run pytest` |
| Lint / format | `uv run ruff check .` / `uv run ruff format .` |

## Rules

- Never commit, push or open PRs; the user does all git remote work. Give a commit title when asked.
- Keep `scripts/*.sh` and `scripts/*.ps1` in sync: a change to one goes in the other.
- Tests must not call paid LLM APIs; mock provider clients.
- Secrets only in `.env` (git-ignored); add every new variable to `.env.example`.
- Update `CHANGELOG.md` under `[Unreleased]` and the relevant `docs/` page with each change.
