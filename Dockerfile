# ── Stage 1: Dependency installer ─────────────────────────────────────────────
# We separate dependency installation from source copying so Docker can cache
# the pip layer. If only source code changes (not pyproject.toml), Docker reuses
# the cached pip layer and the rebuild takes seconds, not minutes.
FROM python:3.13-slim AS deps

WORKDIR /build

# System dependencies needed to compile asyncpg and argon2-cffi
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

# Install hatchling (build backend) then extract and install project dependencies.
# We do NOT install the project itself here — just its declared dependencies.
RUN pip install --no-cache-dir hatchling && \
    python -c "
import tomllib, subprocess, sys
with open('pyproject.toml', 'rb') as f:
    deps = tomllib.load(f)['project']['dependencies']
subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-cache-dir'] + deps, check=True)
"

# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

WORKDIR /app

# Copy installed packages from builder — keeps the final image lean
COPY --from=deps /usr/local/lib/python3.13/site-packages \
                 /usr/local/lib/python3.13/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application source
COPY . .

# Non-root user for security — never run production containers as root
RUN useradd --no-create-home --shell /bin/false hydra \
    && chown -R hydra:hydra /app
USER hydra

EXPOSE 8000

# Uvicorn flags:
#   --no-access-log  → we handle request logging in our own middleware
#   --workers 1      → single worker in container; scale via replicas
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--no-access-log", \
     "--workers", "1"]
