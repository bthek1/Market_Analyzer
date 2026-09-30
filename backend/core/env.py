"""Locating the environment file.

Configuration lives in ONE file at the repository root (see ``.env.example``),
shared by the backend, the frontend (``VITE_*`` keys only), docker compose and
systemd's ``EnvironmentFile`` on prod.
"""

from pathlib import Path


def resolve_env_file(repo_root: Path) -> Path | None:
    """Return the repo-root .env, or None when there is not one.

    None is a normal state: on prod systemd injects the same file through
    ``EnvironmentFile``, and in tests the settings defaults are what we want.
    """
    candidate = repo_root / ".env"
    return candidate if candidate.is_file() else None
