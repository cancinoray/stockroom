"""The incident response schema and its rendered record (T7.2, issue #62).

One good fixture per action, the five rejections the issue names, and the
property that the Markdown is rendered from the validated object rather than
maintained beside it.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
ONCALL_DIR = ROOT / "on-call-engineer"
if str(ONCALL_DIR) not in sys.path:
    sys.path.insert(0, str(ONCALL_DIR))

import policy  # noqa: E402
import run_responder  # noqa: E402

SCHEMA_PATH = ONCALL_DIR / "response.schema.json"
INCIDENT_ID = "stockroom-order-error-rate-high-324f01034b2a-1794026992"
SHA = "a" * 64
PR_URL = "https://github.com/cancinoray/stockroom/pull/999"


def decision(action: str, outcome: str, rule_id: str) -> dict[str, str]:
    return {
        "action": action,
        "decision": outcome,
        "rule_id": rule_id,
        "reason": f"{rule_id} says so",
    }


def base_response(action: str) -> dict[str, Any]:
    return {
        "incident_id": INCIDENT_ID,
        "alert": {
            "name": "StockroomOrderErrorRateHigh",
            "severity": "critical",
            "environment": "development",
            "version": "0.1.0",
            "dashboard_url": "http://localhost:3000/d/stockroom-order-journey",
            "rule": {"expr": "sum(rate(stockroom_orders_failed_total[5m])) > 0.05", "for": "1m"},
        },
        "user_impact": "60 of 60 order requests (100%) returned 500 for 60s.",
        "evidence_inspected": ["evidence packet", "trace " + "a" * 32],
        "hypothesis": "The order route raises when the ledger write is retried.",
        "action": action,
        "changes": {
            "files": [],
            "test": None,
            "branch": None,
            "base_ref": None,
            "worktree": None,
            "pr_url": None,
        },
        "policy": {
            "version": "1",
            "sha256": SHA,
            "decisions": [decision("read.packet", "allow", "read-packet")],
        },
        "verification": {
            "status": "not_run",
            "checks": [],
            "observed_at": None,
        },
        "timing": {
            "started": "2026-11-07T14:00:00Z",
            "ended": "2026-11-07T14:00:42Z",
            "elapsed_seconds": 42.0,
            "budget_seconds": 600,
        },
        "detection_gap": "None: the alert fired one hold duration after the first failure.",
        "escalation": None,
        "review": {"status": "pending", "notes": "QA reviews the PR before merge."},
    }


def fix_response() -> dict[str, Any]:
    document = base_response("fix")
    document["changes"] = {
        "files": ["backend/api/orders.py"],
        "test": "tests/unit/test_orders_fix.py",
        "branch": f"oncall/{INCIDENT_ID}",
        "base_ref": "main",
        "worktree": f"worktrees/oncall-{INCIDENT_ID}",
        "pr_url": PR_URL,
    }
    document["policy"]["decisions"] = [
        decision("edit", "allow", "edit-allowed"),
        decision("run.tests", "allow", "run-tests"),
        decision("pr.create", "allow", "pr-create"),
    ]
    document["verification"] = {
        "status": "not_run",
        "checks": ["make test-unit", "make test-integration"],
        "observed_at": None,
    }
    return document


def no_action_response() -> dict[str, Any]:
    document = base_response("no_action")
    document["hypothesis"] = "The 5xx burst was a client retry storm; the app was healthy."
    document["verification"] = {
        "status": "verified",
        "checks": ["alert resolved without a change", "/api/invariants clean"],
        "observed_at": "2026-11-07T14:05:00Z",
    }
    return document


def escalate_response() -> dict[str, Any]:
    document = base_response("escalate")
    document["hypothesis"] = "The cache and the ledger disagree for three SKUs."
    document["escalation"] = {
        "decision_required": "Approve a ledger reconciliation script for SKU-1042..1044.",
        "context": "Domain rule 3 forbids hand-fixing a counter.",
    }
    return document


FIXTURES = [fix_response, no_action_response, escalate_response]


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_is_draft_2020_12_and_closed(schema: dict[str, Any]) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    Draft202012Validator.check_schema(schema)


def test_every_object_in_the_schema_is_closed(schema: dict[str, Any]) -> None:
    unclosed = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and node.get("additionalProperties") is not False:
                unclosed.append(path)
            for key, value in node.items():
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")

    walk(schema, "#")
    assert unclosed == []


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture.__name__)
def test_one_good_fixture_per_action_validates(schema: dict[str, Any], fixture: Any) -> None:
    document = fixture()
    assert run_responder.validate_response(document, schema) is document


def test_a_fix_without_a_pr_url_is_rejected() -> None:
    document = fix_response()
    document["changes"]["pr_url"] = None
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_a_fix_with_no_files_is_rejected() -> None:
    document = fix_response()
    document["changes"]["files"] = []
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_an_escalation_without_the_decision_required_is_rejected() -> None:
    document = escalate_response()
    document["escalation"] = {"context": "no decision named"}
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_an_escalation_with_an_empty_decision_required_is_rejected() -> None:
    document = escalate_response()
    document["escalation"]["decision_required"] = ""
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_an_unknown_action_is_rejected() -> None:
    document = base_response("fix")
    document["action"] = "deploy"
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_a_missing_top_level_field_is_rejected() -> None:
    document = fix_response()
    del document["detection_gap"]
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_an_extra_top_level_field_is_rejected() -> None:
    document = fix_response()
    document["notes"] = "not in the schema"
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_an_extra_nested_field_is_rejected() -> None:
    document = fix_response()
    document["alert"]["fingerprint"] = "b" * 64
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_a_policy_digest_that_is_not_a_sha256_is_rejected() -> None:
    document = fix_response()
    document["policy"]["sha256"] = "not-a-digest"
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_at_least_one_policy_decision_is_required() -> None:
    document = fix_response()
    document["policy"]["decisions"] = []
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_a_non_escalation_must_not_carry_an_escalation() -> None:
    document = fix_response()
    document["escalation"] = {"decision_required": "merge it"}
    with pytest.raises(run_responder.ResponseError):
        run_responder.validate_response(document)


def test_a_null_rule_is_rendered_as_null_fields() -> None:
    document = no_action_response()
    document["alert"]["rule"] = {"expr": None, "for": None}
    run_responder.validate_response(document)
    markdown = run_responder.render_markdown(document)
    assert "expr: (none recorded)" in markdown


def test_the_markdown_is_rendered_from_the_validated_object() -> None:
    document = fix_response()
    run_responder.validate_response(document)
    markdown = run_responder.render_markdown(document)

    for expected in (
        INCIDENT_ID,
        "StockroomOrderErrorRateHigh",
        "60 of 60 order requests",
        "backend/api/orders.py",
        "tests/unit/test_orders_fix.py",
        f"oncall/{INCIDENT_ID}",
        PR_URL,
        "edit-allowed",
        f"policy sha256 `{SHA}`",
        "not_run",
        "Detection gap",
    ):
        assert expected in markdown
    # The rendered record never invents a field the object does not have.
    assert "deploy" not in markdown.lower()


def test_rendering_is_deterministic() -> None:
    document = escalate_response()
    run_responder.validate_response(document)
    first = run_responder.render_markdown(document)
    second = run_responder.render_markdown(document)
    assert first == second
    assert first.endswith("\n")


def test_rendering_refuses_an_invalid_object() -> None:
    document = fix_response()
    document["changes"]["pr_url"] = None
    with pytest.raises(run_responder.ResponseError):
        run_responder.render_markdown(document)


def test_render_json_is_canonical_and_newline_terminated() -> None:
    document = fix_response()
    run_responder.validate_response(document)
    first = run_responder.render_json(document)
    second = run_responder.render_json(copy.deepcopy(document))
    assert first == second
    assert first.endswith(b"}\n")
    assert json.loads(first) == document


def test_policy_decisions_must_match_the_policy_file() -> None:
    document = fix_response()
    policy_document = policy.load_policy(ONCALL_DIR / "autonomy-policy.yaml")
    run_responder.check_policy_decisions(document, policy_document)

    document["policy"]["decisions"][0]["rule_id"] = "invented-rule"
    with pytest.raises(run_responder.ResponseError):
        run_responder.check_policy_decisions(document, policy_document)

    document = fix_response()
    document["policy"]["decisions"][0]["decision"] = "deny"
    with pytest.raises(run_responder.ResponseError):
        run_responder.check_policy_decisions(document, policy_document)


def test_policy_version_and_digest_must_match_the_file() -> None:
    document = fix_response()
    policy_path = ONCALL_DIR / "autonomy-policy.yaml"
    policy_document = policy.load_policy(policy_path)
    digest = policy.policy_sha256(policy_path)
    document["policy"]["sha256"] = digest

    run_responder.check_policy_identity(document, policy_document, digest)

    document["policy"]["version"] = "999"
    with pytest.raises(run_responder.ResponseError):
        run_responder.check_policy_identity(document, policy_document, digest)

    document["policy"]["version"] = str(policy_document["version"])
    document["policy"]["sha256"] = "b" * 64
    with pytest.raises(run_responder.ResponseError):
        run_responder.check_policy_identity(document, policy_document, digest)
