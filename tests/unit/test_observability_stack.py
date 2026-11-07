"""The local observability stack is declared, pinned and provisioned (T6.2, #56).

These are file-shape tests: no Docker, no network and no server. They pin the
contract the issue fixes — the one Makefile file list, the published ports, the
pinned images, the collector wiring, the provisioned Grafana objects and the
trace link the dashboard expands — so a regression fails `make test-unit`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OBS = ROOT / "observability"
COMPOSE = ROOT / "compose.observability.yaml"
BASE_COMPOSE = ROOT / "compose.yaml"
MAKEFILE = ROOT / "Makefile"
DASHBOARD = OBS / "dashboards" / "order-journey.json"

OBSERVABILITY_SERVICES = {
    "otel-collector",
    "prometheus",
    "loki",
    "tempo",
    "alloy",
    "grafana",
}

# AC8: every image is pinned by tag + digest. T6.3 (#57) reuses the Prometheus
# tag for `promtool check rules`.
PINNED_IMAGES = {
    "otel-collector": (
        "otel/opentelemetry-collector-contrib:0.164.0"
        "@sha256:340c9ca6a36617084c6661bdc4f0fe92b7cda5a805d61673ec8db375fddc522b"
    ),
    "prometheus": (
        "prom/prometheus:v3.16.0"
        "@sha256:e04987641b57704f408e31f6373ba4138ecf27cb4a165d24aabb6c38fddd0f06"
    ),
    "loki": (
        "grafana/loki:3.6.20"
        "@sha256:be040ec94865dabe4821ce1c0f109452bd4b5acb566ae376672696eb43caedb7"
    ),
    "tempo": (
        "grafana/tempo:2.10.10"
        "@sha256:12b0820f13ffa10ce956b6e9acc3b03f3cffded99109be6cc09d106fe56e5d38"
    ),
    "alloy": (
        "grafana/alloy:v1.21.3"
        "@sha256:8ab871206bd2d8f89277f53abffee5f452a293980788d52f85fa183a87a505a4"
    ),
    "grafana": (
        "grafana/grafana:13.2.5"
        "@sha256:9f7aa1e1e3246aade5792d35a738049f7f32f89cd51d1956cf426a4e86268a84"
    ),
}

REQUEST_PANELS = {
    "Orders placed": "short",
    "Orders failed by reason": "short",
    "p95 request latency": "s",
    "Reservation conflicts": "short",
}

ALL_PANELS = {**REQUEST_PANELS, "Invariant drift": "short"}


@pytest.fixture(scope="module")
def overlay() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dashboard() -> dict[str, Any]:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _host_ports(service: dict[str, Any]) -> set[str]:
    ports: set[str] = set()
    for entry in service.get("ports", []):
        text = str(entry)
        if ":" in text:
            ports.add(text.split(":", 1)[0])
    return ports


# ---------------------------------------------------------------------------
# AC1: one command, one file list, both targets
# ---------------------------------------------------------------------------


def test_makefile_defines_the_one_file_list_and_both_targets() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    assert (
        "OBSERVABILITY_FILES = -f compose.yaml -f compose.observability.yaml "
        "$(if $(wildcard compose.override.yaml),-f compose.override.yaml)\n"
    ) in text
    assert (
        "observability:\n"
        "\tdocker compose $(OBSERVABILITY_FILES) --profile observability up -d --build\n"
    ) in text
    assert (
        "observability-down:\n"
        "\tdocker compose $(OBSERVABILITY_FILES) --profile observability down\n"
    ) in text
    phony = next(line for line in text.splitlines() if line.startswith(".PHONY:"))
    assert {"observability", "observability-down"} <= set(phony.split()[1:])


def test_make_dev_is_untouched() -> None:
    # AC1: `make dev` still starts only app + db with the single base file.
    assert "dev:\n\tdocker compose up --build\n" in MAKEFILE.read_text(encoding="utf-8")


def test_overlay_declares_the_six_profiled_services(overlay: dict[str, Any]) -> None:
    services = overlay["services"]
    for name in OBSERVABILITY_SERVICES:
        assert services[name]["profiles"] == ["observability"], name


def test_overlay_adds_to_app_and_never_restates_ports_db_or_the_volume(
    overlay: dict[str, Any],
) -> None:
    services = overlay["services"]
    assert "db" not in services
    assert "ports" not in services["app"]
    assert "stockroom-db" not in overlay.get("volumes", {})


def test_app_gets_the_local_otlp_target_and_header_passthrough(overlay: dict[str, Any]) -> None:
    environment = overlay["services"]["app"]["environment"]
    assert (
        environment["OTEL_EXPORTER_OTLP_ENDPOINT"]
        == "${OTEL_EXPORTER_OTLP_ENDPOINT:-http://otel-collector:4318}"
    )
    assert environment["OTEL_EXPORTER_OTLP_HEADERS"] == "${OTEL_EXPORTER_OTLP_HEADERS:-}"


# ---------------------------------------------------------------------------
# AC2: published ports are the contract
# ---------------------------------------------------------------------------


def test_published_ports_are_the_contract(overlay: dict[str, Any]) -> None:
    services = overlay["services"]
    assert _host_ports(services["otel-collector"]) == {"4318", "4317"}
    assert _host_ports(services["prometheus"]) == {"9090"}
    assert _host_ports(services["tempo"]) == {"3200"}
    assert _host_ports(services["loki"]) == {"3100"}
    assert _host_ports(services["grafana"]) == {"3000"}
    assert _host_ports(services["alloy"]) == set()


def test_internal_ports_are_never_published(overlay: dict[str, Any]) -> None:
    services = overlay["services"]
    assert "8889" not in _host_ports(services["otel-collector"])
    assert {"4317", "4318"}.isdisjoint(_host_ports(services["tempo"]))


# ---------------------------------------------------------------------------
# AC3 / AC8: collector wiring and pinned images
# ---------------------------------------------------------------------------


def test_collector_receives_otlp_and_forwards_traces_to_tempo() -> None:
    config = yaml.safe_load((OBS / "otel-collector" / "config.yaml").read_text(encoding="utf-8"))
    protocols = config["receivers"]["otlp"]["protocols"]
    assert protocols["http"]["endpoint"].endswith(":4318")
    assert protocols["grpc"]["endpoint"].endswith(":4317")
    assert config["service"]["pipelines"]["traces"]["exporters"] == ["otlp/tempo"]
    assert config["exporters"]["otlp/tempo"]["endpoint"] == "tempo:4317"


def test_collector_converts_resources_to_prometheus_labels() -> None:
    config = yaml.safe_load((OBS / "otel-collector" / "config.yaml").read_text(encoding="utf-8"))
    exporter = config["exporters"]["prometheus"]
    assert exporter["endpoint"].endswith(":8889")
    assert exporter["resource_to_telemetry_conversion"]["enabled"] is True


def test_logs_do_not_travel_over_otlp() -> None:
    config = yaml.safe_load((OBS / "otel-collector" / "config.yaml").read_text(encoding="utf-8"))
    assert "logs" not in config["service"]["pipelines"]


def test_prometheus_scrapes_only_the_collector_and_loads_the_alert_rules() -> None:
    # T6.3 (#57) adds the rule file; the scrape contract is unchanged.
    config = yaml.safe_load((OBS / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"))
    assert config["rule_files"] == ["/etc/prometheus/alerts.yaml"]
    targets = [
        target
        for job in config["scrape_configs"]
        for static in job["static_configs"]
        for target in static["targets"]
    ]
    assert targets == ["otel-collector:8889"]


def test_every_image_is_pinned_by_tag_and_digest(overlay: dict[str, Any]) -> None:
    services = overlay["services"]
    assert set(PINNED_IMAGES) == OBSERVABILITY_SERVICES
    for name, expected in PINNED_IMAGES.items():
        reference = services[name]["image"]
        assert reference == expected, name
        tag, _, digest = reference.partition("@")
        assert not tag.endswith(":latest"), name
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest), name


def test_no_latest_tag_anywhere_in_the_stack() -> None:
    for path in [COMPOSE, BASE_COMPOSE, *OBS.rglob("*")]:
        if path.is_file():
            assert ":latest" not in path.read_text(encoding="utf-8", errors="ignore"), path


# ---------------------------------------------------------------------------
# AC4 / AC5: provisioned Grafana objects and dashboard structure
# ---------------------------------------------------------------------------


def test_datasources_are_provisioned_with_fixed_uids() -> None:
    document = yaml.safe_load(
        (OBS / "grafana" / "provisioning" / "datasources" / "datasources.yaml").read_text(
            encoding="utf-8"
        )
    )
    by_uid = {datasource["uid"]: datasource for datasource in document["datasources"]}
    assert set(by_uid) == {"prometheus", "loki", "tempo"}
    assert by_uid["prometheus"]["url"] == "http://prometheus:9090"
    assert by_uid["loki"]["url"] == "http://loki:3100"
    assert by_uid["tempo"]["url"] == "http://tempo:3200"


def test_dashboard_provider_reads_the_mounted_directory() -> None:
    document = yaml.safe_load(
        (OBS / "grafana" / "provisioning" / "dashboards" / "dashboards.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert document["providers"][0]["options"]["path"] == "/etc/grafana/dashboards"


def test_dashboard_has_identity_and_the_required_variables(dashboard: dict[str, Any]) -> None:
    assert dashboard["uid"] == "stockroom-order-journey"
    assert dashboard["title"]
    assert isinstance(dashboard["schemaVersion"], int)
    variables = {variable["name"]: variable for variable in dashboard["templating"]["list"]}
    assert {"environment", "datasource", "tempo_datasource", "grafana_url"} <= set(variables)
    assert variables["datasource"]["type"] == "datasource"
    assert variables["datasource"]["query"] == "prometheus"
    assert variables["tempo_datasource"]["query"] == "tempo"
    assert variables["grafana_url"]["type"] == "textbox"
    assert variables["grafana_url"]["current"]["value"] == "http://localhost:3000"


def test_dashboard_has_the_required_panels(dashboard: dict[str, Any]) -> None:
    by_title = {panel["title"]: panel for panel in dashboard["panels"]}
    for title, unit in ALL_PANELS.items():
        panel = by_title[title]
        assert isinstance(panel["id"], int), title
        assert panel["type"], title
        assert panel["fieldConfig"]["defaults"]["unit"] == unit, title
        assert panel["datasource"]["uid"] == "${datasource}", title


def test_dashboard_never_hardcodes_a_datasource_uid(dashboard: dict[str, Any]) -> None:
    for node in _walk(dashboard):
        if node.get("type") in {"prometheus", "loki", "tempo"} and "uid" in node:
            assert str(node["uid"]).startswith("${"), node


# ---------------------------------------------------------------------------
# AC6: every request panel links to the trace search and expands cleanly
# ---------------------------------------------------------------------------


def test_every_request_panel_links_to_the_trace_search(dashboard: dict[str, Any]) -> None:
    by_title = {panel["title"]: panel for panel in dashboard["panels"]}
    for title in REQUEST_PANELS:
        links = by_title[title]["links"]
        assert links, title
        url = links[0]["url"]
        assert url.startswith("${grafana_url}/explore"), title
        assert "${tempo_datasource}" in url, title
        assert "http://localhost:3000" not in url, title
        decoded = unquote(url)
        assert '"queryType":"traceId"' in decoded, title
        assert '"query":"${__data.fields.traceID}"' in decoded, title


def test_expanding_a_panel_link_leaves_no_template_and_parses(
    dashboard: dict[str, Any],
) -> None:
    panel = next(panel for panel in dashboard["panels"] if panel["title"] == "Orders placed")
    sample = {
        "grafana_url": "http://localhost:3000",
        "tempo_datasource": "tempo",
        "environment": "development",
        "__data.fields.traceID": "4bf92f3577b34da6a3ce929d0e0e4736",
    }
    expanded = panel["links"][0]["url"]
    for name, value in sample.items():
        expanded = expanded.replace("${" + name + "}", value)

    assert "${" not in expanded
    parts = urlsplit(expanded)
    assert parts.scheme == "http"
    assert parts.netloc == "localhost:3000"
    assert parts.path == "/explore"

    payload = json.loads(parse_qs(parts.query)["left"][0])
    assert payload["datasource"]["uid"] == "tempo"
    query = payload["queries"][0]
    assert query["queryType"] == "traceId"
    assert query["query"] == sample["__data.fields.traceID"]


# ---------------------------------------------------------------------------
# AC7: Alloy reads the app's docker logs, read-only, local-only
# ---------------------------------------------------------------------------


def test_alloy_ships_app_logs_to_loki_over_a_read_only_socket(overlay: dict[str, Any]) -> None:
    alloy = overlay["services"]["alloy"]
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in alloy["volumes"]
    config = (OBS / "alloy" / "config.alloy").read_text(encoding="utf-8")
    assert "loki.source.docker" in config
    assert "http://loki:3100/loki/api/v1/push" in config
    assert "stockroom-app" in config
    assert "docker.sock" not in BASE_COMPOSE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC9 / AC11: no credential, DSN or customer data in what we ship
# ---------------------------------------------------------------------------


SENSITIVE_PATTERNS = (
    re.compile(r"customer_ref"),
    re.compile(r"Basic(?:\s|%20)[A-Za-z0-9+/]{8,}={0,2}"),
    re.compile(r"\bglsa_[A-Za-z0-9]{8,}"),
    re.compile(r"\bglc_[A-Za-z0-9]{8,}"),
    re.compile(r"postgres(?:ql)?(?:\+psycopg)?://[^\s\"']+:[^\s\"']+@"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+\S+"),
)


def test_no_secret_or_customer_data_in_dashboards_or_provisioning() -> None:
    files = [COMPOSE, *[path for path in OBS.rglob("*") if path.is_file()]]
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SENSITIVE_PATTERNS:
            match = pattern.search(text)
            assert match is None, f"{path.relative_to(ROOT)}: {match.group(0)!r}"


TOKEN_SCAN_ROOTS = (OBS, ROOT / "backend", ROOT / "_docs")
TOKEN_PATTERNS = (
    re.compile(r"\bglsa_[A-Za-z0-9]{8,}"),
    re.compile(r"\bglc_[A-Za-z0-9]{8,}"),
    re.compile(r"Basic(?:\s|%20)[A-Za-z0-9+/]{16,}={0,2}"),
)


def test_no_grafana_credential_is_committed_in_the_scanned_trees() -> None:
    files = [COMPOSE, BASE_COMPOSE, *ROOT.glob(".env*")]
    for root in TOKEN_SCAN_ROOTS:
        files.extend(path for path in root.rglob("*") if path.is_file())
    for path in files:
        if path.suffix in {".pyc", ".png", ".jpg", ".ico", ".woff", ".woff2"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in TOKEN_PATTERNS:
            match = pattern.search(text)
            assert match is None, f"{path.relative_to(ROOT)}: {match.group(0)!r}"


def test_committed_env_examples_leave_observability_credentials_empty() -> None:
    for path in ROOT.glob(".env*"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key.strip() in {"OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS"}:
                assert value.strip() == "", f"{path.name}: {key.strip()} must stay empty"


# ---------------------------------------------------------------------------
# AC8 / AC10: the README records the pins, ports and Cloud caveat
# ---------------------------------------------------------------------------


def test_readme_records_pins_ports_and_the_cloud_caveat() -> None:
    text = (OBS / "README.md").read_text(encoding="utf-8")
    for reference in PINNED_IMAGES.values():
        tag, _, digest = reference.partition("@")
        assert tag.rsplit(":", 1)[-1] in text, tag
        assert digest in text, digest
    for port in ("4318", "4317", "9090", "3200", "3100", "3000"):
        assert port in text, port
    assert "stockroom-order-journey" in text
    assert "optional, not exercised in P6" in text
    assert "read-only" in text and "local-only" in text
