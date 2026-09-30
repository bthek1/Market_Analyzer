---
description: "Use when setting up the justfile task runner, installing just, running development servers, managing Docker services, running tests, or understanding available project commands."
applyTo: "justfile"
---

# Justfile Setup & Command Reference

## What is `just`?

`just` is a command runner (like `make`, but simpler).
All project tasks — starting servers, running tests, managing Docker, migrations — are defined
in the root `justfile`. Run `just --list` at any time to see all available commands.

---

## 1. Install `just`

### Linux (recommended — via package manager)

```bash
# Debian/Ubuntu
sudo apt install just

# Arch
sudo pacman -S just

# Via cargo (any distro)
cargo install just
```

### macOS

```bash
brew install just
```

### Pre-built binary (any platform)

```bash
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin
```

Verify:

```bash
just --version
```

---

## 2. Optional: Install `overmind` (process manager)

The `just dev` command uses `overmind` when available to run backend + frontend + Celery
concurrently in a single terminal with named output streams.
Without it, `just dev` falls back to plain background processes.

```bash
# macOS
brew install overmind

# Linux — download binary from https://github.com/DarthSim/overmind/releases
# or via mise/asdf
```

---

## 3. Environment Setup (required before first run)

### 3a. Copy env files

```bash
just env-init
```

This copies `.env.example → .env` for both `backend/` and `frontend/` (skips if already exists).

### 3b. Edit `.env` (repo root)

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | Yes | Any long random string for local dev |
| `DATABASE_URL` | Yes | `postgres://appuser:apppassword@localhost:5432/appdb` (local) |
| `CELERY_BROKER_URL` | Yes | `redis://localhost:6379/0` |
| `ANTHROPIC_API_KEY` | Only for RAG `/api/embeddings/rag/` | Leave blank to skip |
| `OLLAMA_BASE_URL` | For chat + embeddings | `http://localhost:11434` |
| `OLLAMA_MODEL` | Only for chat | e.g. `analysis-assistant` |
| `OLLAMA_EMBED_MODEL` | No | Defaults to `nomic-embed-text` (768-dim, served by Ollama) |
| `DJANGO_SETTINGS_MODULE` | No | Defaults to `core.settings.dev` |

### 3c. Edit `frontend/.env`

```
VITE_API_BASE_URL=http://localhost:8004
```

---

## 4. Install Dependencies

```bash
just install          # backend (uv) + frontend (npm) in one command
```

Or separately:

```bash
just be-install       # cd backend && uv sync --group dev
just fe-install       # cd frontend && npm install
```

---

## 5. Start the Database and Redis

The database and Redis run in Docker. Start them before the backend:

```bash
just db-up
```

This checks if `db` and `redis` containers are already running and starts them only if needed.
It waits 3 seconds for PostgreSQL to become ready before returning.

---

## 6. Run the Full Dev Stack

```bash
just dev
```

Starts (in order):
1. `db-up` — PostgreSQL + Redis containers
2. `be-dev` — Django dev server on `http://localhost:8004` (runs `makemigrations` + `migrate` first)
3. `fe-dev` — Vite dev server on `http://localhost:5174`
4. `be-celery` — Celery worker (broker: `redis://localhost:6379/0`)

Uses `overmind` if installed, otherwise runs all three as background processes.

---

## 7. Command Reference

### Docker

| Command | Description |
|---|---|
| `just up` | Start all Docker services (foreground) |
| `just up-d` | Start all Docker services (background) |
| `just down` | Stop all services |
| `just down-v` | Stop and remove volumes (**destroys DB data**) |
| `just build` | Rebuild all Docker images |
| `just build-svc backend` | Rebuild a single service image |
| `just logs` | Tail logs for all services |
| `just logs-svc backend` | Tail logs for a single service |

### Backend

| Command | Description |
|---|---|
| `just be-install` | Install Python deps via `uv sync --group dev` |
| `just be-dev` | Django dev server on `:8004` (runs migrations first) |
| `just be-migrate` | Apply pending migrations |
| `just be-makemigrations` | Generate migrations for all apps |
| `just be-makemigrations embeddings` | Generate migrations for a specific app |
| `just be-showmigrations` | Show migration status |
| `just be-shell` | Open Django interactive shell |
| `just be-superuser` | Recreate superuser from env vars |
| `just be-test` | Run full pytest suite |
| `just be-test-cov` | Run tests with coverage report |
| `just be-lint` | `ruff check .` |
| `just be-fmt` | `ruff format .` |
| `just be-collectstatic` | Collect static files |

### Celery

| Command | Description |
|---|---|
| `just be-celery` | Start Celery worker locally |
| `just be-celery-purge` | Purge all queued tasks |
| `just be-beat` | Start Celery Beat scheduler locally |
| `just be-flower` | Start Flower dashboard on `:5555` |
| `just celery-up` | Start `celery_worker` via Docker Compose |
| `just beat-up` | Start `celery_beat` via Docker Compose |
| `just flower-up` | Start `flower` via Docker Compose |

### Frontend

| Command | Description |
|---|---|
| `just fe-install` | Install npm deps |
| `just fe-dev` | Vite dev server on `:5174` |
| `just fe-build` | Production build |
| `just fe-preview` | Preview production build |
| `just fe-lint` | ESLint |
| `just fe-test` | Run Vitest suite |
| `just fe-test-ui` | Run Vitest with browser UI |

### Database

| Command | Description |
|---|---|
| `just db-up` | Start DB + Redis containers if not running |
| `just db-shell` | Open `psql` session via Docker |
| `just db-reset` | **Destructive**: drop volumes → restart → migrate |

### Utilities

| Command | Description |
|---|---|
| `just env` | Print current `.env` file contents |
| `just env-init` | Copy `.env.example` files (safe, skips existing) |
| `just clean` | Remove `__pycache__` and `.pyc` files |
| `just clean-all` | `clean` + remove `node_modules` and `dist` |

### AWS

| Command | Description |
|---|---|
| `just aws-login` | Log into AWS SSO (`ben-sso` profile) |
| `just aws-status` | Check current AWS SSO session |
| `just aws-console` | Open AWS Console in browser |

---

## 8. Key Justfile Settings

```just
set dotenv-load := false        # .env files are NOT auto-loaded by just
export VIRTUAL_ENV := ""        # Clears shell venv so uv uses the project's .venv
```

`dotenv-load` is disabled deliberately — Django loads the `.env` via `django-environ`.
If you need env vars in `just` recipes themselves, export them in your shell or pass them inline:

```bash
DJANGO_SETTINGS_MODULE=core.settings.prod just be-migrate
```

---

## 9. First-Run Checklist

```bash
# 1. Install just
just --version

# 2. Copy env files
just env-init

# 3. Edit .env (repo root) - set SECRET_KEY, DATABASE_URL, CELERY_BROKER_URL

# 4. Install all dependencies
just install

# 5. Start DB + Redis
just db-up

# 6. Start the full dev stack
just dev
```

After `just dev`, the app is available at:
- **Backend API:** http://localhost:8004
- **Frontend:** http://localhost:5174
- **Flower (Celery):** http://localhost:5555 (if started separately with `just be-flower`)
