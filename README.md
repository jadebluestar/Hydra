# Hydra

An API gateway and developer platform: authenticate traffic with API keys, route it to upstreams by path prefix, rate-limit and circuit-break it, and log every request. Built on FastAPI, Postgres, and Redis.

## What's in here

- **Control plane** (`/api/v1`) — JWT-authenticated management API: orgs, projects, upstreams, routes, API keys, analytics.
- **Data plane** (`/gateway`) — API-key-authenticated proxy. Matches inbound paths against a per-project trie, checks scope/method/rate-limit/circuit-breaker, forwards to the upstream, logs the result.
- **Playground** (`/playground`) — a small built-in Postman-like UI for firing ad-hoc requests through the control plane's `/api/v1/playground/execute` proxy endpoint (avoids CORS, no external tool needed).

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

This brings up the app, Postgres, Redis, and Prometheus/Grafana. Once it's healthy:

```bash
alembic upgrade head          # run once, or exec it inside the app container
```

Then:
- API: http://localhost:8000/docs (Swagger, dev only)
- Playground: http://localhost:8000/playground/
- Grafana: http://localhost:3000 (admin/admin)
- Prometheus: http://localhost:9090

### Running without Docker Compose

If you don't have the `docker compose` plugin, run Postgres/Redis yourself and point `.env` at them:

```bash
docker run -d --name hydra-pg -e POSTGRES_USER=hydra -e POSTGRES_PASSWORD=hydra_secret \
  -e POSTGRES_DB=hydra -p 5432:5432 postgres:16-alpine
docker run -d --name hydra-redis -p 6379:6379 redis:7-alpine

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

alembic upgrade head
uvicorn main:app --reload
```

Register a user before using the playground — there's no signup form in the UI yet:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"yourpassword123"}'
```

## Testing

```bash
pytest -m "not infra"   # unit tests, no external services needed
pytest -m infra         # requires Postgres + Redis running, see tests/conftest.py for expected DATABASE_URL/REDIS_URL
```

## Project layout

```
api/            FastAPI routers (api/v1/* = control plane, api/gateway/* = data plane)
gateway/         proxy engine: trie matching, auth, rate limiting, circuit breaker
models/          SQLAlchemy models
repositories/    DB access, one per aggregate
services/        business logic, called from routers
schemas/         Pydantic request/response models
providers/       swappable implementations (JWT, password hashing, email)
security/        RBAC roles/scopes
alembic/         migrations
web/playground/  the Postman-like UI (static, no build step)
tests/           unit/ (no infra) and integration/ (marked @pytest.mark.infra where DB/Redis are needed)
```

## Conventions

- Python 3.12+, fully typed, `mypy --strict` (see `pyproject.toml`).
- Lint/format with `ruff check .` and `ruff format .`.
- Errors are `HydraError` subclasses (`core/exceptions.py`) — don't raise raw `HTTPException` outside the gateway/proxy layer.
- Routers stay thin: validate input, call a service, return a schema. Business logic belongs in `services/`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.
