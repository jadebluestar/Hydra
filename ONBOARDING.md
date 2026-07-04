# Hydra — Engineering Onboarding

Welcome to the team. This doc is meant to get you from "never seen this repo" to "can answer any question about it in a design review." Read it top to bottom once, then use it as a reference. I'm writing this the way I'd explain it to you in person, so it's long — that's on purpose.

## Table of contents

1. [The elevator pitch](#1-the-elevator-pitch)
2. [The one mental model that matters: control plane vs data plane](#2-the-one-mental-model-that-matters-control-plane-vs-data-plane)
3. [Tech stack, and why each piece was chosen](#3-tech-stack-and-why-each-piece-was-chosen)
4. [The domain model](#4-the-domain-model)
5. [Directory tour](#5-directory-tour)
6. [Request lifecycle #1: a control-plane call](#6-request-lifecycle-1-a-control-plane-call)
7. [Request lifecycle #2: a gateway proxy call](#7-request-lifecycle-2-a-gateway-proxy-call)
8. [Authentication deep dive](#8-authentication-deep-dive)
9. [Authorization deep dive: RBAC vs Scopes](#9-authorization-deep-dive-rbac-vs-scopes)
10. [The gateway internals](#10-the-gateway-internals)
11. [The database layer](#11-the-database-layer)
12. [Migrations with Alembic](#12-migrations-with-alembic)
13. [Redis usage inventory](#13-redis-usage-inventory)
14. [Observability: logging, correlation, metrics](#14-observability-logging-correlation-metrics)
15. [Error handling](#15-error-handling)
16. [The Playground](#16-the-playground)
17. [Testing strategy](#17-testing-strategy)
18. [CI/CD](#18-cicd)
19. [Docker & deployment](#19-docker--deployment)
20. [Walkthrough: setting up a working gateway from scratch](#20-walkthrough-setting-up-a-working-gateway-from-scratch)
21. [Glossary](#21-glossary)
22. [Gotchas — things that will trip you up](#22-gotchas--things-that-will-trip-you-up)

---

## 1. The elevator pitch

Hydra is an **API gateway** with a **management API** bolted on top of it — think "a tiny, self-hosted Kong" plus the admin dashboard you'd need to configure it.

Two things it does:

- **Lets your team configure gateway behavior**: which upstream backends exist, which URL paths route to which backend, what auth/rate-limits apply, who on your team can change any of this.
- **Actually proxies traffic** according to that configuration: an inbound HTTP request hits Hydra, Hydra figures out which upstream it should go to, checks the caller is allowed to do that, forwards the request, and logs what happened.

If you've used Kong, Nginx with `proxy_pass`, AWS API Gateway, or Envoy — same idea, smaller and readable enough that a new hire (you) can hold the whole thing in their head in a week.

## 2. The one mental model that matters: control plane vs data plane

Every question you'll ever have about "why does this code look like this" traces back to this split. Get this and the rest of the codebase makes sense on sight.

**Control plane** — `/api/v1/*`
- Who: your team, logged into a dashboard.
- Auth: JWT (a login session).
- What it does: CRUD on organizations, projects, upstreams, routes, API keys. Configuration, not traffic.
- Files: `api/v1/`, `services/`, `repositories/`, `models/`.

**Data plane** — `/gateway/*`
- Who: your customers' applications, calling your API through Hydra.
- Auth: an API key (`hk_live_...`), not a user login.
- What it does: takes the actual HTTP request, matches it to a route, and forwards it to the real backend. This runs on every single API call your customers make, so it's written to be fast — no unnecessary DB round-trips per request.
- Files: `gateway/`, `api/gateway/router.py`.

Why keep them apart? Different auth mechanisms, wildly different performance requirements (control plane: a human clicking a button, latency doesn't matter; data plane: thousands of requests/second, every millisecond counts), and different blast radius if something goes wrong. Mixing them in one router would make both harder to reason about.

`main.py` wires this up explicitly:

```python
app.include_router(api_v1_router, prefix="/api/v1")   # control plane
app.include_router(gateway_router, prefix="/gateway")  # data plane
```

## 3. Tech stack, and why each piece was chosen

| Piece | Why |
|---|---|
| **FastAPI** | Async-native, Pydantic-validated request/response, auto-generated OpenAPI docs at `/docs`. It's the obvious choice for an async Python API in 2024+. |
| **Pydantic v2** | Every request body and response shape is a typed schema (`schemas/`). Invalid input never reaches business logic. |
| **PostgreSQL** | The system of record. JSONB columns (`routes.methods`, `api_keys.scopes`) give us flexible array/list storage with actual indexing, unlike a plain text blob. |
| **SQLAlchemy 2.0 (async) + asyncpg** | ORM + the fastest Postgres driver for Python async. `AsyncSession` everywhere — there is no sync DB code in this repo. |
| **Alembic** | Schema migrations, versioned and reversible. Every schema change is a file in `alembic/versions/`. |
| **Redis** | Everything that needs to be fast and shared across processes but doesn't need to survive a restart forever: rate-limit counters, circuit-breaker state, JWT revocation, refresh-token storage. |
| **python-jose** | JWT encode/decode (HS256). |
| **argon2-cffi** | Password hashing. OWASP's recommended algorithm — see [§8](#8-authentication-deep-dive) for why it's used for passwords but *not* for API keys. |
| **httpx.AsyncClient** | Both the gateway's upstream forwarding and the Playground's ad-hoc requests go through one shared async HTTP client (connection pooling, reused across every proxied request). |
| **structlog** | Every log line is a structured JSON object (or colorized console output in dev), with request context (request ID, correlation ID) automatically attached. See [§14](#14-observability-logging-correlation-metrics). |
| **Prometheus + Grafana** | Metrics collection and dashboards (`docker-compose.yml`, `docker/prometheus/`). |
| **Docker / docker-compose** | Local dev environment: app + Postgres + Redis + Prometheus + Grafana, one command. |
| **pytest + pytest-asyncio** | All tests are async. Split into `unit/` (no external services) and `integration/` (needs Postgres/Redis, marked `@pytest.mark.infra`). |
| **ruff** | Lint + format, one tool instead of flake8+isort+black. |
| **mypy --strict** | Full static typing. If you add a function without type hints, CI will reject it. |

## 4. The domain model

```
Organization
 ├── OrganizationMembership (User × Role)   ← who's on the team, and what they can do
 └── Project                                 ← a logical grouping, e.g. "production", "staging"
      ├── Upstream                           ← a real backend: base_url, timeout, retries
      │    └── Route (many routes → one upstream is allowed)
      ├── Route                              ← "requests to /api/v1/users go to upstream X"
      └── APIKey                             ← credential customers use to call through the gateway
```

Plus `User` (a Hydra dashboard login) and `RequestLog` (one row per gateway request, for analytics — not part of the config hierarchy, just an event stream).

**Why this shape?**

- **Organization → Project**: an org is a company/team. A project is an environment or product within it ("acme-corp" org has "production" and "staging" projects). Projects don't share routes or keys — a staging API key can't touch production routes.
- **Upstream vs Route are separate**: an upstream is *where* traffic goes (`http://user-service:8080`). A route is *when* to send it there (`/api/v1/users` → that upstream). One upstream can back multiple routes. This mirrors Kong/Nginx's own upstream/route split — don't collapse them into one table, you'll regret it the first time two routes need to share a backend.
- **APIKey belongs to a Project, not a User**: keys authenticate *applications*, not people. A project can have many keys (one per client app, or per environment) and revoking one doesn't touch the others.
- **RequestLog has no foreign keys**: it intentionally does **not** reference `projects.id` etc. with an FK constraint — it stores the UUID as a plain column. Logs need to outlive the entities they describe. If you delete a project, its historical request logs should still be queryable, not cascade-deleted or become dangling FK violations.

Every model that a user can meaningfully "delete" (`User`, `Organization`, `Project`, `APIKey`, `Upstream`, `Route`) inherits `HydraSoftDeleteBase` — deletion sets `deleted_at`, never actually removes the row. Event-log-style tables (`RequestLog`) inherit plain `HydraBase` — there's no such thing as "undeleting" a log line, so there's no `deleted_at` to manage. `OrganizationMembership` also uses `HydraBase` (hard delete) — see `models/membership.py`'s docstring for why (a revoked membership isn't a "soft" state you'd want to see in the UI; it's just gone, add a domain event if you need an audit trail).

## 5. Directory tour

The layering is strict and it's the same in every module: **router → service → repository → model**. If you're not sure where new code goes, this table tells you.

```
main.py               # App factory: creates FastAPI app, wires middleware, mounts routers
core/
  config.py           # Settings — one Pydantic BaseSettings class, reads .env
  exceptions.py       # HydraError hierarchy + FastAPI exception handlers
  logging.py          # structlog configuration

api/
  v1/                 # Control plane routers — one folder per resource
    auth/              organizations/          projects/
    upstreams/          routes/                 analytics/
    playground/         health/                deps.py (get_current_user)
  gateway/
    router.py          # The single catch-all proxy route

gateway/               # Data-plane ENGINE — not routers, the actual proxy logic
  trie.py              # PathTrie — in-memory route matching
  auth.py              # API key extraction + scope checking
  rate_limiter.py       # Redis sliding-window rate limiting
  circuit_breaker.py     # Upstream health circuit breaker
  proxy.py               # forward_request() — the actual httpx call to upstream
  state.py               # GatewayState — per-process trie cache + shared http client
  logger.py               # write_request_log() background task

models/                # SQLAlchemy ORM models — one file per table
repositories/          # DB access layer — one class per model, extends BaseRepository
services/              # Business logic — permission checks + orchestration, called by routers
schemas/               # Pydantic request/response shapes
security/
  rbac.py              # Role → Permission mapping (control plane authorization)
  scopes.py            # API key scope checking (data plane authorization)
domain/
  enums/               # Role, Permission, APIKeyScope, CircuitState — plain string enums
  value_objects/       # Email, RoutePath — validated immutable wrappers around primitives

providers/
  interfaces/          # Protocol classes — the CONTRACT (JWTProvider, HashingProvider, ...)
  implementations/     # Concrete classes (HS256JWTProvider, Argon2Hasher, MockEmailProvider)

middleware/            # RequestID, CorrelationID, Logging — see §14 for ordering
database/
  base.py               # Declarative Base + mixins (UUIDMixin, TimestampMixin, SoftDeleteMixin)
  session.py            # Async engine/session factory, get_db() dependency
cache/
  client.py             # Redis connection pool
  keys.py               # Every Redis key format, in one place

alembic/                # Migrations
web/playground/          # The Postman-like UI — static HTML/CSS/JS, no build step
tests/
  unit/                  # No external services required
  integration/            # Needs Postgres + Redis, marked @pytest.mark.infra
```

**The provider pattern is worth understanding on its own.** `providers/interfaces/` defines `Protocol` classes (structural typing — Python's version of an interface). `providers/implementations/` has the concrete classes. Services depend on the *interface* type, never the concrete class:

```python
class AuthService:
    def __init__(self, *, jwt_provider: JWTProvider, hasher: HashingProvider, ...): ...
```

This means tests can pass a fake `HashingProvider` without touching Argon2 at all, and swapping HS256 for RS256 JWTs later means writing one new class, not touching `AuthService`.

## 6. Request lifecycle #1: a control-plane call

Trace `POST /api/v1/projects/{project_id}/api-keys` (creating an API key) end to end — this is the shape every control-plane endpoint follows.

1. **Middleware** (outermost to innermost, per `main.py`): `RequestIDMiddleware` → `CorrelationIDMiddleware` → `LoggingMiddleware` → CORS. Each stamps something on `request.state` or logs.
2. **Router** (`api/v1/projects/router.py`): declares the path, the Pydantic request body (`CreateAPIKeyRequest`), and depends on `current_user: CurrentUser` (`= Annotated[User, Depends(get_current_user)]`).
3. **`get_current_user`** (`api/v1/deps.py`): pulls the `Authorization: Bearer <jwt>` header, decodes it, checks the JTI isn't in the Redis revocation set, loads the `User` row. Raises `UnauthorizedError` (→ 401) at any failure.
4. **Router body**: builds an `APIKeyService` (a plain Python object — services are constructed fresh per-request in the router, not DI-framework-injected), calls `svc.create(...)`.
5. **Service** (`services/api_key_service.py`): this is where permission checks and business rules live.
   - `_require_permission()` loads the `Project`, then the caller's `OrganizationMembership` for that project's org, then calls `rbac.require_permission(role, Permission.CREATE_API_KEY)` — raises `ForbiddenError` (403) if the role doesn't have it.
   - `validate_requested_scopes()` rejects unknown scope strings.
   - `utils.api_key.generate_api_key()` creates the actual key + its SHA-256 hash.
   - Calls the repository to persist it.
6. **Repository** (`repositories/api_key_repository.py` → `BaseRepository`): `session.add()` + `flush()` + `refresh()`. Note: **repositories never commit**. The session's lifecycle is owned entirely by `get_db()`.
7. **Back in `get_db()`** (`database/session.py`): after the route handler returns successfully, the dependency's `finally`-equivalent commits the transaction. If anything raised, it rolls back instead. This is why you'll never see `session.commit()` anywhere in a service or repository — one place owns that decision.
8. **Response**: the router wraps the ORM object in a Pydantic response schema (`APIKeyResponse.model_validate(...)`) and FastAPI serializes it to JSON.
9. **Exception path**: if any step raised a `HydraError` subclass, `core/exceptions.py`'s handler converts it to `{"error": ..., "message": ..., "details": ...}` with the right status code — the router itself never writes error-handling code.

## 7. Request lifecycle #2: a gateway proxy call

This is the hot path — the thing that runs on every single customer API call, so every step here was chosen for speed. It all lives in one function, `gateway_proxy()` in `api/gateway/router.py`, and its own docstring lists all 12 steps — here's what each one actually means and which file does the work:

1. **Extract API key** — `gateway/auth.py:extract_api_key()`. Just header parsing, no DB.
2. **Verify key** — `APIKeyService.verify()` (`services/api_key_service.py`). Extracts the key's 16-char prefix, looks up candidates by that indexed prefix (narrows to a handful of rows), then does a constant-time SHA-256 comparison against each candidate. Returns `None` (not an exception) on failure — the caller decides what a bad key means.
3. **Load the project's route trie** — `GatewayState.get_trie()` (`gateway/state.py`). **This is the key performance trick in the whole codebase.** The first request for a project loads all its routes from Postgres and builds an in-memory `PathTrie`. Every subsequent request for that project reuses the cached trie — **zero DB queries** to figure out routing. The trie is invalidated (evicted from the cache) only when routes/upstreams change (see `_invalidate()` calls in `api/v1/upstreams/router.py` / `routes/router.py`).
4. **Match path** — `PathTrie.match()` (`gateway/trie.py`). Longest-prefix match, segment-aware (`/api` does *not* match `/apikeys` — it splits on `/` first, so this can't happen by accident like naive string-prefix matching would allow).
5. **Scope check** — `gateway/auth.py:check_scope()`. Does the key's scopes satisfy the route's `required_scope`? 403 if not (401 would be wrong here — the key *is* valid, it's just not authorized for this).
6. **Method check** — is the HTTP method in the route's allowed list? 405 if not.
7. **Rate limit** — `gateway/rate_limiter.py:check_rate_limit()`. A Redis Lua script implementing a true sliding window (not fixed-window, which has a boundary-burst bug — see the file's docstring). 429 if exceeded.
8. **Circuit breaker check** — `CircuitBreaker.check()` (`gateway/circuit_breaker.py`). If the upstream has been failing, short-circuit to 503 *without even trying to call it*. See [§10](#10-the-gateway-internals) for the full state machine.
9. **Build target URL** — strip the route's path prefix if `strip_prefix=True`.
10. **Forward** — `gateway/proxy.py:forward_request()`. The actual `httpx` call to the upstream, using the **shared** `AsyncClient` from `GatewayState` (one connection pool for the whole process, not one-per-request). Maps upstream timeouts/connection failures to 504/502.
11. **Record circuit breaker outcome** — success or failure, based on whether the response status is in `{502, 503, 504}`.
12. **Return the response** to the customer.
13. **(Background, after the response is already sent)** — `write_request_log()` (`gateway/logger.py`) opens a *fresh* DB session (the request's session is already closed by this point) and inserts a `RequestLog` row. If this fails, it's logged and swallowed — a broken analytics write must never affect a live customer request.

Every one of steps 1–8 can short-circuit the whole thing with an exception (`HydraError` subclass), and the `finally` block always fires the background log write regardless of which step failed — that's why `log_status_code`, `log_project_id`, etc. are all declared as mutable locals at the top of the function before the `try`.

## 8. Authentication deep dive

There are **two completely separate auth mechanisms** in this codebase. Don't get them confused.

### JWT (control plane — humans)

- On login/register, `AuthService` (`services/auth_service.py`) issues an **access token** (15 min TTL) and a **refresh token** (7 day TTL), both JWTs signed with `HS256JWTProvider`.
- Claims: `sub` (user UUID), `jti` (unique token ID, for revocation), `exp`/`iat`, `type` (`"access"` or `"refresh"`).
- **Revocation**: JWTs can't be "deleted" — they're self-contained and valid until they expire, by design. To support logout, Hydra keeps a Redis **denylist**: on logout, the access token's `jti` is written to `hydra:revoked:{jti}` with a TTL equal to its remaining lifetime. `get_current_user` checks this set on every request.
- **Refresh token rotation**: every `/auth/refresh` call deletes the old refresh JTI from Redis and issues a brand new pair. A stolen refresh token can only be used once before the legitimate owner's next refresh invalidates it.
- **Timing-attack resistance**: `AuthService.login()` *always* runs Argon2 `verify()`, even when the email doesn't exist (against a cached "sentinel" hash). Otherwise, an attacker could tell registered vs. unregistered emails apart by how fast the response comes back.

### API keys (data plane — applications)

- Format: `hk_{env}_{32 hex chars}` (`hk_live_...` / `hk_test_...`), generated in `utils/api_key.py`.
- Hashed with **SHA-256**, not Argon2. Deliberately — see the docstring in `utils/api_key.py`: API keys already have 128 bits of randomness, so brute-forcing the *key itself* is infeasible regardless of hash speed. Argon2's whole point is to slow down guessing *low-entropy, human-chosen* secrets (passwords). Using Argon2 for a high-entropy key would just add 80ms of latency to every gateway request for no security benefit. Stripe, GitHub, and Twilio all do the same thing (fast hash for keys, slow hash for passwords).
- **Heads up**: the docstring at the top of `models/api_key.py` still says "Store an Argon2 hash of the full key" — that's stale, left over from an earlier design. The actual, tested behavior (`utils/api_key.py`, `services/api_key_service.py`) uses SHA-256. Trust the code, not that one comment, and feel free to send a one-line PR fixing the docstring if it bugs you as much as it bugs me.
- **Prefix-indexed lookup**: the first 16 characters are stored in an indexed `key_prefix` column. Verifying a key is "look up the handful of rows with this prefix, then SHA-256-compare each" rather than hashing and scanning the whole table.
- Revocation is a `revoked_at` timestamp (not soft-delete's `deleted_at`) — see `models/api_key.py`'s docstring for why that's a semantically different thing worth its own column.

### Passwords

Argon2id, via `providers/implementations/argon2_hasher.py`. Parameters: 64 MB memory cost, 3 iterations, 4 threads of parallelism — these are the OWASP 2024 minimums. Hashing happens inside `asyncio.to_thread()` because Argon2 deliberately takes ~80ms, and if you ran that on the event loop directly, the whole server would serve zero other requests for those 80ms.

## 9. Authorization deep dive: RBAC vs Scopes

Two more separate systems — one per plane, again.

**Control plane: Role + Permission (`security/rbac.py`)**
- A user's `OrganizationMembership.role` is one of `OWNER > ADMIN > MEMBER > VIEWER` (`domain/enums/role.py`).
- Each `Role` maps to a `frozenset[Permission]` (`domain/enums/permission.py` has ~20 fine-grained permissions like `CREATE_ROUTE`, `VIEW_ANALYTICS`).
- Services call `rbac.require_permission(role, Permission.X)` — never `if role == "admin"`. This means adding a new permission is one line in `rbac.py`, and every place that checks it stays correct.
- `OWNER` gets `frozenset(Permission)` — literally every permission that exists, automatically, without listing them. Add a new `Permission` and `OWNER` gets it for free; you only have to decide whether `ADMIN`/`MEMBER`/`VIEWER` should too.

**Data plane: API key scopes (`security/scopes.py`, `domain/enums/scope.py`)**
- An `APIKey` has a `scopes: list[str]`, e.g. `["gateway:read", "analytics:read"]`.
- A `Route` has a single `required_scope: str | None`.
- `has_scope()` checks membership with two expansion rules baked in: `admin` implies everything, `gateway:write` implies `gateway:read`. `None` required_scope means the route is public — no key needed at all for that specific check (the key still has to be *valid*, just doesn't need a specific scope).

**Do not mix these up.** A `Role` never appears in gateway code. An `APIKeyScope` never appears in control-plane permission checks. They protect different systems and answer different questions ("can this *person* configure the gateway" vs "can this *application* call this endpoint").

## 10. The gateway internals

Four pieces work together on every proxied request, each solving one specific problem:

**`PathTrie`** (`gateway/trie.py`) — in-memory routing, O(path length) not O(number of routes). Built once per project, cached in `GatewayState` until routes change. Longest-prefix wins: if both `/api` and `/api/v1` are registered routes, a request to `/api/v1/users` matches `/api/v1`. Segment-boundary aware by construction (splits on `/` before walking the trie), so `/api` correctly never matches `/apikeys`.

**Rate limiter** (`gateway/rate_limiter.py`) — sliding window via a Redis sorted set + a Lua script. Why a sorted set instead of the simpler `INCR` + `EXPIRE` pattern? Fixed windows have a boundary-burst bug: a client can send 2× the limit by hammering the last second of window N and the first second of window N+1. A sorted set keyed by timestamp gives a *true* "in the last 60 seconds" window. Why Lua? The read-check-write sequence (evict expired → count → maybe reject → record) has to be atomic, or two concurrent requests can both read "one under the limit" and both proceed — Redis runs the whole Lua script as one atomic unit, no separate locking needed.

**Circuit breaker** (`gateway/circuit_breaker.py`) — protects against a dead upstream causing every request to pile up waiting for a timeout. States: `CLOSED` (normal) → `OPEN` (5 failures within 60s trips it; every request gets an instant 503, *no upstream call is even attempted*) → after 30s, `HALF_OPEN` (exactly one request is let through as a "probe"; success closes the circuit, failure reopens it and resets the timer). The "exactly one probe" part is enforced with a Redis `SET NX` — whichever request claims that key first becomes the probe; everyone else gets rejected until the probe resolves.

**`GatewayState`** (`gateway/state.py`) — the process-level object holding the per-project trie cache and the *one* shared `httpx.AsyncClient` (created once in `main.py`'s lifespan, reused for every proxied request — this is why connection pooling actually works instead of opening a new TCP connection per request).

All four are designed the same way: **fail fast, never block on a dying dependency.** A rate-limited or circuit-broken request never touches the upstream at all.

## 11. The database layer

- **UUIDv7 primary keys** (`utils/uuidv7.py`), not UUID4, not auto-increment integers. UUIDv7 embeds a millisecond timestamp in the high bits, so new IDs sort after old ones. This matters because Postgres stores primary keys in a B-tree — random UUID4s scatter inserts across the whole tree causing page splits and index bloat; time-ordered IDs insert at the tail, same write performance as an auto-increment integer, but still globally unique (so the app can generate the ID before the INSERT, useful for e.g. returning the created ID in the same response without a round-trip).
- **Naming conventions on the `MetaData`** (`database/base.py`) — without these, Postgres auto-generates constraint names non-deterministically, and Alembic can't write a reliable `ALTER TABLE ... DROP CONSTRAINT` because it doesn't know the name. `NAMING_CONVENTION` makes every constraint name predictable: `fk_routes_upstream_id_upstreams`, `uq_project_org_slug`, etc.
- **Soft delete vs hard delete**: `HydraSoftDeleteBase` (adds `deleted_at`) for anything a user can "delete" through the API — deleting a project shouldn't orphan or cascade-destroy its historical API keys' audit trail. `HydraBase` (no `deleted_at`) for event records that should never be "un-happened" (`RequestLog`) and for `OrganizationMembership` (revocation is a hard delete by design — see its docstring).
- **`lazy="raise"` on every relationship**. This is deliberate, not an oversight: accessing `user.memberships` without having explicitly loaded it (via `selectinload(User.memberships)` in the query) raises immediately instead of silently firing a *synchronous* lazy-load query that would actually just crash with a much more confusing async-context error. If you see `InvalidRequestError` about lazy loading, the fix is to add `.options(selectinload(...))` to the query in the repository — not to change the model.
- **Repository pattern** (`repositories/base.py`): one class per model, all extending `BaseRepository[ModelT]`. It auto-applies the `deleted_at IS NULL` filter to every query for soft-delete models (`_base_select()`), so nobody has to remember to add that `WHERE` clause by hand. Repositories `flush()`, never `commit()` — see [§6](#6-request-lifecycle-1-a-control-plane-call) step 6–7 for why.
- **Two session factories** (`database/session.py`): `get_db()` (FastAPI dependency, one session per HTTP request, commits/rolls back automatically) and `get_standalone_session()` (for code that runs *outside* a request — currently only the gateway's background request-log writer, since by the time that background task runs, the original request's session is already closed).

## 12. Migrations with Alembic

`alembic/env.py` reads the DB URL from `core.config.Settings` (not from `alembic.ini` directly — so migrations always target whatever `.env` points the running app at) and imports the whole `models` package so `Base.metadata` sees every table.

```bash
alembic revision --autogenerate -m "add widgets table"   # generate from model diff
alembic upgrade head                                      # apply
alembic downgrade -1                                       # roll back one
alembic upgrade head --sql                                  # preview SQL, don't run it
```

**Always read the autogenerated file before running it.** Autogenerate is good at "you added a column" and bad at server defaults, index names, and enum changes — it'll often produce something *close* but subtly wrong.

Concrete example: `alembic/versions/2c7912e0dc45_initial_schema.py` originally had `server_default="'[]'"` on the two JSONB columns (`api_keys.scopes`, `routes.methods`). That looks reasonable but is wrong: when you pass a **plain Python string** as `server_default`, SQLAlchemy's compiler quotes it as a string literal for you (`render_default_string` wraps it in `'...'` and escapes internal quotes). Since the string already contained literal quotes (`'[]'`), it got quoted *again*, producing `DEFAULT '''[]'''` — which Postgres rejects outright for a JSONB column, so migrating from scratch failed 100% of the time. The fix is `server_default=text("'[]'")` — wrapping it in `sqlalchemy.text()` tells SQLAlchemy "this is already raw SQL, don't re-quote it." Same fix had to be applied in the ORM models (`models/route.py`, `models/api_key.py`) too, not just the migration — otherwise the next `alembic revision --autogenerate` would just regenerate the broken version by diffing against the (still wrong) model default. This is exactly the kind of bug autogenerate review would have caught before it shipped.

## 13. Redis usage inventory

Every key format lives in `cache/keys.py` — check there before inventing a new key naming scheme. Currently *actually used*:

| Key pattern | Used by | Purpose |
|---|---|---|
| `hydra:rl:apikey:{key_id}:{route_id}` | `gateway/rate_limiter.py` | Sliding-window rate limit sorted set |
| `hydra:cb:{upstream_id}:failures` / `:open_at` / `:probe` | `gateway/circuit_breaker.py` | Circuit breaker state |
| `hydra:revoked:{jti}` | `services/auth_service.py` | JWT access-token denylist |
| `hydra:auth:refresh:{jti}` | `services/auth_service.py` | Valid refresh token registry (rotation) |

Also defined in `cache/keys.py` but **not wired up to anything yet**: `route_cache_key()`, `api_key_cache_key()`, `permission_cache_key()`. These are reserved for a future optimization (caching API key lookups and RBAC checks in Redis instead of hitting Postgres each time) — don't go looking for the code that reads them, there isn't any yet. If you're the one who implements that milestone, these names are already chosen for you.

## 14. Observability: logging, correlation, metrics

**Middleware order matters and is documented in `main.py`** — because `add_middleware()` inserts each one at the *front* of the stack, they're registered in reverse of execution order:

```
CORS → LoggingMiddleware → CorrelationIDMiddleware → RequestIDMiddleware → [routes]
                                                        (outermost, runs first)
```

- **`RequestIDMiddleware`**: identifies *this specific* HTTP request. New UUID per request unless the caller supplies `X-Request-ID` (useful if a client wants to correlate its own logs with ours).
- **`CorrelationIDMiddleware`**: identifies a *logical chain* of requests that span multiple services (e.g., a browser request that triggers three backend calls) — propagated unchanged if the caller sends `X-Correlation-ID`, generated fresh otherwise. Different from request ID: one correlation ID can span many request IDs.
- **`LoggingMiddleware`**: binds both IDs (plus method/path/client IP) into `structlog.contextvars` at the start of the request and clears them at the end. Because `contextvars` is asyncio-`Task`-scoped, concurrent requests never leak context into each other's logs — and because every logger call anywhere in the codebase (service, repository, background task) picks up whatever's currently bound, you never have to manually thread a request ID through function signatures to get it into a log line three layers deep.

Structured logs are JSON in production, colorized console output in dev (`configure_logging(json_logs=...)` in `core/logging.py`). Every log call is `logger.info("event.name", key=value, ...)` — structured fields, not string interpolation, so a log aggregator can filter/query on them.

Prometheus + Grafana run via `docker-compose.yml` (ports 9090 / 3000, Grafana default login `admin`/`admin`) — `prometheus-fastapi-instrumentator` is in `pyproject.toml`'s dependencies for exposing a `/metrics` endpoint (check current `main.py` if you need to confirm it's wired in, since instrumentation setup is easy to miss when skimming).

## 15. Error handling

Every domain error is a subclass of `HydraError` (`core/exceptions.py`): `NotFoundError` (404), `ConflictError` (409), `UnauthorizedError` (401), `ForbiddenError` (403), `ValidationFailedError` (422), `RateLimitError` (429), `ServiceUnavailableError` (503). Each carries a `status_code`, an `error_code` string, and a default `message`.

```python
raise ForbiddenError("You do not have permission to delete projects")
```

A single `@app.exception_handler(HydraError)` in `core/exceptions.py` catches all of them and renders a consistent JSON shape:

```json
{"error": "forbidden", "message": "You do not have permission to delete projects", "details": {}}
```

Services and control-plane routers should **always** raise a `HydraError` subclass, never a raw `fastapi.HTTPException` — the one exception is the gateway proxy layer (`gateway/`, `api/gateway/router.py`), which raises `HTTPException` directly for upstream-facing status codes (502/504) because those map straight to HTTP semantics that don't need a custom error code/body shape. There's also a catch-all `Exception` handler that logs the full traceback and returns a generic 500 — so an unhandled bug never leaks a stack trace to a caller.

## 16. The Playground

`web/playground/` + `POST /api/v1/playground/execute` (`api/v1/playground/router.py`) — a small built-in Postman-like UI for firing test requests, and the *why* is worth understanding, not just the *what*.

**The problem it solves**: if the frontend tried to `fetch()` an arbitrary third-party or internal URL directly from the browser, it'd hit CORS almost immediately — most APIs don't send `Access-Control-Allow-Origin` headers for arbitrary origins, and you can't control that as the caller.

**The fix**: the browser only ever talks to Hydra's own backend. The backend (which has no CORS restrictions on itself, and controls what it forwards to) makes the actual outbound HTTP call using the *same shared `httpx.AsyncClient`* the gateway proxy uses, and returns status/headers/body/timing back to the browser as plain JSON.

**Security note, deliberately**: `/api/v1/playground/execute` requires a logged-in user (`get_current_user`), same as every other control-plane endpoint. This is a generic "make the server fetch any URL you ask it to" endpoint (a classic SSRF shape) — restricting it to authenticated users keeps it in the same trust boundary as the rest of the control plane, but be aware if you ever expose it more broadly (e.g., to lower-trust API keys) you'd need to think about blocking internal/private IP ranges first.

Frontend is deliberately dependency-free — plain HTML/CSS/JS, no build step, no npm install, served as static files via FastAPI's `StaticFiles` mount in `main.py`. Request history is `localStorage`, no backend persistence.

## 17. Testing strategy

```bash
pytest -m "not infra"   # unit tests — no external services, runs anywhere, fast
pytest -m infra          # integration tests — needs real Postgres + Redis
```

`tests/conftest.py` sets `DATABASE_URL`/`REDIS_URL`/`JWT_SECRET_KEY` env vars **before** importing any application module — this matters because `core/config.py`'s `get_settings()` is `@lru_cache`d and reads env vars the first time it's called. If the app were imported first, it'd cache whatever was in the real `.env` instead of test values.

The `client` fixture drives the *entire* ASGI app (middleware, lifespan, dependency injection, exception handlers included) via `httpx.AsyncClient` + `ASGITransport` — no real network socket, but a real FastAPI app underneath, so these aren't shallow mocked-out tests.

`@pytest.mark.infra` marks anything that needs a live DB/Redis connection (e.g. `test_ready_returns_200_when_infra_up` in `tests/integration/test_health.py`) — CI runs both marks separately (see `.github/workflows/ci.yml`) against real Postgres/Redis service containers, at `localhost:5432`/`hydra_test` DB. If you run `pytest -m infra` locally without a Postgres listening there with those exact credentials, it'll fail — that's expected, not a bug.

## 18. CI/CD

`.github/workflows/ci.yml`, two jobs on every push/PR to `main`/`develop`:

1. **Lint** — `ruff check .` and `ruff format --check .`.
2. **Test** — spins up real Postgres + Redis service containers, runs `pytest -m "not infra"` then `pytest -m infra` separately, with coverage reporting.

If either job fails, don't merge — and per `CONTRIBUTING.md`, run the same commands locally before pushing so you're not waiting on CI to tell you what `ruff` would've told you in 2 seconds.

## 19. Docker & deployment

**Dockerfile**: two-stage build. Stage 1 (`deps`) installs system build tools (gcc, libffi — needed to compile `asyncpg` and `argon2-cffi`) and pip dependencies into a throwaway image. Stage 2 (`runtime`) copies *only* the installed site-packages (not the compilers) into a clean `python:3.13-slim`, then copies source. This keeps the shipped image small and avoids leaving a C compiler in a production container. Runs as a non-root user (`hydra`), never root — standard container hardening.

**docker-compose.yml** services: `app` (the API, `--reload` for dev), `postgres`, `redis`, `prometheus` (port 9090), `grafana` (port 3000, `admin`/`admin`). `app` depends on Postgres/Redis reporting *healthy* (not just "started") via `depends_on: condition: service_healthy` — avoids the classic "app crashed on startup because Postgres was still initializing" race.

## 20. Walkthrough: setting up a working gateway from scratch

The full config chain, in the order you'd actually do it (also the order the FK constraints require):

1. **Register + log in** → `POST /api/v1/auth/register` → get a JWT pair.
2. **Create an organization** → `POST /api/v1/organizations` → you're automatically the `OWNER`.
3. **Create a project** → `POST /api/v1/organizations/{slug}/projects`.
4. **Create an upstream** → `POST /api/v1/projects/{project_id}/upstreams` — this is your real backend's `base_url`.
5. **Create a route** → `POST /api/v1/projects/{project_id}/routes` — a `path_prefix`, which `upstream_id` it points at, optionally a `required_scope` and `rate_limit_rpm`.
6. **Create an API key** → `POST /api/v1/projects/{project_id}/api-keys` with the scopes you want (`["gateway:read"]` etc.) — **the full key is returned exactly once in this response**, save it now, it's not recoverable later (only its hash is stored).
7. **Call through the gateway** → `curl -H "Authorization: Bearer hk_live_..." http://localhost:8000/gateway/<your path_prefix>/...` — this is the request that walks through all 12 steps in [§7](#7-request-lifecycle-2-a-gateway-proxy-call).

Every step after #3 requires the right RBAC permission on your org membership — if you get a 403 partway through, check [§9](#9-authorization-deep-dive-rbac-vs-scopes) for what your role actually grants.

## 21. Glossary

- **Control plane / data plane** — see [§2](#2-the-one-mental-model-that-matters-control-plane-vs-data-plane). The single most important distinction in this codebase.
- **Upstream** — a real backend service Hydra proxies to.
- **Route** — config mapping a path prefix to an upstream, plus auth/rate-limit rules.
- **Scope** — a string like `gateway:read` an API key carries; routes require a minimum scope.
- **Role** — `OWNER`/`ADMIN`/`MEMBER`/`VIEWER`, a human's access level within an org.
- **Permission** — a fine-grained action (`CREATE_ROUTE`, `VIEW_ANALYTICS`); roles are just named bundles of these.
- **Trie** — here, an in-memory prefix tree of route path segments, used so gateway routing doesn't need a DB query per request.
- **Circuit breaker** — a pattern that stops sending requests to a known-broken upstream for a cooldown period, instead of letting every request time out against it.
- **JTI** — "JWT ID," a unique identifier embedded in every token, used to revoke individual tokens without needing a secret rotation.
- **Soft delete** — marking `deleted_at` instead of removing the row, so foreign keys and audit history stay intact.
- **Correlation ID vs Request ID** — request ID = this one HTTP call; correlation ID = the whole logical chain of calls this one is part of.

## 22. Gotchas — things that will trip you up

- **`server_default` on JSONB columns must use `sa.text(...)`, not a plain string containing quotes.** See [§12](#12-migrations-with-alembic). If you ever see `DEFAULT '''[]'''` in generated SQL, this is why.
- **`models/api_key.py`'s docstring says Argon2; the real hashing is SHA-256** (`utils/api_key.py`). Trust the code. See [§8](#8-authentication-deep-dive).
- **`lazy="raise"` on ORM relationships is intentional.** If you hit an error accessing `.memberships` or similar, add `selectinload(...)` to the repository query — don't change the relationship's laziness.
- **Repositories never commit.** If you're writing new repository code and feel like you need a `session.commit()`, you're doing something the `get_db()`/`get_standalone_session()` dependency should be doing instead.
- **The gateway proxy layer is the one place `HTTPException` is OK to raise directly** instead of a `HydraError` subclass — everywhere else, use `HydraError`.
- **`cache/keys.py` has key formats for things that aren't implemented yet** (`route_cache_key`, `api_key_cache_key`, `permission_cache_key`). Don't assume they're wired up just because the key function exists.
- **This machine's Docker install may not have the `docker compose` plugin.** If `docker compose up` says "unknown command," fall back to running Postgres/Redis as separate `docker run` containers and pointing `.env` at them — see `README.md`'s "Running without Docker Compose" section.
- **`@pytest.mark.infra` tests expect Postgres on `localhost:5432` with a `hydra_test` database and specific credentials** (`tests/conftest.py`). If you already have a different Postgres instance using port 5432 for something else, these tests will fail for reasons that have nothing to do with your code change — don't chase that rabbit hole, just note the DB isn't reachable and move on, or spin up a dedicated container on an alternate port for your own manual testing.
