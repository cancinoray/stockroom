"""Headless incident responder runner (T7.2, issue #62).

``make oncall-respond INCIDENT=<id>`` runs ``run-responder.sh``, which execs
this module. The run is bounded and isolated:

* the evidence packet is validated and its ``repo.base_ref`` / ``repo.base_commit``
  are the only base the run may use; a ``null`` commit produces a schema-valid
  escalation, never a guessed base;
* a ``git worktree add --detach`` worktree at that commit, then an
  ``oncall/<incident-id>`` branch, is the only place the responder writes; the
  source checkout is never modified;
* ``RESPONDER_CMD`` is a JSON argv array (no shell string, no vendor default)
  invoked with the task file and the packet path;
* the child gets an allowlisted environment, an isolated ``HOME`` and a ``PATH``
  that holds only shims for the policy's ``tools``;
* ``ONCALL_BUDGET_SECONDS`` (default 600) is a process-group timeout that can be
  lowered, never raised;
* the response is validated against ``response.schema.json`` before it is
  written, and ``incidents/<id>.md`` is rendered from that validated object.

Exit codes: ``0`` an incident record was written (including escalations),
``2`` the run could not produce a record.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import policy
from jsonschema import Draft202012Validator
from state import write_atomic

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = MODULE_DIR.parent
SCHEMA_PATH = MODULE_DIR / "response.schema.json"
TASK_PATH = MODULE_DIR / "responder-task.md"
POLICY_PATH = MODULE_DIR / "autonomy-policy.yaml"

DEFAULT_BUDGET_SECONDS = 600
MAX_BUDGET_SECONDS = 600
MIN_BUDGET_SECONDS = 1
DEFAULT_LANG = "C.UTF-8"
DEFAULT_TZ = "UTC"
DEFAULT_PROMETHEUS_URL = "http://localhost:9090"
DEFAULT_LOKI_URL = "http://localhost:3100"
DEFAULT_APP_URL = "http://localhost:8000"

EXIT_OK = 0
EXIT_ERROR = 2

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
TOOL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REDACTED = "[redacted]"


class RunnerError(RuntimeError):
    """The run cannot continue; the message is safe to print."""


class ConfigError(RunnerError):
    """An environment or path the runner refuses to start with."""


class PacketError(RunnerError):
    """The evidence packet is not the shape T7.1 froze."""


class ResponseError(RunnerError):
    """The responder's document does not validate or contradicts the run."""


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    """Everything one run reads from the operator's environment."""

    repo_root: Path
    evidence_dir: Path
    incidents_dir: Path
    worktrees_dir: Path
    budget_seconds: int
    responder_cmd: tuple[str, ...]
    gh_token: str | None
    prometheus_url: str
    loki_url: str
    app_url: str
    lang: str
    tz: str

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> RunnerConfig:
        settings = os.environ if environ is None else environ
        repo_root = Path(settings.get("ONCALL_REPO_ROOT") or DEFAULT_REPO_ROOT).resolve()

        budget = _budget(settings)
        return cls(
            repo_root=repo_root,
            evidence_dir=_path(
                settings, "ONCALL_EVIDENCE_DIR", repo_root / "on-call-engineer/evidence", repo_root
            ),
            incidents_dir=_path(
                settings,
                "ONCALL_INCIDENTS_DIR",
                repo_root / "on-call-engineer/incidents",
                repo_root,
            ),
            worktrees_dir=_path(
                settings, "ONCALL_WORKTREES_DIR", repo_root / "worktrees", repo_root
            ),
            budget_seconds=budget,
            responder_cmd=_responder_cmd(settings),
            gh_token=_gh_token(settings),
            prometheus_url=_local_url(settings, "PROMETHEUS_URL", DEFAULT_PROMETHEUS_URL),
            loki_url=_local_url(settings, "LOKI_URL", DEFAULT_LOKI_URL),
            app_url=_local_url(settings, "STOCKROOM_APP_URL", DEFAULT_APP_URL),
            lang=settings.get("LANG") or DEFAULT_LANG,
            tz=settings.get("TZ") or DEFAULT_TZ,
        )


def _path(settings: dict[str, str], name: str, default: Path, root: Path) -> Path:
    raw = settings.get(name)
    if raw is None or not raw.strip():
        return default.resolve()
    candidate = Path(raw).expanduser()
    return (candidate if candidate.is_absolute() else root / candidate).resolve()


def _budget(settings: dict[str, str]) -> int:
    raw = settings.get("ONCALL_BUDGET_SECONDS")
    if raw is None or not raw.strip():
        return DEFAULT_BUDGET_SECONDS
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError("ONCALL_BUDGET_SECONDS must be an integer") from None
    if value < MIN_BUDGET_SECONDS:
        raise ConfigError(f"ONCALL_BUDGET_SECONDS must be at least {MIN_BUDGET_SECONDS}")
    if value > MAX_BUDGET_SECONDS:
        print(
            json.dumps(
                {
                    "event": "budget_clamped",
                    "requested": value,
                    "applied": MAX_BUDGET_SECONDS,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return MAX_BUDGET_SECONDS
    return value


def _responder_cmd(settings: dict[str, str]) -> tuple[str, ...]:
    raw = settings.get("RESPONDER_CMD")
    if raw is None or not raw.strip():
        raise ConfigError(
            "RESPONDER_CMD is unset. Supply the responder as a JSON argv array, e.g. "
            'RESPONDER_CMD=\'["python3", "/path/to/responder.py"]\''
        )
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise ConfigError("RESPONDER_CMD must be a JSON array of strings") from None
    if (
        not isinstance(parsed, list)
        or not parsed
        or not all(isinstance(item, str) and item.strip() for item in parsed)
    ):
        raise ConfigError("RESPONDER_CMD must be a non-empty JSON array of strings")
    return tuple(parsed)


def _gh_token(settings: dict[str, str]) -> str | None:
    raw = settings.get("GH_TOKEN")
    if raw is None:
        return None
    if not raw.strip():
        raise ConfigError("GH_TOKEN is set but empty")
    return raw


def _local_url(settings: dict[str, str], name: str, default: str) -> str:
    value = (settings.get(name) or default).strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        raise ConfigError(f"{name} must be an http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise ConfigError(f"{name} must not contain credentials")
    if parts.hostname not in LOCAL_HOSTS:
        raise ConfigError(f"{name} must point at the local stack")
    return value


# -- packet -------------------------------------------------------------------


def load_packet(path: Path, incident_id: str) -> dict[str, Any]:
    """Read the evidence packet and check the fields this run depends on."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PacketError(f"no evidence packet at {path}") from None
    except (OSError, ValueError) as exc:
        raise PacketError(f"evidence packet is not readable JSON: {type(exc).__name__}") from None

    if not isinstance(document, dict):
        raise PacketError("evidence packet must be a JSON object")
    for key in ("incident_id", "alert", "service", "repo"):
        if key not in document:
            raise PacketError(f"evidence packet is missing {key!r}")
    if document["incident_id"] != incident_id:
        raise PacketError(
            f"evidence packet incident_id {document['incident_id']!r} is not {incident_id!r}"
        )

    alert = document["alert"]
    if not isinstance(alert, dict) or not isinstance(alert.get("name"), str):
        raise PacketError("evidence packet alert.name must be a string")
    for key in ("service", "repo"):
        if not isinstance(document[key], dict):
            raise PacketError(f"evidence packet {key} must be an object")

    base_ref = document["repo"].get("base_ref")
    if not isinstance(base_ref, str) or not base_ref.strip():
        raise PacketError("evidence packet repo.base_ref must be a non-empty string")
    base_commit = document["repo"].get("base_commit")
    if base_commit is not None and not isinstance(base_commit, str):
        raise PacketError("evidence packet repo.base_commit must be a string or null")
    return document


def packet_alert_view(packet: dict[str, Any]) -> dict[str, Any]:
    """The alert block of the response, copied from the packet and nothing else."""
    alert = packet["alert"]
    service = packet["service"]
    rule = alert.get("rule") if isinstance(alert.get("rule"), dict) else {}
    return {
        "name": str(alert.get("name") or ""),
        "severity": _optional_text(alert.get("severity")),
        "environment": _optional_text(service.get("environment")),
        "version": _optional_text(service.get("deployed_version")),
        "dashboard_url": _optional_text(service.get("dashboard_url")),
        "rule": {
            "expr": _optional_text(rule.get("expr")),
            "for": _optional_text(rule.get("for")),
        },
    }


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


# -- response schema ----------------------------------------------------------


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_response(
    document: dict[str, Any], schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate one response; return it so callers can chain."""
    validator = Draft202012Validator(schema if schema is not None else load_schema())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise ResponseError(f"response is not schema-valid at {where}: {first.message}")
    return document


def check_policy_decisions(document: dict[str, Any], policy_document: dict[str, Any]) -> None:
    """Every recorded decision must name a rule and match what that rule decides."""
    rules = {rule["id"]: rule for rule in policy_document["rules"]}
    for decision in document["policy"]["decisions"]:
        rule_id = decision["rule_id"]
        if rule_id == policy.DEFAULT_RULE_ID:
            if decision["decision"] != policy_document["default"]:
                raise ResponseError("the default rule id must record the policy default")
            continue
        rule = rules.get(rule_id)
        if rule is None:
            raise ResponseError(f"policy decision names unknown rule {rule_id!r}")
        if decision["decision"] != rule["decision"]:
            raise ResponseError(
                f"rule {rule_id!r} decides {rule['decision']!r}, not {decision['decision']!r}"
            )
        if rule["action"] not in (policy.ANY_ACTION, decision["action"]):
            raise ResponseError(
                f"rule {rule_id!r} guards {rule['action']!r}, not {decision['action']!r}"
            )


def check_policy_identity(
    document: dict[str, Any], policy_document: dict[str, Any], digest: str
) -> None:
    if document["policy"]["version"] != str(policy_document["version"]):
        raise ResponseError("the response records a different policy version")
    if document["policy"]["sha256"] != digest:
        raise ResponseError("the response records a different policy digest")


def render_json(document: dict[str, Any]) -> bytes:
    """The on-disk bytes: sorted keys, two-space indent, exactly one newline."""
    return (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _value(value: Any) -> str:
    return "not recorded" if value is None or value == "" else str(value)


def _code(value: Any) -> str:
    return f"`{value}`" if value is not None and value != "" else "not recorded"


def render_markdown(document: dict[str, Any]) -> str:
    """Render the human record from an object that passed the schema."""
    validate_response(document)

    alert = document["alert"]
    rule = alert["rule"]
    changes = document["changes"]
    timing = document["timing"]
    verification = document["verification"]
    escalation = document["escalation"]

    lines = [
        f"# Incident {document['incident_id']}",
        "",
        "## Alert",
        "",
        f"- Name: {_code(alert['name'])}",
        f"- Severity: {_value(alert['severity'])}",
        f"- Environment: {_value(alert['environment'])}",
        f"- Version: {_value(alert['version'])}",
        f"- Dashboard: {_value(alert['dashboard_url'])}",
        f"- Rule for: {_value(rule['for'])}",
        "",
    ]
    if rule["expr"] is None:
        lines.append("- Rule expr: (none recorded)")
        lines.append("")
    else:
        lines.extend(
            [
                "- Rule expr:",
                "",
                "  ```promql",
                *[f"  {line}" for line in str(rule["expr"]).splitlines()],
                "  ```",
                "",
            ]
        )

    lines.extend(
        [
            f"- Action: {document['action']}",
            "",
            "## User impact",
            "",
            document["user_impact"],
            "",
            "## Evidence inspected",
            "",
            *[f"- {item}" for item in document["evidence_inspected"]],
            "",
            "## Hypothesis",
            "",
            document["hypothesis"],
            "",
            "## Changes",
            "",
        ]
    )
    if changes["files"]:
        lines.extend(["- Files:", *[f"  - {_code(path)}" for path in changes["files"]]])
    else:
        lines.append("- Files: none")
    lines.extend(
        [
            f"- Test: {_code(changes['test'])}",
            f"- Branch: {_code(changes['branch'])}",
            f"- Base ref: {_code(changes['base_ref'])}",
            f"- Worktree: {_code(changes['worktree'])}",
            f"- Pull request: {_value(changes['pr_url'])}",
            "",
            "## Policy",
            "",
            (
                f"- Policy: version {_code(document['policy']['version'])}, "
                f"policy sha256 {_code(document['policy']['sha256'])}"
            ),
            "- Decisions:",
        ]
    )
    for decided in document["policy"]["decisions"]:
        lines.append(
            f"  - {_code(decided['action'])} -> {decided['decision']} "
            f"(rule {_code(decided['rule_id'])}): {decided['reason']}"
        )

    lines.extend(
        [
            "",
            "## Verification",
            "",
            f"- Status: {verification['status']}",
            f"- Observed at: {_value(verification['observed_at'])}",
        ]
    )
    if verification["checks"]:
        lines.extend(["- Checks:", *[f"  - {check}" for check in verification["checks"]]])
    else:
        lines.append("- Checks: none recorded")

    lines.extend(
        [
            "",
            "## Timing",
            "",
            f"- Started: {timing['started']}",
            f"- Ended: {timing['ended']}",
            (f"- Elapsed: {timing['elapsed_seconds']}s of a {timing['budget_seconds']}s budget"),
            "",
            "## Detection gap",
            "",
            document["detection_gap"] or "Not assessed.",
            "",
            "## Escalation",
            "",
        ]
    )
    if escalation is None:
        lines.append("None: the responder did not escalate.")
    else:
        lines.append(f"- Decision required: {escalation['decision_required']}")
        if escalation.get("context"):
            lines.append(f"- Context: {escalation['context']}")

    lines.extend(
        [
            "",
            "## Review",
            "",
            f"- Status: {document['review']['status']}",
            f"- Notes: {_value(document['review']['notes'])}",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


# -- isolated child environment ----------------------------------------------


def write_shims(shim_dir: Path, tools: list[str]) -> Path:
    """One shim per allowed binary; everything else is simply absent."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        if not TOOL_NAME.fullmatch(tool):
            raise ConfigError(f"policy tool name {tool!r} is not a plain binary name")
        path = shim_dir / tool
        path.write_text(_shim_source(tool), encoding="utf-8")
        path.chmod(0o755)
    return shim_dir


def _shim_source(tool: str) -> str:
    header = (
        "#!/bin/sh\n"
        f"# Generated by on-call-engineer/run_responder.py: the {tool} shim (T7.2, #62).\n"
        "# The policy names the binaries; this shim enforces its edges before the real one runs.\n"
        "set -eu\n"
        f'real="${{REAL_{tool.upper()}:-}}"\n'
        'if [ -z "$real" ]; then\n'
        f'  echo "oncall: {tool} is not available in this run" >&2\n'
        "  exit 127\n"
        "fi\n"
    )
    return header + SHIM_CHECKS.get(tool, "") + '\nexec "$real" "$@"\n'


SHIM_CHECKS: dict[str, str] = {
    "git": """
if [ "${1:-}" = "push" ]; then
  for arg in "$@"; do
    case "$arg" in
      --force|--force-with-lease|--force-with-lease=*|--force-if-includes|-f)
        echo "oncall: git push --force is denied by the autonomy policy" >&2
        exit 126
        ;;
      +*)
        echo "oncall: a forced refspec is denied by the autonomy policy" >&2
        exit 126
        ;;
      --delete)
        echo "oncall: deleting a remote branch is denied by the autonomy policy" >&2
        exit 126
        ;;
    esac
    target=${arg##*:}
    target=${target#refs/heads/}
    case "$target" in
      main|master)
        echo "oncall: pushing to $target is denied by the autonomy policy" >&2
        exit 126
        ;;
    esac
  done
fi
if [ "${1:-}" = "remote" ]; then
  case "${2:-}" in
    add|remove|rm|set-url|rename|prune|update|set-branches|set-head)
      echo "oncall: changing a git remote is denied by the autonomy policy" >&2
      exit 126
      ;;
  esac
fi
""",
    "gh": """
case "${1:-}" in
  pr)
    case "${2:-}" in
      create)
        base=""
        previous=""
        for arg in "$@"; do
          if [ "$previous" = "--base" ]; then base=$arg; fi
          case "$arg" in --base=*) base=${arg#--base=} ;; esac
          previous=$arg
        done
        if [ -n "$base" ] && [ -n "${ONCALL_BASE_REF:-}" ] &&
           [ "$base" != "$ONCALL_BASE_REF" ]; then
          echo "oncall: gh pr create --base $base is not the packet base" >&2
          echo "oncall: the packet base is $ONCALL_BASE_REF" >&2
          exit 126
        fi
        ;;
      list|view|diff|status|checks)
        ;;
      *)
        echo "oncall: gh pr ${2:-} is denied by the autonomy policy" >&2
        exit 126
        ;;
    esac
    ;;
  issue)
    case "${2:-}" in
      list|view) ;;
      *)
        echo "oncall: gh issue ${2:-} is denied by the autonomy policy" >&2
        exit 126
        ;;
    esac
    ;;
  repo)
    case "${2:-}" in
      view|list) ;;
      *)
        echo "oncall: gh repo ${2:-} is denied by the autonomy policy" >&2
        exit 126
        ;;
    esac
    ;;
  api)
    for arg in "$@"; do
      case "$arg" in
        -X|--method|-f|--field|-F|--raw-field|--input)
          echo "oncall: a mutating gh api call is denied by the autonomy policy" >&2
          exit 126
          ;;
        -X*|--method=*)
          case "$arg" in
            -XGET|--method=GET|-Xget|--method=get) ;;
            *)
              echo "oncall: a mutating gh api call is denied by the autonomy policy" >&2
              exit 126
              ;;
          esac
          ;;
      esac
    done
    ;;
  --version|--help|version|help)
    ;;
  *)
    echo "oncall: gh ${1:-} is denied by the autonomy policy" >&2
    exit 126
    ;;
esac
""",
    "docker": """
if [ -n "${DOCKER_HOST:-}" ]; then
  echo "oncall: DOCKER_HOST is set; only the local daemon is allowed" >&2
  exit 126
fi
for arg in "$@"; do
  case "$arg" in
    --host|--host=*|-H|-H*)
      echo "oncall: choosing a docker host is denied by the autonomy policy" >&2
      exit 126
      ;;
  esac
done
case "${1:-}" in
  context|login|logout|push|swarm|secret|node)
    echo "oncall: docker ${1:-} is denied by the autonomy policy" >&2
    exit 126
    ;;
  compose)
    allowed=1
    for arg in "$@"; do
      case "$arg" in
        up|down|stop|start|restart|build|ps|logs|config|images) allowed=0 ;;
      esac
    done
    if [ "$allowed" -eq 1 ]; then
      echo "oncall: this docker compose subcommand is denied by the autonomy policy" >&2
      exit 126
    fi
    ;;
  ps|images|inspect|version|info|logs)
    ;;
  *)
    echo "oncall: docker ${1:-} is denied by the autonomy policy" >&2
    exit 126
    ;;
esac
""",
    "curl": """
for arg in "$@"; do
  case "$arg" in
    http://*|https://*)
      host=${arg#*://}
      host=${host%%/*}
      host=${host%%:*}
      case "$host" in
        localhost|127.0.0.1|"[::1]") ;;
        *)
          echo "oncall: $host is not the local stack; the autonomy policy denies it" >&2
          exit 126
          ;;
      esac
      ;;
    *://*)
      echo "oncall: only http(s) to the local stack is allowed" >&2
      exit 126
      ;;
  esac
done
""",
}


def real_binaries(tools: list[str], environ: dict[str, str]) -> dict[str, str]:
    """Resolve each tool's real binary, honouring an operator/test override."""
    resolved: dict[str, str] = {}
    for tool in tools:
        variable = f"REAL_{tool.upper()}"
        resolved[variable] = environ.get(variable) or shutil.which(tool) or ""
    return resolved


def build_child_env(
    config: RunnerConfig,
    *,
    incident_id: str,
    worktree: Path,
    response_path: Path,
    packet_path: Path,
    policy_path: Path,
    base_ref: str,
    base_commit: str,
    shim_dir: Path,
    home: Path,
    real: dict[str, str],
) -> dict[str, str]:
    """The whole of the responder's environment: an allowlist, not a copy."""
    env = {
        "PATH": str(shim_dir),
        "HOME": str(home),
        "LANG": config.lang,
        "TZ": config.tz,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GH_CONFIG_DIR": str(home / ".config/gh"),
        "PROMETHEUS_URL": config.prometheus_url,
        "LOKI_URL": config.loki_url,
        "STOCKROOM_APP_URL": config.app_url,
        "ONCALL_INCIDENT_ID": incident_id,
        "ONCALL_BUDGET_SECONDS": str(config.budget_seconds),
        "ONCALL_WORKTREE": str(worktree),
        "ONCALL_RESPONSE_PATH": str(response_path),
        "ONCALL_PACKET_PATH": str(packet_path),
        "ONCALL_TASK_PATH": str(TASK_PATH),
        "ONCALL_POLICY_PATH": str(policy_path),
        "ONCALL_POLICY_PY": str(MODULE_DIR / "policy.py"),
        "ONCALL_BASE_REF": base_ref,
        "ONCALL_BASE_COMMIT": base_commit,
    }
    env.update(real)
    if config.gh_token:
        env["GH_TOKEN"] = config.gh_token
    return env


def write_isolated_home(home: Path, token: str | None) -> None:
    """Git and gh credentials live in the throwaway HOME, never in argv."""
    home.mkdir(parents=True, exist_ok=True)
    gitconfig = [
        "[user]",
        "\tname = Stockroom On-Call Responder",
        "\temail = on-call-responder@stockroom.invalid",
        "[init]",
        "\tdefaultBranch = main",
    ]
    if token:
        gitconfig.extend(["[credential]", "\thelper = store"])
    (home / ".gitconfig").write_text("\n".join(gitconfig) + "\n", encoding="utf-8")

    if not token:
        return
    credentials = home / ".git-credentials"
    credentials.write_text(f"https://x-access-token:{token}@github.com\n", encoding="utf-8")
    credentials.chmod(0o600)

    gh_dir = home / ".config/gh"
    gh_dir.mkdir(parents=True, exist_ok=True)
    hosts = gh_dir / "hosts.yml"
    hosts.write_text(
        "github.com:\n"
        f"    oauth_token: {token}\n"
        "    user: on-call-responder\n"
        "    git_protocol: https\n",
        encoding="utf-8",
    )
    hosts.chmod(0o600)


def redact(text: str, token: str | None) -> str:
    """Remove the run's credential from anything that may be printed."""
    if not token:
        return text
    return text.replace(token, REDACTED)


# -- timing -------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def timing_block(started_at: str, ended_at: str, elapsed: float, budget: int) -> dict[str, Any]:
    return {
        "started": started_at,
        "ended": ended_at,
        "elapsed_seconds": round(max(elapsed, 0.0), 3),
        "budget_seconds": budget,
    }


# -- records ------------------------------------------------------------------


def escalation_document(
    packet: dict[str, Any],
    *,
    reason: str,
    detail: str,
    timing: dict[str, Any],
    policy_document: dict[str, Any],
    worktree: str | None = None,
    budget_exhausted: bool = False,
) -> dict[str, Any]:
    """A schema-valid escalation for a run that could not finish as a fix."""
    decided = policy.decide(
        "escalate",
        {"reason": reason, **({"budget_exhausted": True} if budget_exhausted else {})},
        policy_document,
    )
    alert = packet_alert_view(packet)
    return {
        "incident_id": packet["incident_id"],
        "alert": alert,
        "user_impact": "Not assessed: the run stopped before a diagnosis was reached.",
        "evidence_inspected": ["evidence packet"],
        "hypothesis": f"The run stopped before a diagnosis: {detail}",
        "action": "escalate",
        "changes": {
            "files": [],
            "test": None,
            "branch": None,
            "base_ref": packet["repo"].get("base_ref"),
            "worktree": worktree,
            "pr_url": None,
        },
        "policy": {
            "version": str(policy_document["version"]),
            "sha256": "0" * 64,
            "decisions": [decided.as_dict()],
        },
        "verification": {"status": "not_run", "checks": [], "observed_at": None},
        "timing": timing,
        "detection_gap": "",
        "escalation": {
            "decision_required": f"A human must take over {alert['name']}: {detail}",
            "context": reason,
        },
        "review": {
            "status": "pending",
            "notes": "Automatic escalation written by the runner; no fix was attempted.",
        },
    }


def write_record(
    document: dict[str, Any],
    config: RunnerConfig,
    policy_document: dict[str, Any],
    digest: str,
) -> Path:
    """Validate, write the JSON, then render the Markdown from the same object."""
    document["policy"]["version"] = str(policy_document["version"])
    document["policy"]["sha256"] = digest
    validate_response(document)
    check_policy_identity(document, policy_document, digest)
    check_policy_decisions(document, policy_document)

    config.incidents_dir.mkdir(parents=True, exist_ok=True)
    json_path = config.incidents_dir / f"{document['incident_id']}.json"
    markdown_path = config.incidents_dir / f"{document['incident_id']}.md"
    write_atomic(json_path, render_json(document).decode("utf-8"))
    write_atomic(markdown_path, render_markdown(document))
    return json_path


# -- the run ------------------------------------------------------------------


def run(incident_id: str, environ: dict[str, str] | None = None) -> int:
    try:
        config = RunnerConfig.from_env(environ)
    except ConfigError as exc:
        return _fail("config_error", str(exc))

    try:
        policy_document = policy.load_policy(POLICY_PATH)
    except (OSError, policy.PolicyError) as exc:
        return _fail("policy_error", str(exc))
    digest = policy.policy_sha256(POLICY_PATH)

    packet_path = config.evidence_dir / f"{incident_id}.json"
    try:
        packet = load_packet(packet_path, incident_id)
    except PacketError as exc:
        return _fail("packet_error", str(exc))

    started_at = utc_now()
    started = time.monotonic()

    if packet["repo"].get("base_commit") is None:
        timing = timing_block(
            started_at, utc_now(), time.monotonic() - started, config.budget_seconds
        )
        document = escalation_document(
            packet,
            reason="base_commit_missing",
            detail="the packet records repo.base_commit = null, so no worktree can be based on it",
            timing=timing,
            policy_document=policy_document,
        )
        return _finish(document, config, policy_document, digest)

    base_commit = str(packet["repo"]["base_commit"])
    base_ref = str(packet["repo"]["base_ref"])
    branch = f"oncall/{incident_id}"
    worktree = config.worktrees_dir / f"oncall-{incident_id}"
    worktree_record = str(worktree.relative_to(config.repo_root))
    if worktree.exists():
        return _fail("worktree_exists", f"{worktree} already exists; inspect or remove it first")

    try:
        create_worktree(config.repo_root, worktree, base_commit, branch)
    except RunnerError as exc:
        return _fail("worktree_failed", str(exc))

    home = Path(tempfile.mkdtemp(prefix="oncall-home-"))
    shim_dir = home / "bin"
    response_path = home / "response.json"
    try:
        write_isolated_home(home, config.gh_token)
        write_shims(shim_dir, list(policy_document["tools"]))
        real = real_binaries(list(policy_document["tools"]), environ or dict(os.environ))
        env = build_child_env(
            config,
            incident_id=incident_id,
            worktree=worktree,
            response_path=response_path,
            packet_path=packet_path,
            policy_path=POLICY_PATH,
            base_ref=base_ref,
            base_commit=base_commit,
            shim_dir=shim_dir,
            home=home,
            real=real,
        )
        outcome = invoke_responder(
            config.responder_cmd,
            task_path=TASK_PATH,
            packet_path=packet_path,
            env=env,
            cwd=worktree,
            budget=config.budget_seconds,
            token=config.gh_token,
        )
        response_text = _read_response_text(response_path)
    finally:
        shutil.rmtree(home, ignore_errors=True)

    if outcome.stderr.strip():
        print(
            json.dumps(
                {"event": "responder_stderr", "text": outcome.stderr[-2000:]}, sort_keys=True
            ),
            file=sys.stderr,
        )

    ended_at = utc_now()
    timing = timing_block(started_at, ended_at, time.monotonic() - started, config.budget_seconds)

    if outcome.timed_out:
        document = escalation_document(
            packet,
            reason="budget_exhausted",
            detail=f"the responder exceeded the {config.budget_seconds}s budget and was killed",
            timing=timing,
            policy_document=policy_document,
            worktree=worktree_record,
            budget_exhausted=True,
        )
        return _finish(document, config, policy_document, digest)

    document, problem = parse_response(response_text, config.gh_token)
    if problem is not None:
        document = escalation_document(
            packet,
            reason="response_unusable",
            detail=problem,
            timing=timing,
            policy_document=policy_document,
            worktree=worktree_record,
        )
        return _finish(document, config, policy_document, digest)

    document["incident_id"] = incident_id
    document["alert"] = packet_alert_view(packet)
    document["timing"] = timing
    document["policy"].setdefault("decisions", [])
    document["policy"]["version"] = str(policy_document["version"])
    document["policy"]["sha256"] = digest

    mismatch = check_changes(document, branch=branch, worktree=worktree_record, base_ref=base_ref)
    if mismatch is not None:
        document = escalation_document(
            packet,
            reason="changes_do_not_match_the_run",
            detail=mismatch,
            timing=timing,
            policy_document=policy_document,
            worktree=worktree_record,
        )
        return _finish(document, config, policy_document, digest)

    try:
        validate_response(document)
    except ResponseError as exc:
        document = escalation_document(
            packet,
            reason="response_invalid",
            detail=str(exc),
            timing=timing,
            policy_document=policy_document,
            worktree=worktree_record,
        )
        return _finish(document, config, policy_document, digest)

    try:
        check_policy_decisions(document, policy_document)
        if document["action"] == "fix" and not _consulted_pr_create(document):
            raise ResponseError(
                "a fix must record an allow decision for pr.create before it opens the PR"
            )
    except ResponseError as exc:
        document = escalation_document(
            packet,
            reason="response_policy_inconsistent",
            detail=str(exc),
            timing=timing,
            policy_document=policy_document,
            worktree=worktree_record,
        )
        return _finish(document, config, policy_document, digest)

    return _finish(document, config, policy_document, digest)


@dataclass(frozen=True, slots=True)
class ChildOutcome:
    returncode: int
    timed_out: bool
    stderr: str


def create_worktree(repo_root: Path, worktree: Path, base_commit: str, branch: str) -> None:
    """Add a detached worktree at the packet's commit, then branch in it."""
    worktree.parent.mkdir(parents=True, exist_ok=True)
    added = subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree), base_commit],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if added.returncode != 0:
        raise RunnerError(f"git worktree add failed: {added.stderr.strip()[:300]}")
    created = subprocess.run(
        ["git", "-C", str(worktree), "switch", "--create", branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        raise RunnerError(f"git switch --create {branch} failed: {created.stderr.strip()[:300]}")


def invoke_responder(
    command: tuple[str, ...],
    *,
    task_path: Path,
    packet_path: Path,
    env: dict[str, str],
    cwd: Path,
    budget: int,
    token: str | None,
) -> ChildOutcome:
    """Run the responder under a process-group timeout; never a shell string."""
    process = subprocess.Popen(  # noqa: S603 - argv, not a shell
        [*command, str(task_path), str(packet_path)],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    return _wait(process, budget, token)


def _wait(process: subprocess.Popen[str], budget: int, token: str | None) -> ChildOutcome:
    try:
        _, stderr = process.communicate(timeout=budget)
        timed_out = False
    except subprocess.TimeoutExpired:
        _terminate_group(process)
        _, stderr = process.communicate()
        timed_out = True
    return ChildOutcome(
        returncode=process.returncode,
        timed_out=timed_out,
        stderr=redact(stderr or "", token),
    )


def _terminate_group(process: subprocess.Popen[str]) -> None:
    """Kill the responder's whole process group, not just its leader."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _read_response_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def parse_response(text: str | None, token: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """The responder's document, or the reason it cannot be normalised.

    Schema validation happens after the runner has restored the fields it owns
    (incident id, alert, timing, policy identity), so a responder cannot lie
    about them and a time it could not know is not a validation failure.
    """
    if text is None:
        return None, "the responder wrote no response file"
    if token and token in text:
        return None, "the response contained the run's credential and was discarded"
    try:
        document = json.loads(text)
    except ValueError:
        return None, "the response is not valid JSON"
    if not isinstance(document, dict):
        return None, "the response is not a JSON object"
    if not isinstance(document.get("policy"), dict):
        return None, "the response has no policy object"
    return document, None


def check_changes(
    document: dict[str, Any], *, branch: str, worktree: str, base_ref: str
) -> str | None:
    """The runner owns the worktree path; a fix must match the run and the packet."""
    if document.get("action") != "fix":
        return None
    changes = document.get("changes")
    if not isinstance(changes, dict):
        return "a fix must record a changes object"
    changes["worktree"] = worktree
    if changes.get("branch") != branch:
        return f"the response recorded branch {changes.get('branch')!r}, not {branch!r}"
    if changes.get("base_ref") != base_ref:
        return f"the response recorded base {changes.get('base_ref')!r}, not {base_ref!r}"
    return None


def _consulted_pr_create(document: dict[str, Any]) -> bool:
    return any(
        decided["action"] == "pr.create" and decided["decision"] == "allow"
        for decided in document["policy"]["decisions"]
    )


def _finish(
    document: dict[str, Any],
    config: RunnerConfig,
    policy_document: dict[str, Any],
    digest: str,
) -> int:
    try:
        json_path = write_record(document, config, policy_document, digest)
    except ResponseError as exc:
        return _fail("record_invalid", str(exc))
    print(
        json.dumps(
            {
                "event": "incident_recorded",
                "incident_id": document["incident_id"],
                "action": document["action"],
                "pr_url": document["changes"]["pr_url"],
                "json": str(json_path),
                "markdown": str(json_path.with_suffix(".md")),
            },
            sort_keys=True,
        )
    )
    return EXIT_OK


def _fail(event: str, message: str) -> int:
    print(json.dumps({"event": event, "error": message}, sort_keys=True), file=sys.stderr)
    return EXIT_ERROR


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or not arguments[0].strip():
        print(
            "usage: run-responder.sh <incident-id>  (the id names "
            "on-call-engineer/evidence/<incident-id>.json)",
            file=sys.stderr,
        )
        return EXIT_ERROR
    try:
        return run(arguments[0])
    except RunnerError as exc:
        return _fail("runner_error", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
