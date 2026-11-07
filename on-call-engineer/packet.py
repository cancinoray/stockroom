"""The evidence packet contract (T7.1, issue #61) — frozen for T7.2.

The top-level keys, the nested shapes and the allowlists below are the packet
contract. T7.2 reads this file; changing a key after merge is a new issue.

Only allowlisted values enter the packet: the alert labels and annotations, the
log fields, the app result fields. Everything else the upstream returns is
dropped, so a payload cannot smuggle a credential, customer data or a query
fragment into the packet.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

TOP_LEVEL_KEYS = (
    "incident_id",
    "generated_at",
    "alert",
    "service",
    "deploy",
    "repo",
    "observations",
    "limits",
)

ALERT_NAME_LABEL = "alertname"

# Alert labels that may be copied. `instance`/`job` and anything else Prometheus
# or a future rule adds are dropped.
ALLOWED_ALERT_LABELS = (
    "alertname",
    "severity",
    "service",
    "environment",
    "version",
    "owner",
    "dashboard_url",
)

# The labels a packet cannot be built without. `alertname` names the alert and
# is checked alongside these by the poller.
REQUIRED_ALERT_LABELS = ("service", "environment", "version", "owner", "dashboard_url")

ALLOWED_ANNOTATIONS = ("summary", "description", "runbook_url")

# ``json.dumps`` with sorted keys and no insignificant whitespace: the exact
# bytes the incident id hashes.
_CANONICAL_SEPARATORS = (",", ":")


class MissingRequiredLabelError(ValueError):
    """An alert without the labels an evidence packet needs."""

    def __init__(self, label: str, fingerprint: str, alert_name: str | None) -> None:
        super().__init__(f"alert {alert_name!r} is missing required label {label!r}")
        self.label = label
        self.fingerprint = fingerprint
        self.alert_name = alert_name


def canonical_labels(labels: dict[str, Any]) -> str:
    """Stable JSON for a label set: sorted keys, no whitespace."""
    normalised = {str(key): str(value) for key, value in labels.items()}
    return json.dumps(normalised, sort_keys=True, separators=_CANONICAL_SEPARATORS)


def fingerprint(labels: dict[str, Any]) -> str:
    """SHA-256 of the canonical label set, as 64 lowercase hex characters."""
    return hashlib.sha256(canonical_labels(labels).encode("utf-8")).hexdigest()


def slugify(name: str) -> str:
    """``StockroomOrderErrorRateHigh`` -> ``stockroom-order-error-rate-high``."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", name)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", spaced).strip("-").lower()
    return slug or "alert"


def incident_id(labels: dict[str, Any], first_seen: int) -> str:
    """``<alert-slug>-<first 12 hex of sha256(labels)>-<first-seen epoch>``."""
    name = str(labels.get(ALERT_NAME_LABEL) or "")
    return f"{slugify(name)}-{fingerprint(labels)[:12]}-{int(first_seen)}"


def missing_required_label(labels: dict[str, Any]) -> str | None:
    """The first required label that is absent or blank, else ``None``."""
    for label in REQUIRED_ALERT_LABELS:
        if not str(labels.get(label) or "").strip():
            return label
    return None


def utc_timestamp(epoch: int) -> str:
    """UTC ISO-8601 seconds with a ``Z`` suffix, from an injected clock."""
    return datetime.fromtimestamp(int(epoch), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def rule_for(rule: dict[str, Any]) -> str | None:
    """The rule's ``for`` value.

    Prometheus's rules API returns the hold duration as ``duration`` seconds;
    the rule file calls it ``for``. Prefer a literal ``for`` when a source
    supplies one, otherwise render the seconds as a Prometheus duration.
    """
    declared = rule.get("for")
    if isinstance(declared, str) and declared.strip():
        return declared
    duration = rule.get("duration")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        return f"{int(duration)}s"
    return None


def build_packet(
    alert: dict[str, Any],
    rule: dict[str, Any] | None,
    observations: dict[str, Any],
    config: Any,
    now: int,
) -> dict[str, Any]:
    """Assemble one packet from an alert, its rule, the observations and config."""
    labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
    annotations = alert.get("annotations") if isinstance(alert.get("annotations"), dict) else {}
    name = str(labels.get(ALERT_NAME_LABEL) or "")
    rule = rule or {}

    return {
        "incident_id": incident_id(labels, now),
        "generated_at": utc_timestamp(now),
        "alert": {
            "name": name,
            "severity": labels.get("severity"),
            "state": alert.get("state"),
            "active_at": alert.get("activeAt"),
            "value": alert.get("value"),
            "labels": {key: labels[key] for key in ALLOWED_ALERT_LABELS if key in labels},
            "annotations": {
                key: annotations[key] for key in ALLOWED_ANNOTATIONS if key in annotations
            },
            "rule": {"expr": rule.get("query"), "for": rule_for(rule)},
        },
        "service": {
            "name": labels.get("service"),
            "environment": labels.get("environment"),
            "deployed_version": labels.get("version"),
            "owner": labels.get("owner"),
            "dashboard_url": labels.get("dashboard_url"),
            "runbook_url": annotations.get("runbook_url"),
        },
        "deploy": {
            "image_reference": config.image_reference,
            "version": labels.get("version"),
        },
        "repo": {
            "base_ref": config.base_ref,
            "base_commit": config.base_commit,
        },
        "observations": observations,
        "limits": {
            "lookback_minutes": config.lookback_minutes,
            "log_samples": config.log_samples,
            "trace_samples": config.trace_samples,
            "http_timeout_seconds": config.http_timeout_seconds,
            "resolve_grace_polls": config.resolve_grace_polls,
        },
    }


def render(document: dict[str, Any]) -> bytes:
    """The on-disk bytes: sorted keys, two-space indent, exactly one newline."""
    return (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
