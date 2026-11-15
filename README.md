# genAI-summit

Project for the GenAI Summit.

> **Status:** the product is **Mnamon**, an agentic EU AI Act compliance copilot ([mnamon/](mnamon/)): it audits high-risk ML systems end to end (obligations, synthetic data, tests, sealed findings, reports) with human gates.

## What Mnamon does

Mnamon checks an organisation's high-risk AI systems against the EU AI Act. Agents do the tedious work (find the obligations that apply, plan tests, make synthetic data, run the model, judge the results); people approve each step. Every step is traced in Langfuse.

### Three roles

There is no login. The roles describe who does what; the app does not enforce them.

| Role | What they do | Status in this build |
| --- | --- | --- |
| **AI Engineer** | Takes a registered system, adds docs to its folder, **builds its pipeline in the Plugins tab** (models, upstream systems, human review steps and how they connect), configures one **plugin** per model (how the agent calls the model on the local MLflow server), then runs audits with human gates | **Built** (the MVP) |
| **AI Officer** | Oversees everything: all systems, audits, the findings register, regulation changes and their impact | Built as the shared read view (systems list, Status tab, audits list, regulation inbox). No separate officer UI or permissions |
| **PM (product manager)** | Registers new systems with documents only: system card, risk class, documentation. Does **not** define the pipeline or the models; that is the engineer's job | **Not built.** Systems are seeded (SYS-001 to SYS-003, `POST /v1/admin/import-seed`); the API has `POST /v1/systems` but there is no registration screen. A small risk-classification agent is **planned**: from a system description it proposes the AI Act risk class and Annex III basis with citations, and a human approves it |

### The engineer flow

1. **System**: open a registered system (system card, architecture graph, docs, data dictionary).
2. **Pipeline and plugins**: in the Plugins tab, build the system graph (*Add a model*, *Add a step* for an upstream system or a human review, connect with *Comes after* / *Goes to*), then click a model and confirm the plugin form. Defaults come from the graph and the MLflow registry; override only what differs.
3. **Audit**: start an audit on one plugin. The pipeline grounds the applicable obligations, plans scenarios, generates and checks synthetic data, runs the model and judges each obligation. You approve scenarios, public data and datasets at three gates.
4. **Findings and reports**: findings are sealed (hash chain, critic review, citations at a pinned `kb_version`), with an engineer report and a management report.
5. **Regulation change**: a watched source changes → impact on each system → focused re-run → delta report.

### Built vs not built

- No login and no role permissions.
- PM registration screen and the risk-classification agent: not built (systems are seeded).
- **One plugin per audit.** A system with two models (SYS-001: CV parser + CV ranker) is audited one model at a time. A single audit across several plugins is future work.

More: [architecture](docs/architecture/README.md), [agent context and plugins](docs/architecture/agent-context.md), [audit pipeline](docs/services/agents-pipeline.md), [backend: systems and plugins](docs/services/backend-systems.md#plugins).

## Quick start

Requirements: [Docker](https://docs.docker.com/get-docker/) with Compose, plus [Python 3.12](https://www.python.org/) and [uv](https://docs.astral.sh/uv/) for the repo tooling.

```bash
git clone https://github.com/EXARTeo/genAI-summit.git
cd genAI-summit
cp .env.example .env        # then fill in your keys
uv sync                     # installs the repo tooling (ruff, pytest, pre-commit)
```

Run the product (backend + Postgres + Redis + Langfuse; see [mnamon/README.md](mnamon/README.md)):

```bash
cp .env.example .env        # the ONE env file (optional: dev defaults are built in)
./scripts/stack.sh up       # Windows: .\scripts\stack.ps1 up (uses WSL Docker if needed)
```

App: <http://localhost:8080> (`FRONTEND_PORT`). Backend: <http://localhost:8100>. Langfuse: <http://localhost:3400> (dev login `admin@example.com` / `genai-summit-dev-1`).

Or run the setup script for the tooling steps above:

| OS | Command |
| --- | --- |
| Linux / macOS | `./scripts/setup.sh` |
| Windows | `.\scripts\setup.ps1` |

## Development

| Task | Command |
| --- | --- |
| Run all checks (lint, format, tests, compose config) | `./scripts/check.sh` or `.\scripts\check.ps1` |
| Tests | `uv run python -m pytest` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Install git hooks | `uv run pre-commit install` |
| Build presentation decks | `./scripts/build-decks.sh` or `.\scripts\build-decks.ps1` |
| Export brand CSS variables | `uv run python branding/export_tokens.py` |

CI runs the same checks on every push and pull request to `main` (see [.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Repository layout

```text
genAI-summit/
├── .github/             # CI workflow, Dependabot, issue and PR templates
├── branding/            # Brand source of truth: name, colours, fonts, logos
├── presentations/       # YAML decks -> branded .pptx (scripts/build-decks.*)
├── docs/                # Project documentation
├── scripts/             # Setup and check scripts (bash + PowerShell)
├── mnamon/              # The product (Mnamon, named after the brand): one folder per service
│   ├── <service>/       #   each with its own Dockerfile and code
│   └── docker-compose.yaml  # wraps all the services
├── tests/               # Repo-level pytest checks
├── .env.example         # Environment variables template (copy to .env)
└── pyproject.toml       # Dependencies and tool configuration
```

## Documentation

- [Getting started](docs/guides/getting-started.md)
- [Branding](branding/README.md)
- [Presentations](presentations/README.md)
- [Architecture](docs/architecture/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE)
