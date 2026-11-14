# genAI-summit

Project for the GenAI Summit.

> **Status:** scaffolding only. The repository has its tooling and CI in place; the product (its name, branding and services) is still to be created.

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

Backend: <http://localhost:8100>. Langfuse: <http://localhost:3400> (dev login `admin@example.com` / `genai-summit-dev-1`).

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
