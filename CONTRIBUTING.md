# Contributing

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

You need Postgres and Redis running (see README for Docker one-liners). Run migrations before starting the app:

```bash
alembic upgrade head
```

## Before you open a PR

```bash
ruff check .
ruff format --check .
mypy .
pytest -m "not infra"
pytest -m infra   # only if you have Postgres/Redis pointed at what tests/conftest.py expects
```

CI runs all of this. Don't push if any of it fails locally — it'll fail in CI too.

## Making a change

- New migration: `alembic revision --autogenerate -m "description"`, then **read the generated file**. Autogenerate gets server defaults, enum diffs, and index names wrong often enough that you can't skip this.
- New endpoint: router stays thin (parse request, call a service, return a schema). Business rules go in `services/`, DB access in `repositories/`. Don't put query logic in a router.
- Raise `HydraError` subclasses (`core/exceptions.py`), not raw `HTTPException`, for anything outside the gateway proxy layer (`gateway/`, `api/gateway/`) — the proxy has its own error mapping to upstream-facing status codes.
- Touching the gateway hot path (`gateway/trie.py`, `gateway/proxy.py`, `api/gateway/router.py`)? Check the docstrings first — there's a specific ordering (auth → route match → scope → method → rate limit → circuit breaker → forward) that other checks depend on.

## Commits and PRs

- Commit messages: what changed and why, not a narration of the diff.
- One logical change per PR. If you're fixing a bug and refactoring nearby code, split it — makes review and revert both easier.
- Add a test for the behavior you're adding or fixing. If you can't write one (e.g. it needs infra you don't have), say so in the PR description.

## Code style

- Full type hints, `mypy --strict` passes as-is — don't add `# type: ignore` without a comment saying why.
- No comments explaining *what* the code does; names should carry that. Comment only the non-obvious *why* (a workaround, an ordering constraint, a subtle invariant).
- Don't add abstractions, config flags, or error handling for cases that can't happen in this codebase. If it's not needed yet, don't build it yet.
