"""The alert poller: one bounded loop, incident identity and de-duplication (#61).

File-shape and behaviour tests. Every test injects the clock, the sleep and an
``httpx.MockTransport`` standing in for Prometheus, Loki and the app, and points
the state and evidence directories at a temporary directory. Nothing here waits
for an interval, starts a container or touches the network.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
ONCALL_DIR = ROOT / "on-call-engineer"
if str(ONCALL_DIR) not in sys.path:
    sys.path.insert(0, str(ONCALL_DIR))

import packet  # noqa: E402
import poll_alerts  # noqa: E402
from config import Config, ConfigError  # noqa: E402
from state import StateStore  # noqa: E402

FIXED_NOW = 1_800_000_000

BASE_LABELS = {
    "alertname": "StockroomOrderErrorRateHigh",
    "severity": "critical",
    "service": "stockroom",
    "environment": "development",
    "version": "abc1234def",
    "owner": "stockroom-on-call",
    "dashboard_url": "http://localhost:3000/d/stockroom-order-journey",
    # Labels the rule does not set: the packet must drop them, the identity must not care.
    "instance": "otel-collector:8889",
    "job": "otel-collector",
}

BASE_ANNOTATIONS = {
    "summary": "Order journey is returning 5xx above 5%",
    "description": "1 of 1 order-journey requests failed.",
    "runbook_url": "_docs/runbooks/stockroom-order-error-rate-high.md",
}

RULE = {
    "name": "StockroomOrderErrorRateHigh",
    "query": "(sum(rate(stockroom_http_request_duration_seconds_count[5m]))) > 0.05",
    "for": "1m",
    "type": "alerting",
    "state": "firing",
    "labels": {},
    "annotations": {},
}

TRACE_A = "a" * 32
TRACE_B = "b" * 32


class Clock:
    """An injected clock; one call per poll returns the current value."""

    def __init__(self, value: int = FIXED_NOW) -> None:
        self.value = float(value)

    def __call__(self) -> float:
        return self.value

    def tick(self, seconds: int = 60) -> None:
        self.value += seconds


class FakeApi:
    """MockTransport for Prometheus, Loki and the app, with a request log."""

    def __init__(
        self,
        *,
        alerts: list[dict[str, Any]] | None = None,
        rules: list[dict[str, Any]] | None = None,
        prometheus_result: Any = None,
        loki: dict[str, Any] | None = None,
        app: dict[str, tuple[int, Any]] | None = None,
    ) -> None:
        self.alerts = [make_alert()] if alerts is None else alerts
        self.rules = [RULE] if rules is None else rules
        self.prometheus_result = (
            {"resultType": "vector", "result": [{"metric": {}, "value": [FIXED_NOW, "0.42"]}]}
            if prometheus_result is None
            else prometheus_result
        )
        self.loki = default_loki() if loki is None else loki
        self.app = default_app() if app is None else app
        self.failure: str | None = None
        self.failure_kind = "connect"
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=5.0)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if self.failure and self._fails(path):
            if self.failure_kind == "connect":
                raise httpx.ConnectError("failed http://operator:secret@upstream.invalid")
            return httpx.Response(503, json={"error": "unavailable"})

        if path == "/api/v1/alerts":
            return _json({"status": "success", "data": {"alerts": self.alerts}})
        if path == "/api/v1/rules":
            return _json(
                {"status": "success", "data": {"groups": [{"name": "g", "rules": self.rules}]}}
            )
        if path == "/api/v1/query":
            return _json({"status": "success", "data": self.prometheus_result})
        if path == "/loki/api/v1/query_range":
            return _json(self.loki)
        if path in self.app:
            status, body = self.app[path]
            return _json(body, status=status)
        return _json({"error": "not found"}, status=404)

    def _fails(self, path: str) -> bool:
        return {
            "alerts": path == "/api/v1/alerts",
            "rules": path == "/api/v1/rules",
            "query": path == "/api/v1/query",
            "loki": path == "/loki/api/v1/query_range",
            "app": path in self.app,
        }.get(self.failure or "", False)


def _json(body: Any, *, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def make_alert(
    *,
    labels: dict[str, Any] | None = None,
    annotations: dict[str, Any] | None = None,
    state: str = "firing",
) -> dict[str, Any]:
    merged = dict(BASE_LABELS)
    for key, value in (labels or {}).items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return {
        "labels": merged,
        "annotations": dict(BASE_ANNOTATIONS) if annotations is None else annotations,
        "state": state,
        "activeAt": "2026-11-06T19:22:21Z",
        "value": "1",
    }


def default_loki() -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"container": "stockroom-app-1"},
                    "values": [
                        [f"{FIXED_NOW}000000000", json.dumps(_log_line(TRACE_A, 500))],
                        [f"{FIXED_NOW - 1}000000000", json.dumps(_log_line(TRACE_B, 500))],
                    ],
                }
            ],
        },
    }


def _log_line(trace_id: str, status_code: int) -> dict[str, Any]:
    return {
        "timestamp": "2026-11-07T09:59:59.000Z",
        "level": "ERROR",
        "message": f"POST /api/orders HTTP/1.1 {status_code}",
        "method": "POST",
        "route": "/api/orders",
        "status_code": status_code,
        "duration_ms": 3.2,
        "trace_id": trace_id,
    }


def default_app() -> dict[str, tuple[int, Any]]:
    return {
        "/healthz": (200, {"status": "ok", "db": "ok"}),
        "/api/version": (
            200,
            {
                "version": "0.1.0",
                "commit": "abc1234def",
                "build_time": "2026-11-07T00:00:00Z",
                "environment": "development",
            },
        ),
        "/api/invariants": (200, {"ok": True, "violations": []}),
    }


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        prometheus_url="http://127.0.0.1:9090",
        loki_url="http://127.0.0.1:3100",
        app_url="http://127.0.0.1:8000",
        poll_interval_seconds=60,
        lookback_minutes=15,
        log_samples=20,
        trace_samples=3,
        http_timeout_seconds=5.0,
        evidence_dir=tmp_path / "evidence",
        state_dir=tmp_path / "state",
        resolve_grace_polls=2,
        base_ref="main",
        base_commit="deadbeefcafe",
        image_reference="stockroom-app:local",
    )


def packets(config: Config) -> list[Path]:
    return sorted(config.evidence_dir.glob("*.json"))


def events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and "event" in payload:
            parsed.append(payload)
    return parsed


def run(config: Config, fake: FakeApi, clock: Clock) -> int:
    return poll_alerts.run_once(config, clock=clock, client=fake.client())


def test_incident_id_is_slug_fingerprint_and_first_seen() -> None:
    labels = make_alert()["labels"]
    fingerprint = packet.fingerprint(labels)
    incident = packet.incident_id(labels, FIXED_NOW)

    assert incident == f"stockroom-order-error-rate-high-{fingerprint[:12]}-{FIXED_NOW}"
    assert len(fingerprint) == 64
    assert set(fingerprint) <= set("0123456789abcdef")
    assert packet.canonical_labels({"b": "2", "a": "1"}) == '{"a":"1","b":"2"}'


def test_first_firing_writes_one_packet_and_later_polls_write_none(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeApi()
    with caplog.at_level(logging.DEBUG, logger="stockroom.oncall"):
        assert run(config, fake, Clock()) == 0

    written = packets(config)
    assert len(written) == 1
    first_bytes = written[0].read_bytes()
    document = json.loads(first_bytes)
    expected_generated_at = datetime.fromtimestamp(FIXED_NOW, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert document["incident_id"] == written[0].stem
    assert document["generated_at"] == expected_generated_at
    assert first_bytes.endswith(b"}\n") and not first_bytes.endswith(b"\n\n")

    with caplog.at_level(logging.DEBUG, logger="stockroom.oncall"):
        assert run(config, fake, Clock()) == 0

    assert packets(config) == written
    assert written[0].read_bytes() == first_bytes


def test_resolve_after_grace_and_refire_gets_a_new_incident(config: Config) -> None:
    clock = Clock()
    fake = FakeApi()
    assert run(config, fake, clock) == 0
    first_id = packets(config)[0].stem

    clock.tick()
    fake.alerts = []
    assert run(config, fake, clock) == 0  # one missing poll: still inside the grace
    assert len(packets(config)) == 1

    clock.tick()
    assert run(config, fake, clock) == 0  # second missing poll: resolved
    assert len(packets(config)) == 1

    clock.tick()
    fake.alerts = [make_alert()]
    assert run(config, fake, clock) == 0

    written = packets(config)
    assert len(written) == 2
    second_id = next(path.stem for path in written if path.stem != first_id)
    assert second_id.endswith(f"-{int(clock.value)}")
    assert second_id != first_id


def test_transient_missing_poll_inside_grace_does_not_create_a_new_incident(
    config: Config,
) -> None:
    clock = Clock()
    fake = FakeApi()
    assert run(config, fake, clock) == 0
    first_id = packets(config)[0].stem

    clock.tick()
    fake.alerts = []
    assert run(config, fake, clock) == 0
    assert len(packets(config)) == 1

    clock.tick()
    fake.alerts = [make_alert()]
    assert run(config, fake, clock) == 0
    assert len(packets(config)) == 1

    clock.tick()
    fake.alerts = []
    assert run(config, fake, clock) == 0
    assert len(packets(config)) == 1

    clock.tick()
    assert run(config, fake, clock) == 0
    assert len(packets(config)) == 1
    assert packets(config)[0].stem == first_id


def test_same_name_with_different_labels_is_separate_incidents(config: Config) -> None:
    alerts = [
        make_alert(),
        make_alert(labels={"severity": "warning"}),
        make_alert(labels={"environment": "staging"}),
        make_alert(labels={"version": "deadbeefcafe"}),
    ]
    fake = FakeApi(alerts=alerts)

    assert run(config, fake, Clock()) == 0

    written = packets(config)
    assert len(written) == 4
    assert len({path.stem for path in written}) == 4


def test_restart_against_same_state_dir_does_not_duplicate(config: Config) -> None:
    fake = FakeApi()
    clock = Clock()
    assert run(config, fake, clock) == 0
    written = packets(config)
    state_before = (config.state_dir / "state.json").read_bytes()

    # A new process would build a new StateStore and load the same file.
    assert run(config, fake, clock) == 0

    assert packets(config) == written
    assert (config.state_dir / "state.json").read_bytes() == state_before


def test_corrupt_state_is_reported_and_treated_as_empty(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    config.state_dir.mkdir(parents=True)
    (config.state_dir / "state.json").write_text("{ not json", encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger="stockroom.oncall"):
        assert run(config, FakeApi(), Clock()) == 0

    assert len(packets(config)) == 1
    assert any(event["event"] == "state_corrupt" for event in events(caplog))
    json.loads((config.state_dir / "state.json").read_text(encoding="utf-8"))


def test_missing_required_label_writes_no_packet_and_names_label_and_fingerprint(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    alert = make_alert(labels={"owner": None})
    fake = FakeApi(alerts=[alert])

    with caplog.at_level(logging.DEBUG, logger="stockroom.oncall"):
        assert run(config, fake, Clock()) == 0

    assert packets(config) == []
    reported = [event for event in events(caplog) if event["event"] == "missing_required_label"]
    assert reported
    assert reported[0]["missing_label"] == "owner"
    assert reported[0]["fingerprint"] == packet.fingerprint(alert["labels"])


def test_missing_required_label_does_not_block_the_next_alert(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    broken = make_alert(labels={"owner": None})
    healthy = make_alert(labels={"version": "deadbeefcafe"})
    fake = FakeApi(alerts=[broken, healthy])

    with caplog.at_level(logging.DEBUG, logger="stockroom.oncall"):
        assert run(config, fake, Clock()) == 0

    written = packets(config)
    assert len(written) == 1
    assert (
        json.loads(written[0].read_text(encoding="utf-8"))["service"]["deployed_version"]
        == "deadbeefcafe"
    )
    assert any(event["event"] == "missing_required_label" for event in events(caplog))


@pytest.mark.parametrize("failure_kind", ["connect", "status"])
def test_prometheus_failure_exits_non_zero_and_leaves_state_untouched(
    config: Config, failure_kind: str
) -> None:
    clock = Clock()
    fake = FakeApi()
    assert run(config, fake, clock) == 0
    state_before = (config.state_dir / "state.json").read_bytes()
    written = packets(config)

    fake.failure = "alerts"
    fake.failure_kind = failure_kind

    assert run(config, fake, clock) == 2
    assert (config.state_dir / "state.json").read_bytes() == state_before
    assert packets(config) == written


def test_prometheus_failure_on_the_first_poll_writes_no_state(config: Config) -> None:
    fake = FakeApi()
    fake.failure = "alerts"

    assert run(config, fake, Clock()) == 2

    assert not (config.state_dir / "state.json").exists()
    assert packets(config) == []


def test_second_poller_exits_zero_without_writing_a_duplicate(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    store = StateStore(config.state_dir)
    with store.locked() as acquired:
        assert acquired
        with caplog.at_level(logging.DEBUG, logger="stockroom.oncall"):
            assert run(config, FakeApi(), Clock()) == 0

    assert packets(config) == []
    assert "another poller" in caplog.text


def test_loop_waits_the_configured_interval_after_the_poll(config: Config) -> None:
    fake = FakeApi()
    sleeps: list[tuple[int, int]] = []

    def sleep(seconds: int) -> None:
        sleeps.append((seconds, len(fake.requests)))
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        poll_alerts.run_loop(config, clock=Clock(), client=fake.client(), sleep=sleep)

    assert len(sleeps) == 1
    interval, requests_at_sleep = sleeps[0]
    assert interval == 60
    assert requests_at_sleep >= 3  # alerts, rules and the observations ran first


def test_state_flush_leaves_no_temporary_files(config: Config) -> None:
    assert run(config, FakeApi(), Clock()) == 0

    names = {path.name for path in config.state_dir.iterdir()}
    assert names == {"state.json", "poller.lock"}
    assert len(packets(config)) == 1


def test_config_defaults_and_local_only_guard(tmp_path: Path) -> None:
    environment = {
        "ONCALL_EVIDENCE_DIR": str(tmp_path / "evidence"),
        "ONCALL_STATE_DIR": str(tmp_path / "state"),
        "ONCALL_BASE_COMMIT": "deadbeefcafe",
    }
    config = Config.from_env(environment)

    assert config.prometheus_url == "http://localhost:9090"
    assert config.loki_url == "http://localhost:3100"
    assert config.app_url == "http://localhost:8000"
    assert config.poll_interval_seconds == 60
    assert config.lookback_minutes == 15
    assert config.log_samples == 20
    assert config.trace_samples == 3
    assert config.http_timeout_seconds == 5.0
    assert config.evidence_dir == tmp_path / "evidence"
    assert config.state_dir == tmp_path / "state"
    assert config.resolve_grace_polls == 2
    assert config.base_ref == "main"
    assert config.base_commit == "deadbeefcafe"
    assert config.image_reference == "stockroom-app:local"

    with pytest.raises(ConfigError):
        Config.from_env({**environment, "PROMETHEUS_URL": "http://prometheus.example.com:9090"})
    with pytest.raises(ConfigError):
        Config.from_env({**environment, "LOKI_URL": "http://operator:secret@localhost:3100"})
    with pytest.raises(ConfigError):
        Config.from_env({**environment, "ONCALL_POLL_INTERVAL_SECONDS": "soon"})


def test_makefile_forwards_args_to_the_poller_script() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "oncall-poll:" in makefile
    assert "uv run python on-call-engineer/poll_alerts.py $(ARGS)" in makefile
    assert "oncall-poll" in next(
        line for line in makefile.splitlines() if line.startswith(".PHONY:")
    )


def test_env_example_documents_every_setting() -> None:
    expected = {
        "PROMETHEUS_URL",
        "LOKI_URL",
        "STOCKROOM_APP_URL",
        "ONCALL_POLL_INTERVAL_SECONDS",
        "ONCALL_LOOKBACK_MINUTES",
        "ONCALL_LOG_SAMPLES",
        "ONCALL_TRACE_SAMPLES",
        "ONCALL_HTTP_TIMEOUT_SECONDS",
        "ONCALL_EVIDENCE_DIR",
        "ONCALL_STATE_DIR",
        "ONCALL_RESOLVE_GRACE_POLLS",
        "ONCALL_BASE_REF",
        "ONCALL_BASE_COMMIT",
    }
    assigned = {
        line.split("=", 1)[0].strip()
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }

    assert expected <= assigned


def test_state_directory_is_gitignored() -> None:
    assert "on-call-engineer/.state/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
