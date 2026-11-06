"""The three alert rules, their runbooks and their local firing contract (T6.3, #57).

File-shape tests only: no Docker, no Prometheus, no network. They pin what the
issue fixes — exactly three named Prometheus rules on the order journey, the five
attributes each rule carries, one runbook per rule with the same query, the
`promtool` target on the pinned image, and the absence of PII or secrets.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ALERTS = ROOT / "observability" / "alerts.yaml"
DASHBOARD = ROOT / "observability" / "dashboards" / "order-journey.json"
PROMETHEUS_CONFIG = ROOT / "observability" / "prometheus" / "prometheus.yml"
OVERLAY = ROOT / "compose.observability.yaml"
MAKEFILE = ROOT / "Makefile"
RUNBOOKS = ROOT / "_docs" / "runbooks"

ORDER_ROUTE_MATCHER = 'http_route=~"/api/orders(/.*)?"'

ALERT_NAMES = (
    "StockroomOrderErrorRateHigh",
    "StockroomOrderLatencyP95High",
    "InventoryInvariantViolation",
)

RUNBOOK_FILES = {
    "StockroomOrderErrorRateHigh": "stockroom-order-error-rate-high.md",
    "StockroomOrderLatencyP95High": "stockroom-order-latency-p95-high.md",
    "InventoryInvariantViolation": "stockroom-inventory-invariant-violation.md",
}

# The number in each expression's comparison, repeated in the runbook (AC6).
THRESHOLDS = {
    "StockroomOrderErrorRateHigh": "0.05",
    "StockroomOrderLatencyP95High": "2",
    "InventoryInvariantViolation": "0",
}

ATTRIBUTES = ("service", "environment", "version", "owner", "dashboard_url")

OWNER_PLACEHOLDER = "stockroom-on-call"

PROMETHEUS_IMAGE = (
    "prom/prometheus:v3.16.0"
    "@sha256:e04987641b57704f408e31f6373ba4138ecf27cb4a165d24aabb6c38fddd0f06"
)


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return yaml.safe_load(ALERTS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rules(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [rule for group in document["groups"] for rule in group["rules"]]


@pytest.fixture(scope="module")
def dashboard() -> dict[str, Any]:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def _rule(rules: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(rule for rule in rules if rule["alert"] == name)


def _normalised(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _render(template: str, labels: dict[str, str]) -> str:
    """Expand the rule templates the way Prometheus expands them."""

    def replace(match: re.Match[str]) -> str:
        return labels[match.group(1)]

    return re.sub(r"\{\{\s*\$labels\.([a-z_]+)\s*\}\}", replace, template)


def _runbook(name: str) -> str:
    return (RUNBOOKS / RUNBOOK_FILES[name]).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC1: exactly three rules with the named signals
# ---------------------------------------------------------------------------


def test_alerts_file_defines_exactly_the_three_named_rules(
    rules: list[dict[str, Any]],
) -> None:
    assert [rule["alert"] for rule in rules] == list(ALERT_NAMES)
    assert all("expr" in rule for rule in rules)


def test_every_rule_has_expr_for_severity_and_a_threshold(
    rules: list[dict[str, Any]],
) -> None:
    for rule in rules:
        name = rule["alert"]
        assert rule["expr"].strip(), name
        assert rule["for"].strip(), name
        assert rule["labels"]["severity"].strip(), name
        assert re.search(rf">\s*{re.escape(THRESHOLDS[name])}\b", rule["expr"]), name


def test_error_rate_rule_is_the_problem_json_5xx_ratio_over_five_minutes(
    rules: list[dict[str, Any]],
) -> None:
    expr = _rule(rules, "StockroomOrderErrorRateHigh")["expr"]
    assert "stockroom_http_request_duration_seconds_count" in expr
    assert 'http_response_status_code=~"5.."' in expr
    assert ORDER_ROUTE_MATCHER in expr
    assert "/" in expr
    # 4xx never reaches the numerator: only a 5xx status matcher is present.
    assert not re.search(r'http_response_status_code=~"[^"]*4', expr)
    assert expr.count("[5m]") == 2


def test_latency_rule_is_histogram_quantile_p95_over_the_order_routes(
    rules: list[dict[str, Any]],
) -> None:
    expr = _rule(rules, "StockroomOrderLatencyP95High")["expr"]
    assert re.search(r"histogram_quantile\(\s*0\.95", expr)
    assert "stockroom_http_request_duration_seconds_bucket" in expr
    assert ORDER_ROUTE_MATCHER in expr
    assert "[5m]" in expr


def test_invariant_rule_is_the_drift_gauge_above_zero(
    rules: list[dict[str, Any]],
) -> None:
    expr = _normalised(_rule(rules, "InventoryInvariantViolation")["expr"])
    # The collector exports a unit-1 gauge as `..._ratio`; the rule evaluates
    # that series under the name `_docs/domain.md` §4 documents.
    assert "stockroom_stock_invariant_drift_ratio" in expr
    assert '"stockroom_stock_invariant_drift"' in expr
    assert expr.endswith("> 0")


# ---------------------------------------------------------------------------
# AC2: five attributes, templated from the metric, pointing at local Grafana
# ---------------------------------------------------------------------------


def test_every_rule_carries_the_five_attributes(rules: list[dict[str, Any]]) -> None:
    for rule in rules:
        labels = rule["labels"]
        for attribute in ATTRIBUTES:
            assert labels.get(attribute, "").strip(), (rule["alert"], attribute)
        assert labels["service"] == "stockroom"
        assert labels["owner"] == OWNER_PLACEHOLDER


def test_environment_and_version_come_from_the_metric_labels(
    rules: list[dict[str, Any]],
) -> None:
    for rule in rules:
        labels = rule["labels"]
        assert labels["environment"] == "{{ $labels.deployment_environment }}", rule["alert"]
        assert labels["version"] == "{{ $labels.service_version }}", rule["alert"]


def test_every_aggregation_preserves_the_version_and_environment_labels(
    rules: list[dict[str, Any]],
) -> None:
    for name in ("StockroomOrderErrorRateHigh", "StockroomOrderLatencyP95High"):
        expr = _rule(rules, name)["expr"]
        aggregations = re.findall(r"\bby\s*\(([^)]*)\)", expr)
        assert aggregations, name
        for aggregation in aggregations:
            labels = {label.strip() for label in aggregation.split(",")}
            assert {"service_version", "deployment_environment"} <= labels, name
    # The invariant rule has no aggregation, so it keeps every metric label.
    assert not re.search(r"\b(?:by|without)\b", _rule(rules, "InventoryInvariantViolation")["expr"])


def test_dashboard_url_matches_the_provisioned_dashboard(
    rules: list[dict[str, Any]], dashboard: dict[str, Any]
) -> None:
    uid = dashboard["uid"]
    assert uid == "stockroom-order-journey"
    for rule in rules:
        url = rule["labels"]["dashboard_url"]
        parsed = urlsplit(url)
        assert parsed.scheme == "http"
        assert parsed.hostname == "localhost"
        assert parsed.port == 3000
        assert parsed.username is None and parsed.password is None
        assert parsed.path == f"/d/{uid}", rule["alert"]


def test_rendered_examples_expand_to_five_non_empty_attributes(
    rules: list[dict[str, Any]], dashboard: dict[str, Any]
) -> None:
    sample_labels = {
        "service_name": "stockroom",
        "service_version": "4bf92f3577b34da6a3ce929d0e0e4736",
        "deployment_environment": "development",
    }
    for rule in rules:
        rendered = {
            attribute: _render(rule["labels"][attribute], sample_labels) for attribute in ATTRIBUTES
        }
        for attribute, value in rendered.items():
            assert value.strip(), (rule["alert"], attribute)
            assert "{{" not in value, (rule["alert"], attribute)
        assert rendered["service"] == "stockroom"
        assert rendered["environment"] == "development"
        assert rendered["version"] == sample_labels["service_version"]
        assert rendered["owner"] == OWNER_PLACEHOLDER
        assert f"/d/{dashboard['uid']}" in rendered["dashboard_url"]


# ---------------------------------------------------------------------------
# AC3: one runbook per alert, with the same name and query
# ---------------------------------------------------------------------------


def test_each_alert_has_exactly_one_runbook(rules: list[dict[str, Any]]) -> None:
    on_disk = {path.name for path in RUNBOOKS.glob("*.md")}
    assert on_disk == set(RUNBOOK_FILES.values())
    for rule in rules:
        text = _runbook(rule["alert"])
        assert f"# {rule['alert']}" in text
        assert "## User impact" in text


def test_runbook_url_resolves_to_that_runbook(rules: list[dict[str, Any]]) -> None:
    for rule in rules:
        url = rule["annotations"]["runbook_url"]
        assert not urlsplit(url).scheme, "the runbook path stays repo-relative"
        assert not urlsplit(url).netloc
        assert (ROOT / url).resolve() == (RUNBOOKS / RUNBOOK_FILES[rule["alert"]]).resolve()


def test_runbook_quotes_the_exact_query_and_states_the_threshold(
    rules: list[dict[str, Any]],
) -> None:
    for rule in rules:
        text = _normalised(_runbook(rule["alert"]))
        assert _normalised(rule["expr"]) in text, rule["alert"]
        assert THRESHOLDS[rule["alert"]] in text, rule["alert"]
        assert "## Threshold" in text, rule["alert"]


def test_runbook_has_three_read_only_checks_and_local_links(
    rules: list[dict[str, Any]],
) -> None:
    for rule in rules:
        text = _runbook(rule["alert"])
        section = re.search(r"## First three checks.*?(?=\n## )", text, flags=re.DOTALL)
        assert section is not None, rule["alert"]
        blocks = re.findall(r"```bash\n(.*?)```", section.group(0), flags=re.DOTALL)
        assert len(blocks) == 3, rule["alert"]
        for block in blocks:
            assert "curl -s" in block, (rule["alert"], block.strip())
        assert "localhost:3000" in text, rule["alert"]
        assert "tempo" in text.lower(), rule["alert"]
        assert "## Recovery signal" in text, rule["alert"]


def test_runbook_links_the_autonomy_and_escalation_boundary(
    rules: list[dict[str, Any]],
) -> None:
    for rule in rules:
        text = _runbook(rule["alert"])
        assert "_docs/process.md" in text
        assert "§2" in text and "§10" in text
        assert ".agents/skills/investigate-alert/SKILL.md" in text


# ---------------------------------------------------------------------------
# AC4: promtool on the pinned image, and the local Prometheus loads the file
# ---------------------------------------------------------------------------


def test_check_alerts_target_uses_the_pinned_prometheus_image() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    target = re.search(r"^check-alerts:\n((?:\t.*\n)+)", text, flags=re.MULTILINE)
    assert target is not None
    body = target.group(1)
    assert "promtool" in body
    assert "check rules" in body
    assert PROMETHEUS_IMAGE in body
    phony = next(line for line in text.splitlines() if line.startswith(".PHONY:"))
    assert "check-alerts" in phony.split()


def test_prometheus_loads_the_rules_file_and_compose_mounts_it_read_only() -> None:
    config = yaml.safe_load(PROMETHEUS_CONFIG.read_text(encoding="utf-8"))
    assert config["rule_files"] == ["/etc/prometheus/alerts.yaml"]

    overlay = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    volumes = overlay["services"]["prometheus"]["volumes"]
    assert "./observability/alerts.yaml:/etc/prometheus/alerts.yaml:ro" in volumes


# ---------------------------------------------------------------------------
# AC7: no PII or secret anywhere in the rules or runbooks
# ---------------------------------------------------------------------------

SENSITIVE_PATTERNS = (
    re.compile(r"customer_ref"),
    re.compile(r"Basic(?:\s|%20)[A-Za-z0-9+/]{8,}={0,2}"),
    re.compile(r"\bglsa_[A-Za-z0-9]{8,}"),
    re.compile(r"\bglc_[A-Za-z0-9]{8,}"),
    re.compile(r"postgres(?:ql)?(?:\+psycopg)?://[^\s\"']+:[^\s\"']+@"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+\S+"),
    re.compile(r"(?i)\b(?:token|password|secret|api[_-]?key)\s*[:=]\s*\S{8,}"),
)


def test_no_pii_or_secret_in_rules_or_runbooks() -> None:
    files = [ALERTS, *(RUNBOOKS / name for name in RUNBOOK_FILES.values())]
    for path in files:
        text = path.read_text(encoding="utf-8")
        for pattern in SENSITIVE_PATTERNS:
            match = pattern.search(text)
            assert match is None, f"{path.relative_to(ROOT)}: {match.group(0)!r}"


def test_rule_urls_are_the_plain_local_grafana_base(
    rules: list[dict[str, Any]],
) -> None:
    for rule in rules:
        values = list(rule["labels"].values()) + list(rule["annotations"].values())
        for value in values:
            for url in re.findall(r"https?://[^\s\"'<>)]+", value):
                parsed = urlsplit(url)
                assert parsed.username is None and parsed.password is None, (rule["alert"], url)
                assert parsed.scheme == "http", (rule["alert"], url)
                assert parsed.hostname == "localhost" and parsed.port == 3000, (rule["alert"], url)
                assert "token" not in parsed.query.lower(), (rule["alert"], url)
