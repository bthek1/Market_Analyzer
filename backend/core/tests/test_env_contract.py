"""Guards on the single repo-root .env contract (issue #4).

Config lives in ONE file at the repo root. Nothing at runtime notices when
``.env.example`` drifts from what the settings actually read - a missing key
surfaces as a boot failure on a fresh clone, and a dead key surfaces as nothing
at all. These tests are the only thing keeping the two in step.
"""

import re
from pathlib import Path

from core.env import resolve_env_file

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
SETTINGS_DIR = REPO_ROOT / "backend" / "core" / "settings"

# Keys that no backend setting reads: they are consumed by docker compose, Vite or
# a management command. Listed explicitly so the dead-key guard below stays strict.
NON_SETTINGS_KEYS = {
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "REDIS_PORT",
    "VITE_API_BASE_URL",
    "DJANGO_SUPERUSER_USERNAME",
    "DJANGO_SUPERUSER_EMAIL",
    "DJANGO_SUPERUSER_PASSWORD",
    "DEBUG",
    # k6 (loadtest/k6/lib/config.js) and manage.py ensure_loadtest_user - issue #12
    "LOADTEST_EMAIL",
    "LOADTEST_PASSWORD",
    "LOADTEST_RATE",
}

_ASSIGNMENT = re.compile(r"^(?P<commented>#\s*)?(?P<key>[A-Z][A-Z0-9_]*)=")
_ENV_CALL = re.compile(r"\benv(?:\.\w+)?\(\s*\"(?P<key>[A-Z][A-Z0-9_]*)\"")


def _example_keys() -> tuple[set[str], set[str]]:
    """Return (set, documented) keys from .env.example.

    `set` are live assignments; `documented` also counts commented-out ones -
    a prod-only key belongs in the file as documentation, not as a live value.
    """
    live: set[str] = set()
    documented: set[str] = set()
    for line in ENV_EXAMPLE.read_text().splitlines():
        match = _ASSIGNMENT.match(line.strip())
        if not match:
            continue
        documented.add(match["key"])
        if not match["commented"]:
            live.add(match["key"])
    return live, documented


def _settings_env_keys() -> dict[str, bool]:
    """Map every env(...) key read by the settings modules to has_default."""
    keys: dict[str, bool] = {}
    for path in sorted(SETTINGS_DIR.glob("*.py")):
        text = path.read_text()
        for match in _ENV_CALL.finditer(text):
            call = _call_source(text, match.end())
            has_default = "default=" in call
            keys[match["key"]] = keys.get(match["key"], False) or has_default
    return keys


def _call_source(text: str, start: int) -> str:
    """Slice out the rest of a call's argument list, paren-balanced.

    Needed because some calls (BROWSER_ALLOWED_DOMAINS) span several lines, so a
    line-wise "is default= present" check would read the wrong call.
    """
    depth = 1
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[start:index]
    return text[start:]


def test_env_example_exists():
    assert ENV_EXAMPLE.is_file(), f"{ENV_EXAMPLE} is the committed config contract"


def test_required_settings_keys_are_documented():
    """A key the settings read with no default MUST appear in .env.example.

    Without this, a fresh clone boots into a django-environ ImproperlyConfigured
    and the only way to learn the key's name is to read the settings.
    """
    _, documented = _example_keys()
    required = {key for key, has_default in _settings_env_keys().items() if not has_default}
    missing = sorted(required - documented)
    assert not missing, f"required settings keys missing from .env.example: {missing}"


def test_example_has_no_dead_keys():
    """Every key in .env.example is read by something."""
    live, _ = _example_keys()
    known = set(_settings_env_keys()) | NON_SETTINGS_KEYS
    unknown = sorted(live - known)
    assert not unknown, (
        f"keys in .env.example that nothing reads: {unknown} - "
        "delete them, or add them to NON_SETTINGS_KEYS with a reason"
    )


def test_example_is_systemd_safe():
    """systemd's EnvironmentFile is the strictest consumer of this file.

    It has no shell: `export`, ${VAR} interpolation and command substitution are
    all taken literally, so a value that works for bash would silently reach
    Django as garbage on prod.
    """
    for number, raw in enumerate(ENV_EXAMPLE.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert not line.startswith("export "), f"line {number}: `export` is not systemd-safe"
        assert _ASSIGNMENT.match(line), f"line {number}: not a flat KEY=value line: {raw!r}"
        value = line.split("=", 1)[1]
        assert "${" not in value, f"line {number}: systemd does not interpolate ${{...}}"
        assert "$(" not in value, f"line {number}: systemd does not run command substitution"


class TestResolveEnvFile:
    def test_finds_repo_root_env(self, tmp_path):
        (tmp_path / ".env").write_text("SECRET_KEY=root\n")

        assert resolve_env_file(tmp_path) == tmp_path / ".env"

    def test_ignores_a_stale_backend_env(self, tmp_path):
        """The pre-consolidation location is no longer read at all."""
        backend = tmp_path / "backend"
        backend.mkdir()
        (backend / ".env").write_text("SECRET_KEY=legacy\n")

        assert resolve_env_file(tmp_path) is None

    def test_returns_none_when_absent(self, tmp_path):
        assert resolve_env_file(tmp_path) is None


# ---------------------------------------------------------------------------
# The other consumers of the same file: docker compose, the Ansible template
# that renders it on prod, the systemd units that load it, and deploy.sh.
# ---------------------------------------------------------------------------

COMPOSE = REPO_ROOT / "docker-compose.yml"
ANSIBLE_ROLES = REPO_ROOT / "infra" / "ansible" / "roles"
ENV_J2 = ANSIBLE_ROLES / "deploy" / "templates" / "env.j2"
DEPLOY_SH = REPO_ROOT / "infra" / "deploy.sh"
SYSTEMD_UNITS = sorted((ANSIBLE_ROLES / "services" / "templates").glob("stockmarket-*.service.j2"))

# ${VAR:-default} in compose, or ${VAR} with none.
_INTERPOLATION = re.compile(r"\$\{(?P<key>[A-Z][A-Z0-9_]*)(?::-(?P<default>[^}]*))?\}")


def _example_values() -> dict[str, str]:
    values = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        match = _ASSIGNMENT.match(line.strip())
        if match and not match["commented"]:
            values[match["key"]] = line.strip().split("=", 1)[1]
    return values


class TestDockerCompose:
    """Compose is the one consumer that needs no loader: it auto-loads the root
    .env for ${VAR} interpolation. What it does need is to stop hardcoding."""

    def test_no_hardcoded_credentials_or_ports(self):
        text = COMPOSE.read_text()
        offenders = [
            line.strip()
            for line in text.splitlines()
            if re.search(r"^\s*(POSTGRES_(DB|USER|PASSWORD)):", line) and "${" not in line
        ]
        assert not offenders, f"credentials hardcoded in docker-compose.yml: {offenders}"

        published = re.findall(r'^\s*-\s*"([^"]+):\d+"', text, flags=re.MULTILINE)
        assert published, "no published ports found - has the compose file changed shape?"
        for mapping in published:
            assert mapping.startswith("${"), f"host port {mapping!r} is hardcoded"

    def test_defaults_match_the_example(self):
        """A compose default that disagrees with .env.example is worse than none.

        Both files 'work', so the mismatch only shows up as a developer whose
        containers and whose DATABASE_URL point at different ports.
        """
        example = _example_values()
        for match in _INTERPOLATION.finditer(COMPOSE.read_text()):
            key, default = match["key"], match["default"]
            if default is None or key not in example:
                continue
            assert default == example[key], (
                f"docker-compose.yml defaults {key}={default!r} but "
                f".env.example says {example[key]!r}"
            )

    def test_every_interpolated_key_is_documented(self):
        example = _example_values()
        unknown = sorted(
            {m["key"] for m in _INTERPOLATION.finditer(COMPOSE.read_text())} - set(example)
        )
        assert not unknown, f"docker-compose.yml reads keys absent from .env.example: {unknown}"

    def test_database_url_agrees_with_the_container_ports(self):
        """DATABASE_URL and POSTGRES_PORT are two spellings of one port."""
        example = _example_values()
        db_port = re.search(r":(\d+)/", example["DATABASE_URL"])
        redis_port = re.search(r":(\d+)/", example["CELERY_BROKER_URL"])

        assert db_port and db_port.group(1) == example["POSTGRES_PORT"]
        assert redis_port and redis_port.group(1) == example["REDIS_PORT"]


class TestProdTemplate:
    """env.j2 renders the file systemd actually loads on prod, so it is bound by
    the same format rules as .env.example - and nothing else checks it."""

    def test_renders_flat_key_value_pairs(self):
        for number, raw in enumerate(ENV_J2.read_text().splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            assert _ASSIGNMENT.match(line), f"env.j2 line {number}: not KEY=value: {raw!r}"
            assert not line.startswith("export "), (
                f"env.j2 line {number}: `export` is not systemd-safe"
            )
            value = line.split("=", 1)[1]
            # Jinja braces are fine - they are substituted before systemd sees the
            # file. Shell constructs are not.
            assert "$(" not in value, f"env.j2 line {number}: command substitution"
            assert "${" not in value, f"env.j2 line {number}: systemd does not interpolate"

    def test_supplies_every_key_prod_cannot_default(self):
        """Prod runs core.settings.prod, which has no default for ALLOWED_HOSTS."""
        rendered_keys = {
            match["key"]
            for line in ENV_J2.read_text().splitlines()
            if (match := _ASSIGNMENT.match(line.strip())) and not match["commented"]
        }
        required = {key for key, has_default in _settings_env_keys().items() if not has_default}

        missing = sorted(required - rendered_keys)
        assert not missing, f"env.j2 does not render required keys: {missing}"

    def test_supplies_the_frontend_key_deploy_sh_needs(self):
        """deploy.sh fails the build without it, so its absence breaks deploys."""
        assert re.search(r"^VITE_API_BASE_URL=.+", ENV_J2.read_text(), flags=re.MULTILINE)


class TestSystemdUnits:
    def test_every_unit_loads_the_root_env_file(self):
        assert len(SYSTEMD_UNITS) == 4, f"expected 4 units, found {[u.name for u in SYSTEMD_UNITS]}"
        for unit in SYSTEMD_UNITS:
            assert "EnvironmentFile={{ app_dir }}/.env" in unit.read_text(), (
                f"{unit.name} does not load the repo-root .env"
            )


class TestDeployScript:
    def test_restarts_every_unit_that_runs_app_code(self):
        """CI/CD deploys app code; Ansible deploys units. A unit that runs app code but
        is not restarted by deploy.sh keeps serving the PREVIOUS release indefinitely,
        with nothing to indicate it. stockmarket-metrics was exactly that gap.

        The webhook unit is excluded: it runs the adnanh/webhook binary, not our code.
        """
        text = DEPLOY_SH.read_text()

        app_code_units = set()
        for unit in SYSTEMD_UNITS:
            body = unit.read_text()
            if "/backend/.venv/bin/" in body:
                app_code_units.add(unit.name.removesuffix(".service.j2"))

        missing = sorted(u for u in app_code_units if u not in text)
        assert not missing, (
            f"deploy.sh never restarts {missing}, so they run stale code after a deploy"
        )

    def test_does_not_hardcode_the_api_base_url(self):
        """It used to build with a literal http://192.168.2.200."""
        text = DEPLOY_SH.read_text()
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        assert not re.search(r"VITE_API_BASE_URL=https?://", code), (
            "deploy.sh hardcodes the API base URL again"
        )

    def test_reads_the_api_base_url_from_the_root_env_file(self):
        text = DEPLOY_SH.read_text()
        assert "ENV_FILE=/home/app/stock_market/.env" in text
        assert "VITE_API_BASE_URL" in text
        # An unset value silently builds a bundle that calls the empty string.
        assert "exit 1" in text, "deploy.sh no longer fails when the key is missing"
