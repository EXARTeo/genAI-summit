# Contributing

## Workflow

1. Create a branch from `main`: `feat/<short-name>`, `fix/<short-name>` or `docs/<short-name>`.
2. Make your change, with tests for new behaviour.
3. Run `./scripts/check.sh` (or `.\scripts\check.ps1`) until it passes.
4. Open a pull request into `main` and fill in the template. CI must be green before merging.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat(scope): add something
fix(scope): correct something
docs: update the README
chore: bump dependencies
```

## Code style

- Formatting and linting: `ruff` (configured in `pyproject.toml`). The pre-commit hooks run it for you.
- Type hints on all public functions.
- Keep secrets out of code and git. Use `.env` (see `.env.example`).

## Tests

- Tests live in `tests/` and are named `test_*.py`.
- Tests must not call paid LLM APIs. Mock the provider client instead.
