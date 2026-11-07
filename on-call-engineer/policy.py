"""The autonomy policy evaluator (T7.2, issue #62).

``decide(action, context, policy)`` is pure: it reads no clock, no environment
and no file, and it never mutates its arguments. The same three inputs always
produce the same :class:`Decision`, which names the rule that produced it.

The policy file (``autonomy-policy.yaml``) is the source of truth for what the
responder may do. This module only applies it:

* a rule matches when its ``action`` is the action (or ``"*"``) and every field
  in its ``when`` map matches the supplied context;
* among matching rules, an explicit ``deny`` beats ``escalate`` beats ``allow``;
* no matching rule means the policy ``default`` (``escalate``).

The bottom of the file is the operator-facing CLI. It is the only I/O here and
the responder uses it before a consequential action:

    python3 on-call-engineer/policy.py --action git.push \\
        --context-json '{"branch": "oncall/x", "force": false}'

Exit codes: ``0`` allow, ``1`` escalate, ``2`` deny or unusable input.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DECISIONS = ("allow", "deny", "escalate")
# Lower sorts first, which is exactly the documented precedence.
PRECEDENCE = {"deny": 0, "escalate": 1, "allow": 2}
DEFAULT_RULE_ID = "default-escalate"
ANY_ACTION = "*"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

REQUIRED_POLICY_KEYS = ("version", "default", "precedence", "budget", "tools", "rules")
REQUIRED_RULE_KEYS = ("id", "action", "decision", "reason")
RULE_KEYS = frozenset({*REQUIRED_RULE_KEYS, "when"})


class PolicyError(ValueError):
    """The policy document is not one this evaluator can apply."""


@dataclass(frozen=True, slots=True)
class Decision:
    """One evaluated action, attributed to the rule that decided it."""

    action: str
    decision: str
    rule_id: str
    reason: str
    policy_version: str

    def as_dict(self) -> dict[str, str]:
        """The fields the response's ``policy.decisions`` records."""
        return {
            "action": self.action,
            "decision": self.decision,
            "rule_id": self.rule_id,
            "reason": self.reason,
        }


def decide(action: str, context: Mapping[str, Any] | None, policy: Mapping[str, Any]) -> Decision:
    """Apply ``policy`` to one action. Pure: no I/O, no mutation."""
    validate_policy(policy)
    context_map = dict(context or {})
    matching = [
        rule
        for rule in policy["rules"]
        if _action_matches(rule["action"], action) and _when_matches(rule.get("when"), context_map)
    ]

    if not matching:
        return Decision(
            action=action,
            decision=policy["default"],
            rule_id=DEFAULT_RULE_ID,
            reason="no rule matched this action, so the policy default applies",
            policy_version=str(policy["version"]),
        )

    chosen = min(matching, key=lambda rule: PRECEDENCE[rule["decision"]])
    return Decision(
        action=action,
        decision=chosen["decision"],
        rule_id=chosen["id"],
        reason=chosen["reason"],
        policy_version=str(policy["version"]),
    )


def validate_policy(policy: Mapping[str, Any]) -> None:
    """Reject a policy that could make a decision ambiguous or unattributed."""
    if not isinstance(policy, Mapping):
        raise PolicyError("policy must be a mapping")

    for key in REQUIRED_POLICY_KEYS:
        if key not in policy:
            raise PolicyError(f"policy is missing {key!r}")

    if not isinstance(policy["version"], str) or not policy["version"].strip():
        raise PolicyError("policy version must be a non-empty string")

    if policy["default"] not in DECISIONS:
        raise PolicyError("policy default must be one of allow, deny, escalate")

    precedence = policy["precedence"]
    if (
        not isinstance(precedence, list)
        or not precedence
        or not all(isinstance(item, str) and item.strip() for item in precedence)
    ):
        raise PolicyError("precedence must be a non-empty list of strings")

    budget = policy["budget"]
    if not isinstance(budget, Mapping):
        raise PolicyError("budget must be a mapping")
    seconds = budget.get("seconds")
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
        raise PolicyError("budget.seconds must be a positive integer")
    if budget.get("on_exceed") not in DECISIONS:
        raise PolicyError("budget.on_exceed must be one of allow, deny, escalate")

    tools = policy["tools"]
    if not isinstance(tools, list) or not all(
        isinstance(tool, str) and tool.strip() for tool in tools
    ):
        raise PolicyError("tools must be a list of binary names")
    if len(tools) != len(set(tools)):
        raise PolicyError("tools must not repeat a binary")

    rules = policy["rules"]
    if not isinstance(rules, list) or not rules:
        raise PolicyError("rules must be a non-empty list")

    seen: set[str] = set()
    for rule in rules:
        _validate_rule(rule, seen)


def _validate_rule(rule: Any, seen: set[str]) -> None:
    if not isinstance(rule, Mapping):
        raise PolicyError("every rule must be a mapping")
    extra = set(rule) - RULE_KEYS
    if extra:
        raise PolicyError(f"rule has unknown keys: {sorted(extra)}")
    for key in REQUIRED_RULE_KEYS:
        if key not in rule:
            raise PolicyError(f"rule is missing {key!r}")
    if not isinstance(rule["id"], str) or not rule["id"].strip():
        raise PolicyError("rule id must be a non-empty string")
    if rule["id"] in seen:
        raise PolicyError(f"duplicate rule id {rule['id']!r}")
    seen.add(rule["id"])
    if not isinstance(rule["action"], str) or not rule["action"].strip():
        raise PolicyError(f"rule {rule['id']!r} has no action")
    if rule["decision"] not in DECISIONS:
        raise PolicyError(f"rule {rule['id']!r} has an unknown decision")
    if not isinstance(rule["reason"], str) or not rule["reason"].strip():
        raise PolicyError(f"rule {rule['id']!r} has no reason")
    when = rule.get("when")
    if when is not None and not isinstance(when, Mapping):
        raise PolicyError(f"rule {rule['id']!r} has a non-mapping when")


def _action_matches(rule_action: str, action: str) -> bool:
    return rule_action in (ANY_ACTION, action)


def _when_matches(when: Any, context: Mapping[str, Any]) -> bool:
    if when is None:
        return True
    if not isinstance(when, Mapping):
        raise PolicyError("when must be a mapping")
    for field, matcher in when.items():
        present = field in context and context[field] is not None
        if not _matcher_matches(matcher, context.get(field), present):
            return False
    return True


def _matcher_matches(matcher: Any, value: Any, present: bool) -> bool:
    """One ``when`` entry. An absent context field matches only ``exists: false``."""
    if isinstance(matcher, Mapping):
        if len(matcher) != 1:
            raise PolicyError("a matcher takes exactly one operator")
        operator, operand = next(iter(matcher.items()))
        if operator == "exists":
            return present is bool(operand)
        if not present:
            return False
        if operator == "in":
            return value in operand
        if operator == "not_in":
            return value not in operand
        if operator == "prefix":
            return isinstance(value, str) and value.startswith(str(operand))
        if operator == "glob":
            return isinstance(value, str) and _glob_any(value, operand)
        if operator == "not_glob":
            return isinstance(value, str) and not _glob_any(value, operand)
        raise PolicyError(f"unknown matcher operator {operator!r}")

    if isinstance(matcher, list):
        return present and value in matcher
    return present and value == matcher


def _glob_any(value: str, patterns: Any) -> bool:
    if isinstance(patterns, str):
        patterns = [patterns]
    if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
        raise PolicyError("glob takes a pattern or a list of patterns")
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)


def load_policy(path: str | Path) -> dict[str, Any]:
    """Read and validate the YAML policy. The only file read in this module."""
    with Path(path).open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise PolicyError("policy file must contain a mapping")
    validate_policy(document)
    return document


def policy_sha256(path: str | Path) -> str:
    """SHA-256 of the policy file's bytes, as recorded in the response."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    """CLI wrapper: print the decision as JSON and exit 0/1/2."""
    parser = argparse.ArgumentParser(description="Evaluate one action against the autonomy policy.")
    parser.add_argument("--action", required=True, help="the action being considered")
    parser.add_argument("--context-json", default="{}", help="the action context as a JSON object")
    parser.add_argument(
        "--policy",
        default=str(Path(__file__).with_name("autonomy-policy.yaml")),
        help="path to autonomy-policy.yaml",
    )
    arguments = parser.parse_args(argv)

    try:
        context = json.loads(arguments.context_json)
        if not isinstance(context, dict):
            raise ValueError("context must be an object")
    except ValueError:
        print(json.dumps({"error": "context must be a JSON object"}), file=sys.stderr)
        return 2

    try:
        decision = decide(arguments.action, context, load_policy(arguments.policy))
    except PolicyError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(decision.as_dict(), sort_keys=True))
    return {"allow": 0, "escalate": 1, "deny": 2}[decision.decision]


if __name__ == "__main__":
    raise SystemExit(main())
