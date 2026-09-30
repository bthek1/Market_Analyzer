"""Guards on the k6 load tests (issue #12).

A load test fails in quiet ways. An endpoint renamed in Django turns every request into a
404 that still "passes" a threshold looking only at latency. A script that starts calling
/api/llm/ measures the GPU instead of the app. A tag carrying a concrete URL creates one
Prometheus series per company. And a stress run pointed at prod by accident is itself an
incident. None of that errors in k6, so it is pinned here.

The static checks always run. The `k6 inspect` ones need the binary (`just lt-install`)
and skip without it - inspect evaluates the scripts' init code and options exactly as a
run would, without sending a request.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from django.urls import Resolver404, resolve

REPO_ROOT = Path(__file__).resolve().parents[3]
K6_DIR = REPO_ROOT / "loadtest" / "k6"
SCENARIOS = sorted((K6_DIR / "scenarios").glob("*.js"))
JUSTFILE = REPO_ROOT / "justfile"

PROFILES = ("smoke", "load", "stress", "spike", "soak")
OPEN_MODEL_PROFILES = ("load", "stress", "spike", "soak")

# Paths that must never be load targets (the issue's Non-goals). /api/health/ is allowed
# in exactly one module, which may only be called from setup().
FORBIDDEN = ("/api/llm/", "/sync/", "/yf/")
HEALTH = "/api/health/"
HEALTH_MODULE = K6_DIR / "lib" / "preflight.js"

# System tags that would put an unbounded value into a Prometheus label.
HIGH_CARDINALITY_TAGS = {"url", "vu", "iter"}

_API_LITERAL = re.compile(r"""['"`](/api/[^'"`?]*)""")


def js_files():
    return sorted(K6_DIR.rglob("*.js"))


def api_literals():
    """(file, path) for every /api/ path literal in the k6 sources."""
    return [
        (path, match.group(1))
        for path in js_files()
        for match in _API_LITERAL.finditer(path.read_text())
    ]


def balanced(text, open_index, opener="(", closer=")"):
    """The text between the bracket at open_index and its matching close."""
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == opener:
            depth += 1
        elif text[index] == closer:
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index]
    raise AssertionError("unbalanced brackets")


def function_body(text, name):
    match = re.search(rf"export function {name}\s*\([^)]*\)\s*{{", text)
    assert match, f"no `export function {name}`"
    return balanced(text, match.end() - 1, "{", "}")


def system_tags():
    text = (K6_DIR / "lib" / "config.js").read_text()
    match = re.search(r"export const SYSTEM_TAGS = \[([^\]]*)\]", text)
    assert match, "SYSTEM_TAGS allow-list not found in lib/config.js"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


# ---------------------------------------------------------------------------
# Static: the paths the scripts call
# ---------------------------------------------------------------------------


class TestEndpoints:
    def test_the_scripts_do_reference_endpoints(self):
        """Guards the guards below: an extraction that found nothing would pass them all."""
        paths = {p for _f, p in api_literals()}
        assert len(paths) >= 10, sorted(paths)
        assert SCENARIOS, "no scenario scripts"

    @pytest.mark.parametrize(
        "path",
        sorted({p for _f, p in api_literals()}),
    )
    def test_every_path_resolves_in_django(self, path):
        """A renamed endpoint must fail HERE, not as a run full of fast 404s."""
        concrete = path.replace("{id}", "1")
        try:
            resolve(concrete)
        except Resolver404:
            pytest.fail(f"{path} (as {concrete}) does not resolve - was the endpoint renamed?")

    def test_no_script_targets_a_non_goal_path(self):
        offenders = [
            f"{f.relative_to(REPO_ROOT)}: {p}"
            for f, p in api_literals()
            if any(bad in p for bad in FORBIDDEN)
        ]
        assert not offenders, f"LLM / sync / yfinance paths are out of scope: {offenders}"

    def test_health_appears_only_in_the_preflight_module(self):
        """It runs a Celery broadcast ping and an Ollama probe per call - under load it
        would load-test the broker and Ollama, not Django."""
        places = {f for f, p in api_literals() if p == HEALTH}
        assert places == {HEALTH_MODULE}, places

    @pytest.mark.parametrize("script", SCENARIOS, ids=lambda p: p.stem)
    def test_preflight_is_only_called_from_setup(self, script):
        text = script.read_text()
        calls = len(re.findall(r"\bpreflight\(", text))
        in_setup = len(re.findall(r"\bpreflight\(", function_body(text, "setup")))
        assert calls == in_setup, f"{script.name} calls preflight() outside setup()"

    def test_every_http_call_carries_a_name_tag(self):
        """Without a `name`, k6 falls back to the URL - and the URL is dropped from the
        system tags, so the request would be unattributable in every panel."""
        calls = 0
        for path in js_files():
            text = path.read_text()
            for match in re.finditer(r"\bhttp\.(get|post|put|patch|del|request|batch)\(", text):
                calls += 1
                call = balanced(text, match.end() - 1)
                named_inline = re.search(r"tags:\s*{\s*name:", call)
                named_var = re.search(r"\btags\b", call) and re.search(
                    r"const tags = {\s*name:", text
                )
                assert named_inline or named_var, f"{path.name}: http call without a name tag"
        assert calls >= 3, "found no http calls - has the library changed shape?"


# ---------------------------------------------------------------------------
# Static: cardinality and the prod guard
# ---------------------------------------------------------------------------


class TestCardinality:
    def test_high_cardinality_system_tags_are_excluded(self):
        tags = system_tags()
        assert "name" in tags, "the templated name tag is the replacement for url"
        assert not tags & HIGH_CARDINALITY_TAGS, tags & HIGH_CARDINALITY_TAGS

    @pytest.mark.parametrize("script", SCENARIOS, ids=lambda p: p.stem)
    def test_every_scenario_applies_the_allow_list(self, script):
        assert "systemTags: SYSTEM_TAGS" in script.read_text()

    def test_check_names_are_fixed_strings(self):
        """Each check name is a `check` label value; an interpolated one is unbounded."""
        text = (K6_DIR / "lib" / "checks.js").read_text()
        names = re.findall(r"^\s*(['\"`])(.+?)\1:\s*\(", text, flags=re.MULTILINE)
        assert names
        for quote, name in names:
            assert quote != "`" and "${" not in name, name


class TestProdGuardInTheJustfile:
    def test_the_lt_recipe_refuses_prod_without_confirmation(self):
        text = JUSTFILE.read_text()
        recipe = text[text.index("\nlt PROFILE") :]
        recipe = recipe[: recipe.index("\n[group(")]
        assert 'if [ "{{ TARGET }}" = "prod" ] && [ "${LOADTEST_ALLOW_PROD:-}" != "1" ]' in recipe
        assert "exit 2" in recipe

    def test_the_allow_variable_is_not_switched_on_in_the_example(self):
        example = (REPO_ROOT / ".env.example").read_text()
        assert not re.search(r"^LOADTEST_ALLOW_PROD=", example, flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# k6 inspect: the options as k6 itself evaluates them
# ---------------------------------------------------------------------------


def k6_binary():
    return shutil.which("k6") or next(
        (str(p) for p in [Path.home() / ".local" / "bin" / "k6"] if p.exists()), None
    )


needs_k6 = pytest.mark.skipif(k6_binary() is None, reason="k6 not installed (just lt-install)")


def inspect(script, **env):
    """(returncode, options-or-stderr). Env goes in via -e ONLY: `k6 inspect` does not
    read the system environment, and a developer's LOADTEST_ALLOW_PROD must not leak in
    either way."""
    args = [k6_binary(), "inspect"]
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    result = subprocess.run(
        [*args, str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "K6_NO_USAGE_REPORT": "true"},
        check=False,
    )
    if result.returncode != 0:
        return result.returncode, result.stderr
    return 0, json.loads(result.stdout)


def endpoint_paths():
    text = (K6_DIR / "lib" / "endpoints.js").read_text()
    return set(re.findall(r"path: '([^']+)'", text))


@needs_k6
@pytest.mark.parametrize("script", SCENARIOS, ids=lambda p: p.stem)
class TestInspectedOptions:
    @pytest.mark.parametrize("profile", PROFILES)
    def test_every_profile_parses(self, script, profile):
        code, options = inspect(script, LOADTEST_PROFILE=profile)
        assert code == 0, options
        assert list(options["scenarios"]) == [profile]

    @pytest.mark.parametrize("profile", PROFILES)
    def test_every_threshold_aborts_the_run(self, script, profile):
        """So a run against prod stops itself at the knee instead of relying on someone
        watching it."""
        _code, options = inspect(script, LOADTEST_PROFILE=profile)
        thresholds = options["thresholds"]
        assert {"http_req_failed", "checks"} <= set(thresholds)
        for metric, rules in thresholds.items():
            for rule in rules:
                assert rule["abortOnFail"] is True, f"{profile}: {metric} does not abort"

    def test_every_endpoint_has_a_latency_threshold(self, script):
        _code, options = inspect(script)
        budgets = {
            key.removeprefix("http_req_duration{name:").removesuffix("}")
            for key in options["thresholds"]
            if key.startswith("http_req_duration{name:")
        }
        assert budgets == endpoint_paths()

    @pytest.mark.parametrize("profile", OPEN_MODEL_PROFILES)
    def test_load_profiles_use_an_open_model(self, script, profile):
        """A closed model slows its own arrival rate as the server slows, hiding the very
        saturation these profiles exist to find."""
        _code, options = inspect(script, LOADTEST_PROFILE=profile)
        assert options["scenarios"][profile]["executor"] == "ramping-arrival-rate"

    def test_the_inspected_system_tags_exclude_url_vu_and_iter(self, script):
        _code, options = inspect(script)
        assert set(options["systemTags"]) == system_tags()
        assert "testid" in options["tags"]

    @pytest.mark.parametrize("profile", PROFILES)
    def test_prod_is_refused_without_confirmation(self, script, profile):
        """Every profile, and stress/spike/soak above all. Enforced in the script's init
        code, so `k6 run` by hand cannot skip the justfile's check."""
        code, stderr = inspect(script, LOADTEST_PROFILE=profile, LOADTEST_TARGET="prod")
        assert code != 0
        assert "LOADTEST_ALLOW_PROD" in stderr

    def test_a_prod_host_is_refused_whatever_the_target_says(self, script):
        code, _stderr = inspect(script, LOADTEST_BASE_URL="http://192.168.2.200")
        assert code != 0

    def test_prod_is_allowed_with_confirmation(self, script):
        code, options = inspect(
            script, LOADTEST_PROFILE="smoke", LOADTEST_TARGET="prod", LOADTEST_ALLOW_PROD="1"
        )
        assert code == 0, options


# ---------------------------------------------------------------------------
# Docs and code agree on the latency budgets
# ---------------------------------------------------------------------------

LOAD_TESTING_DOC = REPO_ROOT / "docs" / "project_docs" / "load-testing.md"


def code_budgets():
    text = (K6_DIR / "lib" / "profiles.js").read_text()
    block = re.search(r"export const BUDGETS_MS = {([^}]*)}", text)
    assert block, "BUDGETS_MS not found in lib/profiles.js"
    return {kind: int(ms) for kind, ms in re.findall(r"(\w+): (\d+)", block.group(1))}


def doc_budgets():
    """The `| kind ... | N ms |` rows of the doc's budget table."""
    rows = re.findall(r"^\| (\w+)[^|]*\| (\d+) ms \|$", LOAD_TESTING_DOC.read_text(), re.M)
    return {kind: int(ms) for kind, ms in rows}


class TestBudgetsAreDocumented:
    def test_every_endpoint_kind_has_a_budget(self):
        kinds = set(re.findall(r"kind: '(\w+)'", (K6_DIR / "lib" / "endpoints.js").read_text()))
        assert kinds == set(code_budgets())

    def test_the_doc_states_the_budgets_the_code_enforces(self):
        """Phase 4 replaces the placeholders with baseline-derived values; the doc is where
        the reasoning lives, so a number changed in only one place must fail."""
        assert doc_budgets() == code_budgets()
