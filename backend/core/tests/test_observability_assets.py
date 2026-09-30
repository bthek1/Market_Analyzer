"""Validate the observability stack's provisioned assets (issue #2).

These files are configuration, not code, and they fail SILENTLY in production: a
typo'd datasource uid renders as an empty panel, a broken alert rule is simply never
evaluated, and a contact point that does not exist means notifications go nowhere. None
of that surfaces until someone opens Grafana looking for a number that is not there.

So the invariants that span files - uid references, condition wiring, panel layout -
are asserted here instead.
"""

import io
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
OBS = REPO_ROOT / "infra" / "observability"
ANSIBLE = REPO_ROOT / "infra" / "ansible"
ALLOY_TEMPLATE = ANSIBLE / "roles" / "observability" / "templates" / "config.alloy.j2"
ALLOY_DEFAULTS = ANSIBLE / "roles" / "observability" / "defaults" / "main.yml"
SERVICES_TEMPLATES = ANSIBLE / "roles" / "services" / "templates"
PROVISIONING = OBS / "grafana" / "provisioning"
DASHBOARDS = OBS / "grafana" / "dashboards"

# Where the dashboard provider tells Grafana to look, inside the container.
CONTAINER_DASHBOARD_PATH = "/var/lib/grafana/dashboards"


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def datasource_uids():
    data = load_yaml(PROVISIONING / "datasources" / "lgtm.yml")
    return {ds["uid"] for ds in data["datasources"]}


def dashboard_files():
    return sorted(DASHBOARDS.glob("*.json"))


# ---------------------------------------------------------------------------
# Datasources
# ---------------------------------------------------------------------------


class TestDatasources:
    def test_expected_datasources_are_provisioned(self):
        assert datasource_uids() == {"prometheus", "loki", "tempo"}

    def test_exactly_one_default_datasource(self):
        data = load_yaml(PROVISIONING / "datasources" / "lgtm.yml")
        defaults = [ds for ds in data["datasources"] if ds.get("isDefault")]
        assert len(defaults) == 1

    def test_every_datasource_points_at_a_real_compose_service_and_port(self):
        """Each datasource url is http://<compose service>:<port the service listens on>.
        A drifting port here is invisible in the UI until someone opens a dashboard and
        finds it empty - and an empty panel reads identically to an idle system."""
        compose = yaml.safe_load((OBS / "docker-compose.yml").read_text())
        data = load_yaml(PROVISIONING / "datasources" / "lgtm.yml")

        for datasource in data["datasources"]:
            host, _, port = datasource["url"].removeprefix("http://").partition(":")

            assert host in compose["services"], f"{datasource['uid']} -> unknown service {host}"
            published = {p.split(":")[0] for p in compose["services"][host]["ports"]}
            assert port in published, (
                f"{datasource['uid']} points at :{port}, but {host} publishes {sorted(published)}"
            )

    def test_loki_derived_field_targets_a_real_datasource(self):
        """The request_id pivot is the whole substitute for distributed tracing; if its
        datasourceUid drifts, the link silently goes nowhere."""
        data = load_yaml(PROVISIONING / "datasources" / "lgtm.yml")
        loki = next(ds for ds in data["datasources"] if ds["uid"] == "loki")
        fields = loki["jsonData"]["derivedFields"]

        assert [f["name"] for f in fields] == ["request_id", "trace_id"]
        for field in fields:
            assert field["datasourceUid"] in datasource_uids()
            assert "${__value.raw}" in field["url"]


# ---------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------


class TestDashboards:
    def test_dashboards_exist(self):
        assert {p.stem for p in dashboard_files()} == {
            "host",
            "postgres",
            "redis",
            "django",
            "celery",
            "ingestion",
            "agents",
            "tracing",
            "loadtest",
        }

    def test_provider_path_matches_the_compose_mount(self):
        provider = load_yaml(PROVISIONING / "dashboards" / "stockmarket.yml")["providers"][0]
        compose = (OBS / "docker-compose.yml").read_text()

        assert provider["options"]["path"] == CONTAINER_DASHBOARD_PATH
        assert f"{CONTAINER_DASHBOARD_PATH}:ro" in compose

    @pytest.mark.parametrize("path", dashboard_files(), ids=lambda p: p.stem)
    def test_dashboard_is_valid_json_with_required_keys(self, path):
        board = json.loads(path.read_text())

        for key in ("uid", "title", "panels", "schemaVersion"):
            assert key in board, key
        assert board["panels"], "a dashboard with no panels provisions silently"

    def test_dashboard_uids_are_unique(self):
        uids = [json.loads(p.read_text())["uid"] for p in dashboard_files()]
        assert len(uids) == len(set(uids))

    @pytest.mark.parametrize("path", dashboard_files(), ids=lambda p: p.stem)
    def test_every_panel_targets_a_provisioned_datasource(self, path):
        board = json.loads(path.read_text())
        for panel in board["panels"]:
            assert panel["datasource"]["uid"] in datasource_uids(), panel["title"]

    @pytest.mark.parametrize("path", dashboard_files(), ids=lambda p: p.stem)
    def test_every_panel_has_a_non_empty_query(self, path):
        """PromQL panels carry `expr`; TraceQL panels carry `query`. Both must be
        non-empty - a panel with neither provisions silently and renders blank."""
        board = json.loads(path.read_text())
        for panel in board["panels"]:
            assert panel["targets"], panel["title"]
            for target in panel["targets"]:
                query = target.get("expr") or target.get("query") or ""
                assert query.strip(), panel["title"]

    @pytest.mark.parametrize(
        ("stem", "title"),
        [("django", "5xx rate"), ("celery", "Task failure rate")],
    )
    def test_error_rate_panels_read_zero_rather_than_no_data(self, stem, title):
        """A counter with no observations has NO series, and a ratio over an empty vector
        is empty - so a 0 % error rate rendered as "No data", which is what a broken
        query looks like. Every counter in these two ratios is wrapped in `or vector(0)`
        so a healthy system reads zero. Same class as the Redis alert's
        `redis_memory_max_bytes > 0` guard.

        Only the ERROR rates: for the Postgres cache-hit ratio, NaN while idle is the
        honest answer, because no reads happened for a ratio to describe.
        """
        board = json.loads(next(p for p in dashboard_files() if p.stem == stem).read_text())
        panel = next(p for p in board["panels"] if p["title"] == title)

        for target in panel["targets"]:
            counters = target["expr"].count("rate(")
            guards = target["expr"].count("or vector(0)")
            assert guards == counters, f"{title}: {counters} counter rates, {guards} guarded"

    @pytest.mark.parametrize("path", dashboard_files(), ids=lambda p: p.stem)
    def test_panel_ids_are_unique(self, path):
        ids = [p["id"] for p in json.loads(path.read_text())["panels"]]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("path", dashboard_files(), ids=lambda p: p.stem)
    def test_no_panel_uses_a_second_y_axis(self, path):
        """Dual-axis plots invent a correlation out of an arbitrary alignment of two
        scales. Grafana spells one as an override placing a field's axis on the right,
        so that is what this looks for."""
        board = json.loads(path.read_text())
        for panel in board["panels"]:
            for override in panel["fieldConfig"].get("overrides", []):
                for prop in override.get("properties", []):
                    assert (
                        prop.get("id") != "custom.axisPlacement" or prop.get("value") != "right"
                    ), f"{path.stem}/{panel['title']} has a right-hand y-axis"

    @pytest.mark.parametrize("path", dashboard_files(), ids=lambda p: p.stem)
    def test_panels_do_not_overlap(self, path):
        """Overlapping gridPos makes Grafana reflow the dashboard into an order nobody
        chose, which is how a carefully laid out board turns to soup on first load."""
        board = json.loads(path.read_text())
        occupied = set()
        for panel in board["panels"]:
            pos = panel["gridPos"]
            cells = {
                (x, y)
                for x in range(pos["x"], pos["x"] + pos["w"])
                for y in range(pos["y"], pos["y"] + pos["h"])
            }
            assert not (cells & occupied), f"{panel['title']} overlaps another panel"
            assert pos["x"] + pos["w"] <= 24, f"{panel['title']} exceeds the 24-col grid"
            occupied |= cells

    @pytest.mark.parametrize("path", dashboard_files(), ids=lambda p: p.stem)
    def test_multi_series_panels_show_a_legend(self, path):
        """Identity must never be carried by colour alone."""
        board = json.loads(path.read_text())
        for panel in board["panels"]:
            if panel["type"] != "timeseries":
                continue
            targets = panel["targets"]
            multi = len(targets) > 1 or any("{{" in t.get("legendFormat", "") for t in targets)
            if multi:
                assert panel["options"]["legend"]["showLegend"], panel["title"]


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------


class TestAlerting:
    def rules(self):
        data = load_yaml(PROVISIONING / "alerting" / "rules.yml")
        return [r for group in data["groups"] for r in group["rules"]]

    def test_rules_exist_and_have_unique_uids(self):
        uids = [r["uid"] for r in self.rules()]
        assert len(uids) >= 12
        assert len(uids) == len(set(uids))

    def test_every_rule_condition_points_at_one_of_its_own_nodes(self):
        """A condition naming a refId that is not in `data` is accepted by provisioning
        and then never fires - the worst possible failure mode for an alert."""
        for rule in self.rules():
            refs = [node["refId"] for node in rule["data"]]
            assert rule["condition"] in refs, rule["uid"]

    def test_every_rule_query_uses_a_provisioned_or_expression_datasource(self):
        valid = datasource_uids() | {"__expr__"}
        for rule in self.rules():
            for node in rule["data"]:
                assert node["datasourceUid"] in valid, rule["uid"]

    def test_every_rule_has_a_summary_and_a_severity(self):
        for rule in self.rules():
            assert rule["annotations"]["summary"].strip(), rule["uid"]
            assert rule["labels"]["severity"] in {"warning", "critical"}, rule["uid"]

    def test_no_rule_is_paused(self):
        for rule in self.rules():
            assert rule["isPaused"] is False, rule["uid"]

    def test_redis_memory_rule_guards_against_unset_maxmemory(self):
        """Ubuntu ships redis with no maxmemory, so redis_memory_max_bytes is 0 and the
        bare ratio is +Inf - which is > 90 and would fire this alert permanently from
        the moment the exporter starts. The guard is the rule."""
        rule = next(r for r in self.rules() if r["uid"] == "sm-redis-memory")
        expr = next(n for n in rule["data"] if n["refId"] == "A")["model"]["expr"]

        assert "redis_memory_max_bytes > 0" in expr
        # And NoData must be benign, because the guard returns an empty vector.
        assert rule["noDataState"] == "OK"

    def test_host_down_rule_alerts_on_no_data(self):
        """Collection is push-based: a dead host stops sending rather than reporting 0,
        so NoData is the signal, not an absence of one."""
        rule = next(r for r in self.rules() if r["uid"] == "sm-host-not-reporting")
        assert rule["noDataState"] == "Alerting"

    def test_notification_policy_routes_to_a_defined_contact_point(self):
        policy = load_yaml(PROVISIONING / "alerting" / "policies.yml")["policies"][0]
        contacts = load_yaml(PROVISIONING / "alerting" / "contactpoints.yml")["contactPoints"]

        assert policy["receiver"] in {c["name"] for c in contacts}

    def test_contact_point_has_a_destination(self):
        contacts = load_yaml(PROVISIONING / "alerting" / "contactpoints.yml")["contactPoints"]
        for contact in contacts:
            for receiver in contact["receivers"]:
                assert receiver["settings"].get("addresses", "").strip(), contact["name"]

    def test_ratio_alerts_guard_their_denominator(self):
        """A rate ratio with no traffic is 0/0 = NaN, and a NaN threshold comparison is
        undefined rather than "do not alert". Every percentage rule floors its
        denominator so a silent app reads 0%, not NaN."""
        for uid in ("sm-http-5xx", "sm-celery-failures"):
            rule = next(r for r in self.rules() if r["uid"] == uid)
            expr = next(n for n in rule["data"] if n["refId"] == "A")["model"]["expr"]

            assert "clamp_min(" in expr, uid
            # And an idle period must not alert.
            assert rule["noDataState"] == "OK", uid

    def test_backlog_alert_tolerates_bursts(self):
        """bootstrap_tick and the sync dispatchers enqueue in bursts, so a short spike is
        normal. Only a backlog that does not drain is worth waking up for."""
        rule = next(r for r in self.rules() if r["uid"] == "sm-celery-backlog")

        assert rule["for"] == "15m"
        # Redis deletes an empty list, so an idle broker exports no series at all.
        assert rule["noDataState"] == "OK"

    def test_the_only_loki_backed_rule_is_the_deploy_one(self):
        """Everything else is a metric. The deploy check has to be log-based: deploy.sh
        emits no metrics, and the deploy workflow reports success as soon as the webhook
        is accepted - long before the script finishes."""
        loki_rules = {
            r["uid"] for r in self.rules() if any(n["datasourceUid"] == "loki" for n in r["data"])
        }

        assert loki_rules == {"sm-deploy-failed"}

    def test_kg_cap_alert_reads_the_cap_from_a_series(self):
        """Hard-coding KG_MAX_NODES in the expression would silently invalidate the alert
        the moment the setting changed."""
        rule = next(r for r in self.rules() if r["uid"] == "sm-kg-near-cap")
        expr = next(n for n in rule["data"] if n["refId"] == "A")["model"]["expr"]

        assert "stockmarket_kg_max_concepts" in expr
        assert "clamp_min(" in expr

    def test_ollama_alert_treats_missing_data_as_a_problem(self):
        """NoData here means the exporter process itself is down, which is at least as
        bad as Ollama being down."""
        rule = next(r for r in self.rules() if r["uid"] == "sm-ollama-down")
        assert rule["noDataState"] == "Alerting"

    def test_grafana_smtp_is_configured(self):
        """An email contact point with no SMTP host silently drops every notification."""
        compose = (OBS / "docker-compose.yml").read_text()
        assert "GF_SMTP_ENABLED" in compose
        assert "GF_SMTP_HOST" in compose


# ---------------------------------------------------------------------------
# Collection config: the Alloy agent and what it is pointed at
#
# Everything here is a SILENT failure mode. A renamed systemd unit, a changed Celery
# queue or a drifting Prometheus job label does not raise anything - the logs just stop
# arriving, the queue-depth panel just reads zero, and the alert just never fires.
# ---------------------------------------------------------------------------


def alloy_defaults():
    return yaml.safe_load(ALLOY_DEFAULTS.read_text())


def alloy_template_without_comments():
    """The Alloy config with // comment lines removed."""
    return "\n".join(
        line
        for line in ALLOY_TEMPLATE.read_text().splitlines()
        if not line.lstrip().startswith("//")
    )


def alloy_job_names():
    """Every job label the agent attaches, across BOTH signals.

    Three sources, and they are not interchangeable: exporter blocks hard-code a
    Prometheus `job_name`; application scrapes render one per entry of
    `alloy_app_scrape_targets`; and Loki file sources carry their own `job` label from
    `alloy_log_files`, plus the constant the journal source sets. A rule selecting
    {job="deploy"} is querying the Loki namespace, not the Prometheus one.
    """
    # Comments are stripped first: they legitimately quote label values (e.g. explaining
    # that Alloy emits job="integrations/unix"), and scanning them would report labels the
    # agent never actually sets.
    config = alloy_template_without_comments()
    literal = {name for name in re.findall(r'job_name\s*=\s*"([^"]+)"', config) if "{{" not in name}
    site = yaml.safe_load((ANSIBLE / "site.yml").read_text())
    roles = [role for play in site for role in play.get("roles", []) if isinstance(role, dict)]
    scrape_jobs = {
        scrape["job"] for role in roles for scrape in role.get("alloy_app_scrape_targets", [])
    }
    log_jobs = {entry["job"] for role in roles for entry in role.get("alloy_log_files", [])}
    # Set as a constant on loki.source.journal rather than through a variable.
    journal_jobs = {name for name in re.findall(r'job\s*=\s*"([^"]+)"', config) if "{{" not in name}
    return literal | scrape_jobs | log_jobs | journal_jobs


def referenced_job_labels():
    """Every job="..." selector used by a dashboard query or an alert rule."""
    text = "\n".join(p.read_text() for p in dashboard_files())
    text += (PROVISIONING / "alerting" / "rules.yml").read_text()
    return set(re.findall(r'job=\\?"([^"\\]+)\\?"', text))


class TestCollectionConfig:
    def test_journal_units_match_the_units_the_services_role_deploys(self):
        """If a unit is renamed in the services role and not here, that service's logs
        silently stop reaching Loki - nothing errors, the stream just goes quiet."""
        deployed = {
            path.name.removesuffix(".j2")
            for path in SERVICES_TEMPLATES.glob("stockmarket-*.service.j2")
        }
        configured = set(alloy_defaults()["alloy_journal_units"])

        assert configured == deployed, (
            f"Alloy journal units {sorted(configured)} do not match the deployed units "
            f"{sorted(deployed)}"
        )

    def test_redis_check_keys_include_celerys_actual_queue(self):
        """Celery's default queue is literally named "celery" unless task_default_queue
        or task_routes say otherwise. Nothing here configures either, and the prod
        worker unit passes no -Q, so "celery" is the live queue and the only Redis list
        whose length is the real backlog. Watching the wrong key reports 0 forever.

        This test fails deliberately if routing is ever introduced, because the exporter
        config then has to grow to match."""
        from django.conf import settings

        assert not hasattr(settings, "CELERY_TASK_DEFAULT_QUEUE"), (
            "a custom default queue was configured - add it to alloy_redis_check_keys"
        )
        assert not hasattr(settings, "CELERY_TASK_ROUTES"), (
            "task routing was introduced - add the new queues to alloy_redis_check_keys"
        )
        assert "celery" in alloy_defaults()["alloy_redis_check_keys"]

    def test_every_job_label_used_downstream_is_one_the_agent_sets(self):
        """A dashboard or alert selecting job="node" when the agent labels it "unix"
        produces an empty panel and an alert that can never fire."""
        unknown = referenced_job_labels() - alloy_job_names()

        assert not unknown, (
            f"job label(s) {sorted(unknown)} are queried but never set by Alloy; "
            f"the agent sets {sorted(alloy_job_names())}"
        )

    def test_exporter_scrapes_force_their_job_label(self):
        """Alloy's prometheus.exporter.* components attach their own job label
        ("integrations/<name>"), and a target's existing job label BEATS
        prometheus.scrape's job_name - so job_name alone does not rename it. Observed in
        production as up{job="integrations/unix"} while the host-down alert selected
        job="unix", matched nothing, and would have fired permanently.

        Each exporter must therefore be routed through a discovery.relabel that sets the
        job label explicitly, and the scrape must consume that relabel's output.
        """
        template = ALLOY_TEMPLATE.read_text()

        for name in ("unix", "redis", "postgres"):
            block = re.search(rf'discovery\.relabel "{name}" \{{(.*?)\n\}}', template, re.S)
            assert block, f"{name} exporter is not routed through discovery.relabel"

            body = block.group(1)
            assert 'target_label = "job"' in body, f"{name} relabel does not set the job label"
            assert f'replacement  = "{name}"' in body, f"{name} relabel does not force job={name}"
            assert f"discovery.relabel.{name}.output" in template, (
                f"the {name} scrape does not consume its relabel output"
            )

    def test_agent_sets_the_expected_jobs(self):
        assert alloy_job_names() == {
            # Prometheus scrape jobs
            "unix",
            "redis",
            "postgres",
            "django",
            "celery",
            # Loki job labels
            "systemd-journal",
            "nginx",
            "deploy",
        }

    def test_host_down_alert_counts_every_host_in_the_inventory(self):
        """The rule hard-codes an expected host count because push-based collection
        cannot detect a host that simply stopped sending. Adding a host to the inventory
        without updating the threshold silently disables the alert."""
        inventory = yaml.safe_load((ANSIBLE / "inventory" / "hosts.yml").read_text())
        hosts = inventory["all"]["children"]["prod"]["hosts"]

        rules = yaml.safe_load((PROVISIONING / "alerting" / "rules.yml").read_text())
        rule = next(
            r
            for group in rules["groups"]
            for r in group["rules"]
            if r["uid"] == "sm-host-not-reporting"
        )
        threshold = next(n for n in rule["data"] if n["refId"] == rule["condition"])["model"][
            "conditions"
        ][0]["evaluator"]["params"][0]

        assert threshold == len(hosts), (
            f"the alert expects {threshold} hosts but the inventory has {len(hosts)}"
        )

    def test_observability_roles_are_gated_in_every_play(self):
        """The whole stack is opt-in. An ungated role reference would install Alloy on
        the next unrelated ansible-playbook run."""
        site = yaml.safe_load((ANSIBLE / "site.yml").read_text())

        found = 0
        for play in site:
            for role in play.get("roles", []):
                if isinstance(role, dict) and role.get("role") in {
                    "observability",
                    "monitoring",
                }:
                    found += 1
                    assert "observability_enabled" in role.get("when", ""), (
                        f"{role['role']} in play {play['hosts']} is not gated"
                    )
        assert found == 4, f"expected 4 gated role references, found {found}"

    def test_postgres_dsn_is_not_inlined_in_the_alloy_template(self):
        """The DSN carries the exporter password. It must be read from a 0640 file, not
        written into config.alloy - which ansible --diff would print."""
        template = ALLOY_TEMPLATE.read_text()

        assert "alloy_postgres_dsn_file" in template
        assert "is_secret = true" in template
        assert "{{ alloy_postgres_dsn }}" not in template


# ---------------------------------------------------------------------------
# Dashboard queries vs the metrics we actually export
# ---------------------------------------------------------------------------

# Only the families this codebase defines. redis_*, pg_* and node_* come from Alloy's
# bundled exporters, which are not importable here, so they cannot be checked this way.
OWNED_PREFIXES = ("django_", "celery_", "stockmarket_")

# prometheus_client suffixes a family name per sample type, and Counter also STRIPS a
# trailing "_total" from the name it is given - so Counter("django_db_errors_total")
# registers the family "django_db_errors" and emits the sample "django_db_errors_total".
# Comparing raw names without accounting for that produces false failures.
SAMPLE_SUFFIXES = ("", "_total", "_bucket", "_sum", "_count", "_created")


def exported_metric_names():
    """Every name a dashboard could legitimately query, from the live registry.

    The domain gauges are only emitted from a DomainCollector instance, so it is
    registered on a throwaway registry here rather than the global one - registering it
    globally would leak a DB-querying collector into every other test's scrape.
    """
    # Building the WSGI handler instantiates the middleware chain, which is what
    # registers django-prometheus' HTTP families - importing the module is not enough.
    from django.core.handlers.wsgi import WSGIHandler

    WSGIHandler()
    # The DB families live behind the engine wrapper, which core/settings/test.py does
    # not use (it runs on SQLite), so this import is what registers them.
    import django_prometheus.db.metrics  # noqa: F401
    from prometheus_client import REGISTRY, CollectorRegistry

    import apps.tasks.metrics  # noqa: F401
    from apps.tasks.collectors import DomainCollector

    scratch = CollectorRegistry()
    scratch.register(DomainCollector())

    names = set()
    for family in list(REGISTRY.collect()) + list(scratch.collect()):
        for suffix in SAMPLE_SUFFIXES:
            names.add(family.name + suffix)
    return names


def owned_names_in(exprs):
    return {
        name
        for name in re.findall(r"\b[a-z][a-z0-9_]*\b", " ".join(exprs))
        if name.startswith(OWNED_PREFIXES)
    }


def queried_metric_names(path):
    """Owned metric names across a dashboard's PromQL targets.

    TraceQL targets are skipped: they have no `expr`, they query Tempo rather than
    Prometheus, and there is no metric name in them to own.
    """
    board = json.loads(path.read_text())
    return owned_names_in(
        t["expr"] for panel in board["panels"] for t in panel["targets"] if "expr" in t
    )


def alert_rule_exprs():
    """(uid, expr) for every Prometheus query node in the provisioned alert rules."""
    data = load_yaml(PROVISIONING / "alerting" / "rules.yml")
    return [
        (rule["uid"], node["model"]["expr"])
        for group in data["groups"]
        for rule in group["rules"]
        for node in rule["data"]
        if node["datasourceUid"] != "__expr__" and "expr" in node["model"]
    ]


@pytest.mark.django_db
class TestDashboardMetricNames:
    """A metric name typo is invisible: the panel renders, the query returns nothing, and
    the dashboard reads zero. Nothing errors, so only a test catches it.

    Needs a database: the domain gauges come from a collector that queries at collect()
    time, and its per-section guard would otherwise swallow the DB error and report no
    families at all - making this test pass vacuously.
    """

    @pytest.fixture(autouse=True)
    def _no_network(self):
        """The Ollama probe must not reach out from a unit test."""
        with patch("httpx.Client", side_effect=RuntimeError("no network in tests")):
            yield

    @pytest.mark.parametrize("path", dashboard_files(), ids=lambda p: p.stem)
    def test_every_owned_metric_queried_actually_exists(self, path):
        unknown = queried_metric_names(path) - exported_metric_names()

        assert not unknown, f"{path.stem} queries metric(s) that nothing exports: {sorted(unknown)}"

    def test_the_django_and_celery_dashboards_do_query_owned_metrics(self):
        """Guards the guard: if the extraction regex broke, the test above would pass
        vacuously on an empty set."""
        for stem in ("django", "celery"):
            path = next(p for p in dashboard_files() if p.stem == stem)
            assert queried_metric_names(path), f"{stem} extracted no owned metric names"

    def test_every_owned_metric_an_alert_queries_actually_exists(self):
        """Worse than the dashboard case: a panel querying a misspelled metric at least
        reads as empty to anyone who opens it, whereas an alert rule on one evaluates
        cleanly, reports `health=ok`, and stays inactive forever - it looks exactly like
        a system that is healthy."""
        exported = exported_metric_names()

        for uid, expr in alert_rule_exprs():
            unknown = owned_names_in([expr]) - exported
            assert not unknown, f"alert {uid} queries metric(s) nothing exports: {sorted(unknown)}"

    def test_the_alert_rules_do_query_owned_metrics(self):
        """Guards the guard, as above - the domain rules are all built on our own
        gauges, so an empty extraction means the walk broke."""
        assert owned_names_in(expr for _uid, expr in alert_rule_exprs())


# ---------------------------------------------------------------------------
# The live-stack verifier (infra/observability/verify_dashboards.py)
# ---------------------------------------------------------------------------


def load_verifier():
    """Import the verifier by path - infra/ is not a package on sys.path."""
    import importlib.util

    path = OBS / "verify_dashboards.py"
    spec = importlib.util.spec_from_file_location("verify_dashboards", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDashboardVerifier:
    """The metric names the offline test cannot reach (node/redis/postgres exporters) are
    checked by asking the live Prometheus instead - `just obs-verify`. That script only
    means something if it actually finds every panel, so its extraction is pinned here.
    """

    def test_it_extracts_every_target_from_every_dashboard(self):
        verifier = load_verifier()

        for path in dashboard_files():
            targets = verifier.panel_targets(path)
            board = json.loads(path.read_text())
            # panel_targets extracts PROMQL, so TraceQL targets are correctly absent -
            # obs-verify runs these against Prometheus and could not parse a TraceQL one.
            expected = sum(
                1
                for panel in board["panels"]
                for target in panel.get("targets") or []
                if "expr" in target
            )

            assert len(targets) == expected, f"{path.stem}: found {len(targets)} of {expected}"
            assert all(title and expr for title, expr in targets)

    def test_it_skips_traceql_targets_rather_than_choking_on_them(self):
        """Guards the exclusion above from becoming a silent free pass: the tracing
        dashboard really does contain a TraceQL panel, and it must be skipped while its
        PromQL siblings on the same dashboard are still collected."""
        verifier = load_verifier()
        path = next(p for p in dashboard_files() if p.stem == "tracing")
        board = json.loads(path.read_text())

        traceql = [
            t
            for panel in board["panels"]
            for t in panel.get("targets") or []
            if "query" in t and "expr" not in t
        ]
        assert traceql, "the tracing dashboard no longer exercises the TraceQL path"

        collected = verifier.panel_targets(path)
        assert collected, "PromQL targets on the same dashboard were dropped too"
        assert all("{name=" not in expr for _title, expr in collected)

    def test_it_substitutes_every_grafana_interval_token(self):
        """A `$__rate_interval` left in the query is a 400 from Prometheus, which the
        script would report as an error on every rate panel - drowning real findings."""
        verifier = load_verifier()

        for path in dashboard_files():
            for _title, expr in verifier.panel_targets(path):
                assert "$" not in verifier.substitute(expr), expr

    def test_an_idle_panel_passes_when_its_metrics_all_exist(self):
        """An empty panel whose metrics all have series is an idle window, not a defect -
        which is the common case on a quiet prod, and failing on it would make the script
        unusable for no signal."""
        verifier = load_verifier()

        with patch.object(verifier, "missing_metrics", return_value=[]):
            with patch.object(verifier, "query", return_value=("empty", "no series")):
                assert verifier.main(["--quiet"]) == 0

    def test_a_metric_with_no_series_anywhere_fails_the_run(self):
        """The whole point. `pg_stat_database_rollback` does not exist, so nothing it is
        queried by can ever draw - and that must be an error, not a line nobody reads."""
        verifier = load_verifier()

        with patch.object(verifier, "missing_metrics", return_value=["nonexistent_metric"]):
            with patch.object(verifier, "query", return_value=("empty", "no series")):
                assert verifier.main(["--quiet"]) == 1

    def test_a_declared_missing_metric_does_not_fail_the_run(self):
        verifier = load_verifier()
        declared = next(iter(verifier.EXPECTED_MISSING))

        with patch.object(verifier, "missing_metrics", return_value=[declared]):
            with patch.object(verifier, "query", return_value=("empty", "no series")):
                assert verifier.main(["--quiet"]) == 0

    def test_a_query_error_fails_the_run(self):
        """An unreachable Prometheus must not read as a clean stack."""
        verifier = load_verifier()

        with patch.object(verifier, "query", return_value=("error", "connection refused")):
            assert verifier.main(["--quiet"]) == 1

    def test_it_extracts_metric_names_without_labels_or_functions(self):
        """`missing_metrics` queries each name on its own, so a grouping label or an
        aggregation operator leaking through would be reported as a nonexistent metric -
        the script would fail every panel it cannot parse, which reads as a broken stack.
        """
        verifier = load_verifier()

        assert verifier.metric_names(
            'sum by (method) (rate(django_http_requests_total_by_method_total{status=~"5.."}[5m]))'
        ) == {"django_http_requests_total_by_method_total"}
        assert verifier.metric_names(
            "topk(5, histogram_quantile(0.95, sum by (le, view) "
            "(rate(django_http_requests_latency_seconds_by_view_method_bucket[5m]))))"
        ) == {"django_http_requests_latency_seconds_by_view_method_bucket"}
        assert verifier.metric_names(
            "(sum(rate(a_total[5m])) or vector(0)) / clamp_min(sum(rate(b_total[5m])), 0.001)"
        ) == {"a_total", "b_total"}

    def test_every_dashboard_expression_yields_at_least_one_metric_name(self):
        """Guards the guard: a name-extraction that quietly returned nothing would make
        every empty panel look explainable."""
        verifier = load_verifier()

        for path in dashboard_files():
            for title, expr in verifier.panel_targets(path):
                assert verifier.metric_names(expr), f"{path.stem}/{title}: {expr}"

    def test_it_classifies_a_prometheus_response_by_what_it_means(self):
        """Empty and all-NaN are treated differently, so the split has to be right: no
        series at all means the name is probably wrong, whereas NaN values mean the
        series exists and is idle."""
        verifier = load_verifier()
        responses = {
            "empty": {"status": "success", "data": {"result": []}},
            "nan": {"status": "success", "data": {"result": [{"value": [0, "NaN"]}]}},
            "ok": {"status": "success", "data": {"result": [{"value": [0, "1"]}]}},
            "error": {"status": "error", "error": "parse error"},
        }

        for expected, payload in responses.items():
            body = io.BytesIO(json.dumps(payload).encode())
            with patch.object(verifier.urllib.request, "urlopen") as urlopen:
                urlopen.return_value.__enter__.return_value = body
                status, _detail = verifier.query("http://prom", "up")

            assert status == expected

    def test_expected_missing_entries_name_metrics_we_actually_query(self):
        """An EXPECTED_EMPTY entry that matches no panel is a stale excuse: the panel it
        was written for has been renamed or deleted, and it now silences nothing."""
        verifier = load_verifier()
        exprs = [
            expr for path in dashboard_files() for _title, expr in verifier.panel_targets(path)
        ]

        for needle in verifier.EXPECTED_MISSING:
            assert any(needle in expr for expr in exprs), f"{needle} matches no panel"


# ---------------------------------------------------------------------------
# Tempo: the tracing backend (issue #5 phase 1)
#
# Same silent-failure logic as everything above. A Tempo missing from the compose file,
# an OTLP port that does not match what Alloy is told to push to, or a retention window
# that drifts away from Prometheus' all produce an empty trace view and no error at all.
# ---------------------------------------------------------------------------


class TestTempo:
    def compose(self):
        return yaml.safe_load((OBS / "docker-compose.yml").read_text())

    def config(self):
        return yaml.safe_load((OBS / "tempo" / "config.yml").read_text())

    def datasource(self):
        data = load_yaml(PROVISIONING / "datasources" / "lgtm.yml")
        return next(ds for ds in data["datasources"] if ds["uid"] == "tempo")

    def test_service_exists_and_pins_a_tag(self):
        image = self.compose()["services"]["tempo"]["image"]

        assert image.startswith("grafana/tempo:")
        assert not image.endswith(":latest"), "an unpinned tag makes the stack unreproducible"

    def test_config_is_mounted_read_only(self):
        volumes = self.compose()["services"]["tempo"]["volumes"]
        assert any("tempo/config.yml" in v and v.endswith(":ro") for v in volumes)

    def test_trace_data_has_a_named_volume(self):
        compose = self.compose()

        assert "tempo-data" in compose["volumes"]
        assert any(v.startswith("tempo-data:") for v in compose["services"]["tempo"]["volumes"])

    def test_otlp_receivers_are_published_to_the_lan(self):
        """Alloy on .200/.201 pushes here. An unpublished receiver is a black hole: the
        exporter queues, retries and drops, and nothing on this host logs a thing."""
        ports = self.compose()["services"]["tempo"]["ports"]
        published = {p.split(":")[0] for p in ports}

        assert {"3200", "4317", "4318"} <= published

    def test_published_ports_match_the_listeners_in_the_config(self):
        """Publishing a port the process does not listen on opens onto nothing."""
        config = self.config()
        otlp = config["distributor"]["receivers"]["otlp"]["protocols"]

        assert otlp["grpc"]["endpoint"].endswith(":4317")
        assert otlp["http"]["endpoint"].endswith(":4318")
        assert config["server"]["http_listen_port"] == 3200

    def test_there_is_deliberately_no_healthcheck(self):
        """The Tempo image is DISTROLESS - no shell, no wget, no curl - so a Loki-style
        ["CMD", "wget", ...] probe cannot execute. With one, the container sits
        permanently "unhealthy" while serving perfectly. Verified against 2.10.8."""
        assert "healthcheck" not in self.compose()["services"]["tempo"]

    def test_grafana_starts_after_tempo(self):
        assert "tempo" in self.compose()["services"]["grafana"]["depends_on"]

    def test_grpc_port_does_not_collide_with_loki(self):
        loki = yaml.safe_load((OBS / "loki" / "config.yml").read_text())

        assert self.config()["server"]["grpc_listen_port"] != loki["server"]["grpc_listen_port"]

    def test_retention_matches_prometheus(self):
        """A trace and the metrics around it must age out together. If Tempo expires
        first, clicking through from a metric lands on a trace that no longer exists."""
        prom_cmd = " ".join(self.compose()["services"]["prometheus"]["command"])
        match = re.search(r"--storage\.tsdb\.retention\.time=(\d+)d", prom_cmd)
        assert match, "prometheus retention flag not found"

        block_retention = self.config()["compactor"]["compaction"]["block_retention"]
        assert block_retention.endswith("h")
        assert int(block_retention[:-1]) == int(match.group(1)) * 24

    def test_ingestion_is_bounded(self):
        """Tempo has no --storage.tsdb.retention.size equivalent, so an ingestion cap is
        the only thing standing between a runaway exporter and the disk that Prometheus
        and Loki also live on."""
        defaults = self.config()["overrides"]["defaults"]

        assert defaults["ingestion"]["rate_limit_bytes"] > 0
        assert defaults["global"]["max_bytes_per_trace"] > 0

    def test_blocks_flush_promptly_enough_to_debug_with(self):
        """Tempo's 30m default leaves a finished trace unqueryable in the WAL for half an
        hour, which is indistinguishable from a broken pipeline while testing one."""
        assert self.config()["ingester"]["max_block_duration"] == "5m"

    def test_usage_reporting_is_off(self):
        assert self.config()["usage_report"]["reporting_enabled"] is False

    def test_streaming_flag_agrees_with_the_datasource(self):
        """Grafana's streamingEnabled.search silently does nothing unless Tempo allows
        it, so the two halves are pinned to each other."""
        assert self.config()["stream_over_http_enabled"] is True
        assert self.datasource()["jsonData"]["streamingEnabled"]["search"] is True

    def test_datasource_points_at_the_compose_service_and_port(self):
        datasource = self.datasource()

        assert datasource["type"] == "tempo"
        assert datasource["url"] == f"http://tempo:{self.config()['server']['http_listen_port']}"

    def test_datasource_is_not_the_default(self):
        assert not self.datasource().get("isDefault", False)

    def test_trace_to_logs_queries_the_field_the_formatter_actually_emits(self):
        """The inverse of the phase-1 test that asserted this link stayed ABSENT. It is
        correct only because core/logging.py now writes trace_id into the JSON body; if
        that field is ever renamed, this link resolves to nothing on every span and
        nothing anywhere reports an error."""
        traces_to_logs = self.datasource()["jsonData"]["tracesToLogsV2"]

        assert traces_to_logs["datasourceUid"] == "loki"
        assert "trace_id" in traces_to_logs["query"]
        assert "| json |" in traces_to_logs["query"], "the body is not indexed; it must be parsed"

    def test_log_to_trace_link_points_at_this_datasource(self):
        """The other direction: Loki's trace_id derived field must target tempo, and
        Grafana resolves a Tempo link by raw trace id rather than by a query."""
        data = load_yaml(PROVISIONING / "datasources" / "lgtm.yml")
        loki = next(ds for ds in data["datasources"] if ds["uid"] == "loki")
        field = next(f for f in loki["jsonData"]["derivedFields"] if f["name"] == "trace_id")

        assert field["datasourceUid"] == "tempo"
        assert field["url"] == "${__value.raw}"


# ---------------------------------------------------------------------------
# Traces: the Alloy OTLP pipeline (issue #5 phase 2)
#
# The failure modes here are the quietest in the whole stack. An exporter pointed at
# the wrong port does not error - it queues, retries and drops. A receiver that is not
# enabled on the host running the app just means no spans ever arrive. Neither logs
# anything on the box you would think to look at.
# ---------------------------------------------------------------------------


def site_role_vars(host):
    """The observability role's per-host vars from site.yml."""
    site = yaml.safe_load((ANSIBLE / "site.yml").read_text())
    play = next(p for p in site if p["hosts"] == host)
    return next(
        r for r in play["roles"] if isinstance(r, dict) and r.get("role") == "observability"
    )


class TestTraces:
    def template(self):
        return ALLOY_TEMPLATE.read_text()

    def traces_block(self):
        """Just the guarded traces section of the Alloy template."""
        text = self.template()
        return text[text.index("{% if alloy_traces_enabled %}") :]

    def tempo_config(self):
        return yaml.safe_load((OBS / "tempo" / "config.yml").read_text())

    def test_default_is_off(self):
        """Same opt-in posture as every other optional block in this role."""
        assert alloy_defaults()["alloy_traces_enabled"] is False

    def test_every_otelcol_component_is_behind_the_gate(self):
        """A component rendered outside the guard would make every host open an OTLP
        receiver the moment the role runs, including ones that must not."""
        before_gate = self.template().split("{% if alloy_traces_enabled %}")[0]

        assert "otelcol" not in before_gate

    def test_receiver_binds_loopback_only(self):
        """Spans are attacker-controlled text that gets rendered into a UI. The only
        legitimate clients are local processes, so the LAN must not be able to inject."""
        block = self.traces_block()

        assert 'endpoint = "127.0.0.1:4317"' in block
        assert 'endpoint = "127.0.0.1:4318"' in block
        assert "0.0.0.0" not in block

    def test_exporter_port_matches_the_port_tempo_actually_listens_on(self):
        """The cross-file pin that matters most. If these drift, Alloy exports into a
        closed port: it queues, retries, drops, and logs nothing Tempo-side."""
        endpoint = alloy_defaults()["alloy_otlp_endpoint"]
        exporter_port = endpoint.rsplit(":", 1)[1]

        otlp = self.tempo_config()["distributor"]["receivers"]["otlp"]["protocols"]
        assert otlp["grpc"]["endpoint"].rsplit(":", 1)[1] == exporter_port

    def test_exporter_endpoint_follows_obs_host(self):
        """So the obs box's loopback override is honoured exactly like the Loki and
        Prometheus sinks honour it, rather than hard-coding the LAN address."""
        assert alloy_defaults()["alloy_otlp_endpoint"].startswith("{{ obs_host }}")

    def test_pipeline_stages_are_wired_in_order(self):
        """receiver -> attributes -> batch -> exporter. A stage that forwards to the
        wrong input silently drops that signal rather than failing to start."""
        block = self.traces_block()

        assert "traces = [otelcol.processor.attributes.host.input]" in block
        assert "traces = [otelcol.processor.batch.default.input]" in block
        assert "traces = [otelcol.exporter.otlp.tempo.input]" in block

    def test_spans_are_labelled_with_the_host_like_the_other_two_signals(self):
        """loki.write and prometheus.remote_write both stamp host via external_labels.
        Three hosts push into one Tempo, so without this a span's origin is lost."""
        block = self.traces_block()

        assert 'key    = "host"' in block
        assert 'value  = "{{ inventory_hostname }}"' in block

    def test_enabled_on_the_app_host(self):
        """The only box running instrumented processes - gunicorn workers and Celery
        prefork children. If this is off, phase 3 produces no traces at all."""
        assert site_role_vars("stockmarket").get("alloy_traces_enabled") is True

    def test_not_enabled_on_the_observability_host(self):
        """Tempo publishes 0.0.0.0:4317 and 0.0.0.0:4318 on .208, and 0.0.0.0 already
        covers 127.0.0.1 - so an Alloy receiver there cannot bind, and a component that
        fails to start takes the WHOLE agent down, losing that host's logs and metrics
        too. This is a much bigger blast radius than "traces are missing"."""
        assert "alloy_traces_enabled" not in site_role_vars("stockmarket-obs")

    def test_not_enabled_on_the_db_host(self):
        """Nothing instrumented runs there; an open receiver would just be surface."""
        assert "alloy_traces_enabled" not in site_role_vars("stockmarket-db")

    def test_receiver_ports_do_not_collide_with_the_app_metrics_ports(self):
        """The app host already binds 8005-8008 (gunicorn workers) and 8010 (the Celery
        exporter) on the loopback. A collision would fail the agent at startup."""
        app_targets = site_role_vars("stockmarket")["alloy_app_scrape_targets"]
        used = {t.rsplit(":", 1)[1] for scrape in app_targets for t in scrape["targets"]}

        assert not ({"4317", "4318"} & used)


class TestStackDeployment:
    """The monitoring role is what actually gets these files onto .208."""

    def role_tasks(self):
        path = ANSIBLE / "roles" / "monitoring" / "tasks" / "main.yml"
        return yaml.safe_load(path.read_text())

    def test_the_whole_observability_directory_is_copied(self):
        """Tempo shipped for free because this task copies the DIRECTORY. If it is ever
        converted to an explicit file list, the next config subdir added to the repo
        stops reaching the host - and compose fails on a missing bind-mount source."""
        task = next(t for t in self.role_tasks() if "Copy stack configuration" in t["name"])

        assert task["copy"]["src"].endswith("/observability/")

    def test_every_compose_bind_mount_source_exists_in_the_repo(self):
        """docker compose creates a DIRECTORY where a missing bind-mount file should be
        (verified the hard way while building phase 1), so the container then starts with
        a directory as its config and dies in a way that reads like a config bug."""
        compose = yaml.safe_load((OBS / "docker-compose.yml").read_text())

        for name, service in compose["services"].items():
            for volume in service.get("volumes", []):
                source = volume.split(":")[0]
                if not source.startswith("./"):
                    continue  # named volume, not a bind mount
                assert (OBS / source[2:]).exists(), f"{name} mounts missing {source}"

    def test_trace_smoke_test_recipe_exists(self):
        """Every hop in the trace path fails silently, so the one-command check that
        proves it end to end is part of the deliverable, not a convenience."""
        justfile = (REPO_ROOT / "justfile").read_text()

        assert "obs-trace-test:" in justfile
        assert "127.0.0.1:4318" in justfile


# ---------------------------------------------------------------------------
# Span metrics and exemplars (issue #5 phase 5)
#
# This is the part of the stack where a mistake is EXPENSIVE rather than merely
# invisible: span metrics create a series per span name per dimension combination, so
# an unbounded dimension does not produce a wrong number, it produces millions of them.
# ---------------------------------------------------------------------------


class TestSpanMetrics:
    def tempo_config(self):
        return yaml.safe_load((OBS / "tempo" / "config.yml").read_text())

    def compose(self):
        return yaml.safe_load((OBS / "docker-compose.yml").read_text())

    def test_generator_processors_are_enabled(self):
        """The metrics_generator block is inert until the processors are switched on in
        overrides - config present, metrics silently absent."""
        processors = self.tempo_config()["overrides"]["defaults"]["metrics_generator"]["processors"]

        assert "span-metrics" in processors

    def test_generator_remote_writes_to_the_prometheus_service(self):
        remote_write = self.tempo_config()["metrics_generator"]["storage"]["remote_write"]
        url = remote_write[0]["url"]

        assert url.startswith("http://prometheus:")
        assert url.endswith("/api/v1/write")

    def test_span_metric_dimensions_are_bounded(self):
        """THE cardinality guard. Dimensions multiply the series count, so only bounded
        attributes may appear. agent.run_id is a UUID per run - it belongs in a span
        attribute (free in Tempo) and would be ruinous here."""
        dimensions = self.tempo_config()["metrics_generator"]["processor"]["span_metrics"][
            "dimensions"
        ]

        forbidden = {"agent.run_id", "request_id", "trace_id", "symbol", "user", "user_id"}
        assert not (set(dimensions) & forbidden), f"unbounded dimension in {dimensions}"

    def test_exemplars_are_sent_and_stored_and_linkable(self):
        """Three separate switches, and missing any one fails SILENTLY - the write
        succeeds and only the trace id goes missing."""
        remote_write = self.tempo_config()["metrics_generator"]["storage"]["remote_write"]
        assert remote_write[0]["send_exemplars"] is True

        prometheus_cmd = " ".join(self.compose()["services"]["prometheus"]["command"])
        assert "--enable-feature=exemplar-storage" in prometheus_cmd

        data = load_yaml(PROVISIONING / "datasources" / "lgtm.yml")
        prometheus = next(ds for ds in data["datasources"] if ds["uid"] == "prometheus")
        destinations = prometheus["jsonData"]["exemplarTraceIdDestinations"]
        assert destinations[0]["datasourceUid"] == "tempo"
        # Tempo attaches the id under `traceID`, camelCase - NOT `trace_id`, which is
        # what our log bodies use. Confirmed against the live exemplar API on 2.10.8.
        # With the wrong name Grafana still draws the dot and the click does nothing.
        assert destinations[0]["name"] == "traceID"

    def test_generator_storage_lives_on_the_tempo_volume(self):
        """The WAL must sit under the mounted volume or it is lost on every restart."""
        storage = self.tempo_config()["metrics_generator"]["storage"]

        assert storage["path"].startswith("/var/tempo/")


class TestAlertingStaysMetricBased:
    """The phase-5 alerting review, encoded rather than written down.

    Span metrics COULD back an alert now, and deliberately do not. Three reasons:
    tracing ships OFF, so such a rule would sit permanently in NoData on any deployment
    that has not enabled it; span metrics depend on the whole trace pipeline (app ->
    Alloy -> Tempo -> generator -> remote_write), so the rule would fire for pipeline
    faults rather than application faults; and the existing rules already cover the same
    failures from a shorter, more reliable causal chain. Traces are for DIAGNOSIS,
    metrics for alerting.
    """

    def rules(self):
        data = load_yaml(PROVISIONING / "alerting" / "rules.yml")
        return [rule for group in data["groups"] for rule in group["rules"]]

    def test_rule_count_is_unchanged_by_the_tracing_work(self):
        """Adding a dashboard must not quietly add or drop alerts."""
        assert len(self.rules()) == 12

    def test_no_alert_rule_depends_on_span_metrics(self):
        expressions = " ".join(
            node["model"].get("expr", "")
            for rule in self.rules()
            for node in rule.get("data", [])
            if isinstance(node.get("model"), dict)
        )

        assert "traces_spanmetrics" not in expressions
        assert "traces_service_graph" not in expressions


class TestTracingDashboard:
    def board(self):
        return json.loads((DASHBOARDS / "tracing.json").read_text())

    def test_panels_query_span_metrics_that_tempo_actually_generates(self):
        """Tempo emits traces_spanmetrics_*. A panel on an invented name renders empty,
        which is indistinguishable from an idle system by eye."""
        board = self.board()
        exprs = [t["expr"] for p in board["panels"] for t in p.get("targets", []) if "expr" in t]

        assert exprs
        for expr in exprs:
            assert "traces_spanmetrics_" in expr, expr

    def test_dimension_labels_match_the_configured_dimensions(self):
        """Tempo renders a dimension's dots as underscores. Querying llm.model instead of
        llm_model is a label that never exists, so the panel is simply always empty."""
        dimensions = yaml.safe_load((OBS / "tempo" / "config.yml").read_text())[
            "metrics_generator"
        ]["processor"]["span_metrics"]["dimensions"]
        expected = {d.replace(".", "_") for d in dimensions}
        exprs = " ".join(
            t["expr"] for p in self.board()["panels"] for t in p.get("targets", []) if "expr" in t
        )

        used = {label for label in expected if label in exprs}
        assert used == expected, f"configured but never queried: {expected - used}"

    def test_span_name_regexes_survive_both_escaping_layers(self):
        """REGRESSION, and the subtlety is that there are TWO layers.

        PromQL string literals use Go escaping, where `\\.` is an INVALID escape and
        Prometheus answers HTTP 400 - not an empty result, a hard error. So the regex a
        panel needs is `ollama\\\\..*` in PromQL text, which is `ollama\\\\\\\\..*`
        in the JSON file because JSON escapes each backslash again.

        Getting this wrong in EITHER direction is silent in a different way: too few
        backslashes is a 400 that only obs-verify sees, too many is a regex matching a
        literal backslash, which matches nothing and renders as an idle panel.
        """
        expressions = " ".join(
            t["expr"] for p in self.board()["panels"] for t in p.get("targets", []) if "expr" in t
        )
        patterns = set(re.findall(r'span_name=~"([^"]+)"', expressions))
        assert patterns, "no span_name regex found; the dashboard shape changed"

        emitted = {"ollama.chat", "ollama.chat_stream", "ollama.chat_many", "ollama.embed"}
        llm_patterns = [p for p in patterns if "ollama" in p]
        assert llm_patterns, "nothing selects the LLM spans"

        for pattern in llm_patterns:
            # A lone backslash would be rejected by Prometheus before it ever ran.
            assert "\\\\" in pattern, (
                f"{pattern!r} is not escaped for a PromQL string literal; "
                "Prometheus returns HTTP 400 for an invalid escape"
            )
            # What the regex engine finally receives, after PromQL unescapes the literal.
            regex = pattern.replace("\\\\", "\\")
            matched = {name for name in emitted if re.fullmatch(regex, name)}
            assert matched == emitted, f"{pattern!r} misses {sorted(emitted - matched)}"

    def test_literal_span_name_selectors_name_spans_we_emit(self):
        """The exact-match counterpart: a typo'd literal is just as silent."""
        expressions = " ".join(
            t["expr"] for p in self.board()["panels"] for t in p.get("targets", []) if "expr" in t
        )
        literals = set(re.findall(r'span_name="([^"]+)"', expressions))

        assert literals <= {"agent.run", "agent.tool"}, f"unknown span name: {literals}"

    def test_the_traceql_panel_uses_the_tempo_datasource(self):
        """And therefore has no 'expr', which is exactly why obs-verify skips it rather
        than failing to parse it as PromQL."""
        traceql = [p for p in self.board()["panels"] if p["datasource"]["uid"] == "tempo"]

        assert traceql
        for panel in traceql:
            for target in panel["targets"]:
                assert "expr" not in target
                assert "query" in target

    def test_exemplars_are_requested_on_the_latency_panels(self):
        """Storing exemplars is not enough - a panel must ASK for them or the dots never
        render and the click-through silently does not exist."""
        panels = [p for p in self.board()["panels"] if "p95" in p["title"]]
        assert panels

        assert any(t.get("exemplar") for p in panels for t in p.get("targets", [])), (
            "no latency panel requests exemplars"
        )

    def test_error_ratio_cannot_render_infinity_on_an_idle_system(self):
        """Empty is not zero: a ratio over an empty vector is empty, and an unguarded
        divisor yields +Inf. Same class as the Redis maxmemory alert."""
        exprs = [
            t["expr"]
            for p in self.board()["panels"]
            for t in p.get("targets", [])
            if "expr" in t and "/" in t.get("expr", "")
        ]

        for expr in exprs:
            assert "clamp_min(" in expr, expr


# ---------------------------------------------------------------------------
# Load testing (issue #12): the k6 dashboard and the run annotation
#
# k6 remote-writes its own metrics, so every failure mode here is the familiar silent
# one: a trend-stat suffix that k6 was never told to emit, a label that would put one
# Prometheus series per company into the TSDB, or an annotation that simply never fires.
# ---------------------------------------------------------------------------

K6_DIR = REPO_ROOT / "loadtest" / "k6"
JUSTFILE = REPO_ROOT / "justfile"

# k6's built-in metrics by type, and how its Prometheus remote-write output names each:
# counters get `_total`, rates `_rate`, gauges nothing, trends one series per configured
# stat (`p(95)` -> `_p95`).
K6_COUNTERS = {"http_reqs", "data_sent", "data_received", "iterations", "dropped_iterations"}
K6_RATES = {"checks", "http_req_failed"}
K6_GAUGES = {"vus", "vus_max"}
K6_TRENDS = {
    "http_req_duration",
    "http_req_blocked",
    "http_req_connecting",
    "http_req_tls_handshaking",
    "http_req_sending",
    "http_req_waiting",
    "http_req_receiving",
    "iteration_duration",
}
HIGH_CARDINALITY_LABELS = ("url", "vu", "iter")


def trend_stats():
    match = re.search(r'K6_PROMETHEUS_RW_TREND_STATS="([^"]+)"', JUSTFILE.read_text())
    assert match, "the lt recipe no longer sets K6_PROMETHEUS_RW_TREND_STATS"
    return [re.sub(r"[()]", "", stat) for stat in match.group(1).split(",")]


def custom_k6_metrics():
    """Custom metrics declared in the k6 library, by type."""
    found = {}
    for path in K6_DIR.rglob("*.js"):
        for kind, name in re.findall(
            r"new (Counter|Rate|Gauge|Trend)\('([a-z_]+)'\)", path.read_text()
        ):
            found[name] = kind
    return found


def k6_remote_write_names():
    names = {f"k6_{m}_total" for m in K6_COUNTERS}
    names |= {f"k6_{m}_rate" for m in K6_RATES}
    names |= {f"k6_{m}" for m in K6_GAUGES}
    names |= {f"k6_{m}_{stat}" for m in K6_TRENDS for stat in trend_stats()}
    suffix = {"Counter": "_total", "Rate": "_rate", "Gauge": ""}
    for name, kind in custom_k6_metrics().items():
        if kind == "Trend":
            names |= {f"k6_{name}_{stat}" for stat in trend_stats()}
        else:
            names.add(f"k6_{name}{suffix[kind]}")
    return names


def all_dashboard_exprs():
    """Every PromQL expression on every dashboard, panels AND annotations."""
    exprs = []
    for path in dashboard_files():
        board = json.loads(path.read_text())
        exprs += [t["expr"] for p in board["panels"] for t in p["targets"] if "expr" in t]
        exprs += [a["expr"] for a in board.get("annotations", {}).get("list", []) if "expr" in a]
    return exprs


class TestLoadTestDashboard:
    def board(self):
        return json.loads((DASHBOARDS / "loadtest.json").read_text())

    def k6_exprs(self):
        return [
            t["expr"]
            for p in self.board()["panels"]
            for t in p["targets"]
            if "k6_" in t.get("expr", "")
        ]

    def test_every_k6_metric_queried_is_one_k6_emits(self):
        """k6 only writes the trend stats it is told to (K6_PROMETHEUS_RW_TREND_STATS),
        so a `_p90` panel with no `p(90)` configured renders empty forever."""
        emitted = k6_remote_write_names()
        queried = set(re.findall(r"\bk6_[a-z0-9_]+\b", " ".join(all_dashboard_exprs())))

        assert queried, "no k6 metric is queried - has the dashboard changed shape?"
        assert not queried - emitted, f"k6 never emits: {sorted(queried - emitted)}"

    def test_the_refresh_counter_panel_matches_the_counter_the_scripts_declare(self):
        assert custom_k6_metrics().get("auth_refreshes") == "Counter"
        assert any("k6_auth_refreshes_total" in e for e in self.k6_exprs())

    def test_every_k6_metric_is_declared_absent_outside_a_run(self):
        """Outside a run every k6_* series is stale. obs-verify must be told so BY NAME,
        or `just obs-verify` fails whenever no load test happens to be running."""
        declared = load_verifier().EXPECTED_MISSING
        queried = set(re.findall(r"\bk6_[a-z0-9_]+\b", " ".join(self.k6_exprs())))

        assert not queried - set(declared), sorted(queried - set(declared))

    def test_no_query_touches_a_high_cardinality_label(self):
        """url/vu/iter are removed from the k6 system tags; a panel grouping by one would
        be empty, and if the tag ever came back it would be one series per company."""
        for expr in all_dashboard_exprs():
            for label in HIGH_CARDINALITY_LABELS:
                assert not re.search(rf"\b{label}\s*(=|!=|=~|!~)", expr), expr
                for grouping in re.findall(r"\b(?:by|without)\s*\(([^)]*)\)", expr):
                    assert label not in [g.strip() for g in grouping.split(",")], expr

    def test_the_k6_config_removes_the_high_cardinality_system_tags(self):
        config = (K6_DIR / "lib" / "config.js").read_text()
        allow_list = re.search(r"export const SYSTEM_TAGS = \[([^\]]*)\]", config)
        assert allow_list, "SYSTEM_TAGS allow-list missing"
        tags = set(re.findall(r"'([a-z_]+)'", allow_list.group(1)))

        assert "name" in tags
        assert not tags & set(HIGH_CARDINALITY_LABELS)

    def test_every_k6_panel_filters_on_the_run_picker(self):
        variables = [v["name"] for v in self.board()["templating"]["list"]]
        assert variables == ["testid"]
        for expr in self.k6_exprs():
            assert 'testid=~"$testid"' in expr, expr

    def test_server_panels_sit_beside_the_k6_panels(self):
        """The point of the shared Grafana: see WHICH resource saturates at the knee."""
        exprs = " ".join(t["expr"] for p in self.board()["panels"] for t in p["targets"])
        for family in (
            "django_http_",
            "process_resident_memory_bytes",
            "node_cpu_",
            "pg_stat_",
            "redis_",
        ):
            assert family in exprs, family

    def test_promql_regexes_use_no_invalid_escape(self):
        """Two layers (see TestTracingDashboard): a lone backslash escape in a PromQL
        string literal is an HTTP 400, not an empty panel."""
        for expr in self.k6_exprs() + all_dashboard_exprs():
            for pattern in re.findall(r'=~"([^"]*)"', expr):
                assert not re.search(r"(?<!\\)\\(?!\\)", pattern), pattern


class TestLoadTestAnnotation:
    """Without it, a load test makes every prod panel look like an incident."""

    @pytest.mark.parametrize("path", dashboard_files(), ids=lambda p: p.stem)
    def test_every_dashboard_marks_load_test_runs(self, path):
        annotations = json.loads(path.read_text()).get("annotations", {}).get("list", [])
        runs = [a for a in annotations if a.get("name") == "Load test"]

        assert len(runs) == 1, f"{path.stem} has no load-test annotation"
        (run,) = runs
        assert run["enable"] is True
        assert run["datasource"]["uid"] in datasource_uids()
        assert "k6_vus" in run["expr"] and "testid" in run["expr"]
        assert "{{testid}}" in run["textFormat"]

    def test_the_annotation_metric_is_one_k6_emits(self):
        assert "k6_vus" in k6_remote_write_names()
