# Contributing to saga-agents

Thanks for your interest in contributing! This project follows the same conventions
as the other Saga components.

## Getting started

```bash
# 1. Install uv: https://docs.astral.sh/uv/
# 2. Install dependencies and the pre-commit hooks
uv sync
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

## Development workflow

We use **Git Flow**:

- `main` — released, production-ready code (tagged releases only).
- `develop` — integration branch for the next release.
- `feature/<name>` — new features; branch from and merge into `develop`.
- `fix/<name>` — non-urgent fixes; branch from and merge into `develop`.
- `release/<version>` — release stabilisation; branch from `develop`, merge into
  `main` **and** `develop`.
- `hotfix/<version>` — urgent production fixes; branch from `main`, merge into `main`
  **and** `develop`.

Open pull requests against `develop` (or `main` for hotfixes).

## Quality gates (run before pushing)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

CI runs the same checks plus a Docker image build. All must pass; coverage must stay ≥ 80 %.

## Coding standards

- Python **3.12+**, **fully typed** (`mypy --strict`).
- **English** for all code, comments, and docs.
- No hard-coded config or secrets — use environment variables / `.env`.
- Reach SAGA only through the MCP server (HTTP); never add direct database / object-storage
  access.
- Meaningful, actionable error messages; structured logging (no `print`).
- New behaviour comes with unit tests that mock SAGA MCP, Redis, and the LLM.

## Adding an agent

Agents are declarative — add a `config/agents/<id>.md` file (YAML frontmatter + system
prompt). No code change is required unless you are extending the runtime itself. See the
[README](README.md) for the frontmatter schema.

## Commit messages — Conventional Commits

Format: `type(scope): summary`

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`,
`ci`, `chore`, `revert`.

Examples:

```
feat(triggers): add jitter to the cron scheduler
fix(runtime): enforce max_tool_calls before the final step
docs: document the proposal approval API
ci: add Docker build step to CI workflow
```

Breaking changes: add `!` after the type/scope or a `BREAKING CHANGE:` footer.
Release notes are generated from these messages via `git cliff`.

## Reporting issues

Use the GitHub issue templates. Include reproduction steps, expected vs. actual
behaviour, logs (with secrets redacted), and your environment.

By contributing, you agree that your contributions are licensed under the project's
[Apache-2.0 license](LICENSE).
