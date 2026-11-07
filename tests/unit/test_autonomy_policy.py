"""The autonomy policy is explicit, total and testable (T7.2, issue #62).

Every row of the issue's decision matrix is fed through the real policy file,
so the test fails if a rule is deleted, weakened or reordered. The evaluator is
pure: no clock, no environment, no filesystem.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ONCALL_DIR = ROOT / "on-call-engineer"
if str(ONCALL_DIR) not in sys.path:
    sys.path.insert(0, str(ONCALL_DIR))

import policy  # noqa: E402

POLICY_PATH = ONCALL_DIR / "autonomy-policy.yaml"

# The issue's matrix, one row per action shape. Each entry is
# ``(action, context, expected decision, expected rule id)``.
MATRIX: tuple[tuple[str, dict[str, Any], str, str], ...] = (
    # Read the packet, the repo and the allowlisted local endpoints.
    ("read.packet", {}, "allow", "read-packet"),
    ("read.repo", {"path": "backend/api/orders.py"}, "allow", "read-repo"),
    ("read.local_endpoint", {"host": "localhost"}, "allow", "read-local-endpoint"),
    ("read.local_endpoint", {"host": "127.0.0.1"}, "allow", "read-local-endpoint"),
    ("read.local_endpoint", {"host": "prometheus.example.com"}, "deny", "read-remote-endpoint"),
    # Run tests; start, stop or rebuild the local named Compose stack.
    ("run.tests", {}, "allow", "run-tests"),
    ("compose.start", {"host": "localhost"}, "allow", "compose-start"),
    ("compose.stop", {"host": "localhost"}, "allow", "compose-stop"),
    ("compose.rebuild", {"host": "localhost"}, "allow", "compose-rebuild"),
    ("compose.start", {"host": "db.example.com"}, "deny", "compose-remote"),
    ("compose.stop", {"host": "db.example.com"}, "deny", "compose-remote-stop"),
    ("compose.rebuild", {"host": "db.example.com"}, "deny", "compose-remote-rebuild"),
    # Worktree, branch, commit, push a non-main branch, open a PR to the base.
    ("git.worktree.create", {}, "allow", "worktree-create"),
    ("git.branch.create", {"branch": "oncall/example-1"}, "allow", "branch-create"),
    ("git.commit", {"branch": "oncall/example-1"}, "allow", "commit"),
    ("git.push", {"branch": "oncall/example-1", "force": False}, "allow", "push-feature"),
    ("pr.create", {"base_matches_packet": True}, "allow", "pr-create"),
    # Main/master pushes, force-pushes, merges, deleting a foreign branch.
    ("git.push", {"branch": "main", "force": False}, "deny", "push-main"),
    ("git.push", {"branch": "master", "force": False}, "deny", "push-main"),
    ("git.push", {"branch": "oncall/example-1", "force": True}, "deny", "push-force"),
    ("git.push", {"branch": "main", "force": True}, "deny", "push-main"),
    ("git.remote.change", {}, "deny", "remote-change"),
    ("pr.merge", {}, "deny", "pr-merge"),
    ("git.branch.delete", {"created_by_responder": False}, "deny", "branch-delete-foreign"),
    # Deploy, image push, ssh, any host other than the local stack.
    ("deploy", {}, "deny", "deploy"),
    ("docker.image.push", {}, "deny", "image-push"),
    ("ssh", {}, "deny", "ssh"),
    ("network.remote", {"host": "github.example.com"}, "deny", "network-remote"),
    # Secrets and SQL.
    ("secret.read", {}, "deny", "secret-read"),
    ("secret.print", {}, "deny", "secret-print"),
    ("secret.rotate", {}, "deny", "secret-rotate"),
    ("sql.execute", {}, "deny", "sql-execute"),
    # Contract, spec, migration, CI and observability edits.
    ("edit", {"path": "product-spec.md"}, "deny", "edit-protected"),
    ("edit", {"path": "openapi.yaml"}, "deny", "edit-protected"),
    ("edit", {"path": "backend/db/migrations/0001_initial.py"}, "deny", "edit-protected"),
    ("edit", {"path": ".github/workflows/ci.yml"}, "deny", "edit-protected"),
    ("edit", {"path": "compose.yaml"}, "deny", "edit-protected"),
    ("edit", {"path": "Dockerfile"}, "deny", "edit-protected"),
    ("edit", {"path": "observability/alerts.yaml"}, "deny", "edit-protected"),
    ("edit", {"path": "backend/api/orders.py"}, "allow", "edit-allowed"),
    # A fix that needs a protected edit is escalated, not forced.
    ("escalate", {"reason": "protected_path_required"}, "allow", "escalate-explicit"),
    # Unknown action, exhausted budget, PR base that is not the packet's base.
    ("does.not.exist", {}, "escalate", "default-escalate"),
    ("pr.create", {"base_matches_packet": False}, "escalate", "pr-base-mismatch"),
    (
        "git.push",
        {"branch": "oncall/example-1", "force": False, "budget_exhausted": True},
        "escalate",
        "budget-exhausted",
    ),
)


@pytest.fixture(scope="module")
def loaded() -> dict[str, Any]:
    return policy.load_policy(POLICY_PATH)


def test_policy_file_is_versioned_and_defaults_to_escalate(loaded: dict[str, Any]) -> None:
    assert loaded["version"]
    assert loaded["default"] == "escalate"
    assert loaded["precedence"]
    assert loaded["budget"] == {"seconds": 600, "on_exceed": "escalate"}


def test_tools_list_names_the_required_binaries(loaded: dict[str, Any]) -> None:
    required = {"git", "gh", "make", "docker", "curl", "python3", "uv", "sh"}
    assert required <= set(loaded["tools"])
    assert len(loaded["tools"]) == len(set(loaded["tools"]))


def test_every_rule_names_itself_and_its_decision(loaded: dict[str, Any]) -> None:
    for rule in loaded["rules"]:
        assert rule["id"]
        assert rule["action"]
        assert rule["decision"] in policy.DECISIONS
        assert rule["reason"].strip()
    ids = [rule["id"] for rule in loaded["rules"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    ("action", "context", "expected", "rule_id"),
    MATRIX,
    ids=[f"{row[0]}-{row[2]}-{row[3]}" for row in MATRIX],
)
def test_matrix_row(
    loaded: dict[str, Any],
    action: str,
    context: dict[str, Any],
    expected: str,
    rule_id: str,
) -> None:
    decision = policy.decide(action, context, loaded)
    assert decision.decision == expected
    assert decision.rule_id == rule_id
    assert decision.reason.strip()
    assert decision.policy_version == loaded["version"]


def test_the_matrix_covers_every_rule(loaded: dict[str, Any]) -> None:
    """Every rule a decision can name is reachable from the matrix."""
    exercised = {row[3] for row in MATRIX}
    for rule in loaded["rules"]:
        assert rule["id"] in exercised, f"rule {rule['id']} has no matrix row"


def test_explicit_deny_beats_escalate_beats_allow() -> None:
    overlapping = {
        "version": "test",
        "default": "escalate",
        "precedence": ["deny > escalate > allow"],
        "budget": {"seconds": 600, "on_exceed": "escalate"},
        "tools": ["git"],
        "rules": [
            {"id": "a-allow", "action": "x", "decision": "allow", "reason": "r"},
            {"id": "b-escalate", "action": "x", "decision": "escalate", "reason": "r"},
            {"id": "c-deny", "action": "x", "decision": "deny", "reason": "r"},
        ],
    }
    decided = policy.decide("x", {}, overlapping)
    assert decided.decision == "deny"
    assert decided.rule_id == "c-deny"

    del overlapping["rules"][2]
    decided = policy.decide("x", {}, overlapping)
    assert decided.decision == "escalate"
    assert decided.rule_id == "b-escalate"


def test_no_match_falls_back_to_the_default_rule(loaded: dict[str, Any]) -> None:
    decision = policy.decide("totally.unknown", {"anything": 1}, loaded)
    assert decision.decision == loaded["default"] == "escalate"
    assert decision.rule_id == policy.DEFAULT_RULE_ID


def test_missing_context_never_slips_past_a_guard(loaded: dict[str, Any]) -> None:
    """An omitted field is not a wildcard: the guard does not match, so it escalates."""
    decision = policy.decide("git.push", {}, loaded)
    assert decision.decision == "escalate"
    assert decision.rule_id == "default-escalate"


def test_budget_exhaustion_escalates_a_would_be_allow(loaded: dict[str, Any]) -> None:
    decision = policy.decide(
        "git.push",
        {"branch": "oncall/example-1", "force": False, "budget_exhausted": True},
        loaded,
    )
    assert decision.decision == "escalate"
    assert decision.rule_id == "budget-exhausted"


def test_budget_exhaustion_does_not_soften_a_deny(loaded: dict[str, Any]) -> None:
    decision = policy.decide(
        "git.push", {"branch": "main", "force": False, "budget_exhausted": True}, loaded
    )
    assert decision.decision == "deny"
    assert decision.rule_id == "push-main"


def test_decide_is_pure_and_does_not_mutate_its_inputs(loaded: dict[str, Any]) -> None:
    policy_before = copy.deepcopy(loaded)
    context = {"branch": "oncall/example-1", "force": False}
    context_before = dict(context)
    first = policy.decide("git.push", context, loaded)
    second = policy.decide("git.push", context, loaded)
    assert first == second
    assert loaded == policy_before
    assert context == context_before


def test_decision_serialises_to_the_fields_the_response_records(loaded: dict[str, Any]) -> None:
    decision = policy.decide("git.push", {"branch": "main", "force": False}, loaded)
    record = decision.as_dict()
    assert set(record) == {"action", "decision", "rule_id", "reason"}
    assert json.loads(json.dumps(record)) == record


def test_policy_sha256_matches_the_file_bytes() -> None:
    expected = hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()
    assert policy.policy_sha256(POLICY_PATH) == expected
    assert len(expected) == 64


@pytest.mark.parametrize(
    "broken",
    [
        {"rules": []},
        {"default": "maybe"},
        {"budget": {"seconds": 600}},
        {"rules": [{"id": "a", "action": "x", "decision": "allow"}]},
        {"rules": [{"id": "a", "action": "x", "decision": "allow", "reason": "r", "oops": 1}]},
        {"rules": [{"id": "a", "action": "x", "decision": "allow", "reason": "r"}] * 2},
    ],
)
def test_invalid_policies_are_rejected(loaded: dict[str, Any], broken: dict[str, Any]) -> None:
    document = copy.deepcopy(loaded)
    document.update(broken)
    with pytest.raises(policy.PolicyError):
        policy.validate_policy(document)


def test_policy_is_valid_yaml_and_a_mapping() -> None:
    document = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
