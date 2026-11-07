"""The headless responder run: worktree, base, budget, isolation, shims (#62).

Nothing here calls a real agent, a real ``gh`` or a real GitHub. The responder
is a small script written into the test's temporary directory, and ``gh`` and
``docker`` are fake binaries reached only through the runner's shims.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
ONCALL_DIR = ROOT / "on-call-engineer"
if str(ONCALL_DIR) not in sys.path:
    sys.path.insert(0, str(ONCALL_DIR))

import policy  # noqa: E402
import run_responder  # noqa: E402

INCIDENT_ID = "stockroom-order-error-rate-high-324f01034b2a-1794026992"
SENTINEL_TOKEN = "ghp_SENTINEL_TOKEN_DO_NOT_LEAK"
FAKE_PR_URL = "https://github.com/example/stockroom/pull/123"

FORBIDDEN_ENV = {
    "STOCKROOM_DATABASE_URL": "postgresql://sentinel:sentinel@db.invalid/prod",
    "DATABASE_URL": "postgresql://sentinel:sentinel@db.invalid/prod",
    "PGPASSWORD": "sentinel-pg-password",
    "PGHOST": "db.invalid",
    "AWS_ACCESS_KEY_ID": "AKIASENTINEL",
    "AWS_SECRET_ACCESS_KEY": "sentinel-aws-secret",
    "GOOGLE_APPLICATION_CREDENTIALS": "/sentinel/google.json",
    "AZURE_CLIENT_SECRET": "sentinel-azure-secret",
    "SSH_AUTH_SOCK": "/tmp/sentinel-agent.sock",
    "OTEL_EXPORTER_OTLP_HEADERS": "authorization=Bearer sentinel-otel",
}

FAKE_RESPONDER = '''\
"""A fake headless responder for the T7.2 tests. Never a real agent."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CONFIG = json.loads(Path(__file__).with_suffix(".json").read_text())
WORKTREE = Path(os.environ["ONCALL_WORKTREE"])
BASE = os.environ["ONCALL_BASE_REF"]
INCIDENT = os.environ["ONCALL_INCIDENT_ID"]
PROBE = Path(CONFIG["probe"])


def sh(*argv):
    return subprocess.run(list(argv), capture_output=True, text=True)


def main():
    mode = CONFIG["mode"]
    if mode == "silent":
        return 0
    if mode == "slow":
        PROBE.write_text(json.dumps({"phase": "started"}))
        time.sleep(CONFIG.get("sleep", 30))
        PROBE.write_text(json.dumps({"phase": "finished"}))
        return 0
    if mode == "invalid":
        Path(os.environ["ONCALL_RESPONSE_PATH"]).write_text('{"action": "fix"}')
        PROBE.write_text(json.dumps({"phase": "invalid"}))
        return 0

    probe = {
        "argv": sys.argv[1:],
        "path_entries": sorted(os.listdir(os.environ["PATH"])),
        "path": os.environ["PATH"],
        "home": os.environ["HOME"],
        "cwd": os.getcwd(),
        "env_present": {
            key: key in os.environ
            for key in (
                "STOCKROOM_DATABASE_URL",
                "DATABASE_URL",
                "PGHOST",
                "PGPASSWORD",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_ACCESS_KEY_ID",
                "GOOGLE_APPLICATION_CREDENTIALS",
                "AZURE_CLIENT_SECRET",
                "SSH_AUTH_SOCK",
                "OTEL_EXPORTER_OTLP_HEADERS",
            )
        },
        "gh_token_present": "GH_TOKEN" in os.environ,
        "denied_binaries": {},
        "denials": [],
        "policy": [],
    }
    for binary in ("ssh", "scp", "psql", "pg_dump", "aws", "gcloud", "kubectl", "az"):
        probe["denied_binaries"][binary] = sh(
            "sh", "-c", "command -v " + binary
        ).stdout.strip()

    denials = [
        ("git", "push", "origin", "main"),
        ("git", "push", "--force", "origin", "oncall/example"),
        ("git", "push", "origin", "HEAD:refs/heads/master"),
        ("git", "remote", "set-url", "origin", "https://example.com/x.git"),
        ("gh", "pr", "merge", "1"),
        ("gh", "pr", "close", "1"),
        ("gh", "secret", "list"),
        ("gh", "repo", "delete", "example"),
        ("gh", "workflow", "run", "ci"),
        ("gh", "api", "-X", "POST", "/repos/example/stockroom"),
        ("gh", "issue", "comment", "1", "--body", "hi"),
        ("docker", "--host", "tcp://example.com:2375", "ps"),
        ("docker", "push", "example/app:1"),
        ("docker", "login", "example.com"),
        ("docker", "context", "use", "remote"),
        ("curl", "http://example.com/health"),
    ]
    for argv in denials:
        probe["denials"].append({"argv": list(argv), "code": sh(*argv).returncode})
    probe["docker_allowed"] = sh("docker", "compose", "ps").returncode

    def consult(action, context):
        completed = sh(
            "python3",
            os.environ["ONCALL_POLICY_PY"],
            "--action",
            action,
            "--context-json",
            json.dumps(context),
            "--policy",
            os.environ["ONCALL_POLICY_PATH"],
        )
        decision = json.loads(completed.stdout)
        decision["exit_code"] = completed.returncode
        probe["policy"].append(decision)
        return decision

    consult("read.packet", {})
    consult("read.repo", {"path": "app/order_math.py"})
    consult("run.tests", {})
    consult("edit", {"path": "app/order_math.py"})
    consult("git.commit", {"branch": "oncall/" + INCIDENT})

    source = WORKTREE / "app/order_math.py"
    source.write_text(source.read_text().replace("> qty", ">= qty"))
    added = WORKTREE / "tests/test_order_math_fix.py"
    added.write_text(
        "import sys\\n"
        "from pathlib import Path\\n\\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\\n\\n"
        "from app.order_math import can_reserve\\n\\n\\n"
        "def test_the_last_unit_can_be_reserved():\\n"
        "    assert can_reserve(1, 0, 1) is True\\n"
    )
    sh("git", "add", "app/order_math.py", "tests/test_order_math_fix.py")
    commit = sh("git", "commit", "-m", "fix: allow reserving the last unit (#62)")
    tests = sh("python3", "-m", "pytest", "-q", "tests/test_order_math_fix.py")

    created = sh(
        "gh",
        "pr",
        "create",
        "--base",
        BASE,
        "--title",
        "fix: reserve the last unit",
        "--body",
        "Refs #62",
    )
    consult("pr.create", {"base_matches_packet": True})

    response = {
        "incident_id": INCIDENT,
        "alert": {
            "name": "placeholder",
            "severity": None,
            "environment": None,
            "version": None,
            "dashboard_url": None,
            "rule": {"expr": None, "for": None},
        },
        "user_impact": "An order for exactly the available quantity is refused with 409.",
        "evidence_inspected": ["evidence packet", "app/order_math.py"],
        "hypothesis": "can_reserve uses > instead of >=, so the last unit cannot be sold.",
        "action": "fix",
        "changes": {
            "files": ["app/order_math.py"],
            "test": "tests/test_order_math_fix.py",
            "branch": "oncall/" + INCIDENT,
            "base_ref": CONFIG.get("base_ref", BASE),
            "worktree": "",
            "pr_url": created.stdout.strip(),
        },
        "policy": {
            "version": "0",
            "sha256": "0" * 64,
            "decisions": [
                {key: item[key] for key in ("action", "decision", "rule_id", "reason")}
                for item in probe["policy"]
                if item["exit_code"] == 0
            ],
        },
        "verification": {
            "status": "verified" if tests.returncode == 0 else "failed",
            "checks": ["python3 -m pytest tests/test_order_math_fix.py"],
            "observed_at": None,
        },
        "timing": {
            "started": "1970-01-01T00:00:00Z",
            "ended": "1970-01-01T00:00:00Z",
            "elapsed_seconds": 0,
            "budget_seconds": 600,
        },
        "detection_gap": "None: the alert fired one hold duration after the first refusal.",
        "escalation": None,
        "review": {"status": "pending", "notes": "QA reviews the PR before merge."},
    }
    if CONFIG.get("leak"):
        response["review"]["notes"] = os.environ.get("GH_TOKEN", "")
    PROBE.write_text(json.dumps(probe))
    Path(os.environ["ONCALL_RESPONSE_PATH"]).write_text(json.dumps(response))
    return 0


raise SystemExit(main())
'''


def git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *arguments], cwd=repo, capture_output=True, text=True, check=True)


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "on-call-engineer/evidence").mkdir(parents=True)
    (repo / "app/__init__.py").write_text("")
    (repo / "app/order_math.py").write_text(
        "def available(on_hand, reserved):\n"
        "    return on_hand - reserved\n\n\n"
        "def can_reserve(on_hand, reserved, qty):\n"
        "    return available(on_hand, reserved) > qty\n"
    )
    (repo / "tests/test_order_math.py").write_text(
        "import sys\n"
        "from pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n\n"
        "from app.order_math import available\n\n\n"
        "def test_available():\n"
        "    assert available(5, 2) == 3\n"
    )
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test Runner")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD").stdout.strip()


def write_packet(repo: Path, base_commit: str | None, base_ref: str = "main") -> Path:
    document = {
        "incident_id": INCIDENT_ID,
        "generated_at": "2026-11-07T14:00:00Z",
        "alert": {
            "name": "StockroomOrderErrorRateHigh",
            "severity": "critical",
            "state": "firing",
            "active_at": "2026-11-07T13:59:00Z",
            "value": "1",
            "labels": {
                "alertname": "StockroomOrderErrorRateHigh",
                "severity": "critical",
                "service": "stockroom",
                "environment": "development",
                "version": "0.1.0",
                "owner": "stockroom-on-call",
                "dashboard_url": "http://localhost:3000/d/stockroom-order-journey",
            },
            "fingerprint": "324f01034b2a" + "0" * 52,
            "annotations": {
                "summary": "Order journey is returning 5xx above 5%",
                "runbook_url": "_docs/runbooks/stockroom-order-error-rate-high.md",
            },
            "rule": {
                "expr": "sum(rate(stockroom_orders_failed_total[5m])) > 0.05",
                "for": "1m",
                "state": "firing",
            },
        },
        "service": {
            "name": "stockroom",
            "environment": "development",
            "deployed_version": "0.1.0",
            "version_source": "alert_label",
            "owner": "stockroom-on-call",
            "dashboard_url": "http://localhost:3000/d/stockroom-order-journey",
            "runbook_url": "_docs/runbooks/stockroom-order-error-rate-high.md",
        },
        "deploy": {"image_reference": "stockroom-app:local", "version_label": "0.1.0"},
        "repo": {"base_ref": base_ref, "base_commit": base_commit, "source": "operator"},
        "observations": {"prometheus": [], "logs": {}, "app": {}},
        "limits": {
            "lookback_minutes": 15,
            "log_samples": 20,
            "trace_samples": 3,
            "http_timeout_seconds": 5.0,
            "resolve_grace_polls": 2,
        },
    }
    path = repo / "on-call-engineer/evidence" / f"{INCIDENT_ID}.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_fake_tool(path: Path, log: Path, output: str) -> Path:
    path.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\necho "{output}"\nexit 0\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def write_fake_responder(tmp_path: Path, **config: Any) -> Path:
    script = tmp_path / "fake_responder.py"
    script.write_text(FAKE_RESPONDER, encoding="utf-8")
    script.with_suffix(".json").write_text(
        json.dumps({"probe": str(tmp_path / "probe.json"), **config}), encoding="utf-8"
    )
    return script


def runner_env(tmp_path: Path, responder: Path, **overrides: str) -> dict[str, str]:
    gh_log = tmp_path / "gh.log"
    docker_log = tmp_path / "docker.log"
    gh_log.write_text("")
    docker_log.write_text("")
    env = dict(os.environ)
    env.update(FORBIDDEN_ENV)
    env.update(
        {
            "GH_TOKEN": SENTINEL_TOKEN,
            "RESPONDER_CMD": json.dumps(["python3", str(responder)]),
            "ONCALL_REPO_ROOT": str(tmp_path / "repo"),
            "REAL_GH": str(write_fake_tool(tmp_path / "real_gh", gh_log, FAKE_PR_URL)),
            "REAL_DOCKER": str(write_fake_tool(tmp_path / "real_docker", docker_log, "ok")),
        }
    )
    env.update(overrides)
    return env


def invoke_runner(
    repo: Path, env: dict[str, str], incident_id: str = INCIDENT_ID
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(ROOT / "on-call-engineer/run-responder.sh"), incident_id],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def record(repo: Path) -> dict[str, Any]:
    path = repo / "on-call-engineer/incidents" / f"{INCIDENT_ID}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_policy() -> dict[str, Any]:
    return policy.load_policy(ONCALL_DIR / "autonomy-policy.yaml")


def test_a_fix_run_writes_a_valid_record_and_leaves_the_checkout_alone(
    tmp_path: Path,
) -> None:
    repo, base_commit = make_repo(tmp_path)
    write_packet(repo, base_commit)
    fake = write_fake_responder(tmp_path, mode="fix")
    env = runner_env(tmp_path, fake)
    status_before = git(repo, "status", "--porcelain", "--untracked-files=no").stdout

    completed = invoke_runner(repo, env)

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout.strip().splitlines()[-1])
    assert summary["action"] == "fix"
    assert summary["pr_url"] == FAKE_PR_URL

    document = record(repo)
    run_responder.validate_response(document)
    assert document["incident_id"] == INCIDENT_ID
    assert document["alert"]["name"] == "StockroomOrderErrorRateHigh"
    assert document["alert"]["version"] == "0.1.0"
    assert document["alert"]["rule"]["for"] == "1m"
    assert document["action"] == "fix"
    assert document["changes"]["pr_url"] == FAKE_PR_URL
    assert document["changes"]["base_ref"] == "main"
    assert document["changes"]["branch"] == f"oncall/{INCIDENT_ID}"
    assert document["changes"]["worktree"] == f"worktrees/oncall-{INCIDENT_ID}"
    assert document["changes"]["files"] == ["app/order_math.py"]
    assert document["changes"]["test"] == "tests/test_order_math_fix.py"
    assert document["timing"]["budget_seconds"] == 600
    assert document["timing"]["elapsed_seconds"] >= 0
    assert document["escalation"] is None
    assert document["verification"]["status"] == "verified"
    assert document["policy"]["sha256"] == policy.policy_sha256(ONCALL_DIR / "autonomy-policy.yaml")
    rules = {rule["id"] for rule in load_policy()["rules"]}
    assert {item["rule_id"] for item in document["policy"]["decisions"]} <= rules | {
        policy.DEFAULT_RULE_ID
    }
    assert any(item["action"] == "pr.create" for item in document["policy"]["decisions"])

    markdown = (repo / "on-call-engineer/incidents" / f"{INCIDENT_ID}.md").read_text()
    for expected in (INCIDENT_ID, FAKE_PR_URL, "app/order_math.py", "pr-create"):
        assert expected in markdown

    worktree = repo / "worktrees" / f"oncall-{INCIDENT_ID}"
    assert worktree.is_dir()
    assert ">= qty" in (worktree / "app/order_math.py").read_text()
    assert (worktree / "tests/test_order_math_fix.py").is_file()
    branch = git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert branch == f"oncall/{INCIDENT_ID}"
    assert "fix: allow reserving the last unit" in git(worktree, "log", "-1", "--format=%s").stdout
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == base_commit

    # The tracked source checkout is untouched; the incident record is the only new file.
    assert git(repo, "status", "--porcelain", "--untracked-files=no").stdout == status_before
    untracked = git(repo, "status", "--porcelain").stdout
    assert "app/" not in untracked
    assert (repo / "on-call-engineer/incidents" / f"{INCIDENT_ID}.json").is_file()
    assert (repo / "on-call-engineer/incidents" / f"{INCIDENT_ID}.md").is_file()


def test_the_child_environment_is_an_allowlist_and_the_shims_are_enforced(
    tmp_path: Path,
) -> None:
    repo, base_commit = make_repo(tmp_path)
    write_packet(repo, base_commit)
    fake = write_fake_responder(tmp_path, mode="fix")
    env = runner_env(tmp_path, fake)

    completed = invoke_runner(repo, env)
    assert completed.returncode == 0, completed.stderr

    probe = json.loads((tmp_path / "probe.json").read_text())
    tools = sorted(load_policy()["tools"])
    assert probe["path_entries"] == tools
    assert "oncall-home-" in probe["path"]

    for name, present in probe["env_present"].items():
        assert present is False, f"{name} leaked into the responder environment"
    assert probe["gh_token_present"] is True
    assert probe["home"] != os.environ.get("HOME")
    assert Path(probe["home"]).name.startswith("oncall-home-")

    for binary, found in probe["denied_binaries"].items():
        assert found == "", f"{binary} is resolvable in the responder PATH"

    assert [item["code"] for item in probe["denials"]] == [126] * len(probe["denials"])
    assert probe["docker_allowed"] == 0

    gh_calls = (tmp_path / "gh.log").read_text().splitlines()
    assert len(gh_calls) == 1
    assert gh_calls[0].startswith("pr create --base main")
    assert SENTINEL_TOKEN not in "\n".join(gh_calls)
    assert (tmp_path / "docker.log").read_text().strip() == "compose ps"

    assert SENTINEL_TOKEN not in probe["argv"]
    assert SENTINEL_TOKEN not in json.dumps(probe)


def test_the_token_never_reaches_the_record_or_the_worktree(tmp_path: Path) -> None:
    repo, base_commit = make_repo(tmp_path)
    write_packet(repo, base_commit)
    fake = write_fake_responder(tmp_path, mode="fix")
    env = runner_env(tmp_path, fake)

    completed = invoke_runner(repo, env)
    assert completed.returncode == 0, completed.stderr

    incident_json = (repo / "on-call-engineer/incidents" / f"{INCIDENT_ID}.json").read_text()
    incident_md = (repo / "on-call-engineer/incidents" / f"{INCIDENT_ID}.md").read_text()
    assert SENTINEL_TOKEN not in incident_json
    assert SENTINEL_TOKEN not in incident_md
    assert SENTINEL_TOKEN not in completed.stdout
    assert SENTINEL_TOKEN not in completed.stderr

    worktree = repo / "worktrees" / f"oncall-{INCIDENT_ID}"
    for path in worktree.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert SENTINEL_TOKEN not in path.read_text(errors="ignore")


def test_a_response_that_repeats_the_credential_becomes_an_escalation(tmp_path: Path) -> None:
    repo, base_commit = make_repo(tmp_path)
    write_packet(repo, base_commit)
    fake = write_fake_responder(tmp_path, mode="fix", leak=True)
    env = runner_env(tmp_path, fake)

    completed = invoke_runner(repo, env)

    assert completed.returncode == 0, completed.stderr
    document = record(repo)
    run_responder.validate_response(document)
    assert document["action"] == "escalate"
    assert document["escalation"]["decision_required"]
    assert SENTINEL_TOKEN not in json.dumps(document)
    assert (
        SENTINEL_TOKEN
        not in (repo / "on-call-engineer/incidents" / f"{INCIDENT_ID}.md").read_text()
    )


def test_the_budget_kills_the_process_group_and_escalates(tmp_path: Path) -> None:
    repo, base_commit = make_repo(tmp_path)
    write_packet(repo, base_commit)
    fake = write_fake_responder(tmp_path, mode="slow", sleep=30)
    env = runner_env(tmp_path, fake, ONCALL_BUDGET_SECONDS="1")

    completed = invoke_runner(repo, env)

    assert completed.returncode == 0, completed.stderr
    document = record(repo)
    run_responder.validate_response(document)
    assert document["action"] == "escalate"
    assert document["timing"]["budget_seconds"] == 1
    assert document["timing"]["elapsed_seconds"] < 15
    assert document["escalation"]["decision_required"]
    assert document["changes"]["pr_url"] is None
    assert {item["rule_id"] for item in document["policy"]["decisions"]} == {"budget-exhausted"}
    # The responder was killed during its sleep: it never wrote the finished marker.
    assert json.loads((tmp_path / "probe.json").read_text())["phase"] == "started"


def test_the_budget_can_be_lowered_but_never_raised(tmp_path: Path) -> None:
    repo, base_commit = make_repo(tmp_path)
    write_packet(repo, base_commit)
    fake = write_fake_responder(tmp_path, mode="fix")
    env = runner_env(tmp_path, fake, ONCALL_BUDGET_SECONDS="100000")

    completed = invoke_runner(repo, env)

    assert completed.returncode == 0, completed.stderr
    assert record(repo)["timing"]["budget_seconds"] == 600
    assert "budget_clamped" in completed.stderr


def test_a_null_base_commit_escalates_without_guessing_or_branching(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path)
    write_packet(repo, None)
    fake = write_fake_responder(tmp_path, mode="fix")
    env = runner_env(tmp_path, fake)

    completed = invoke_runner(repo, env)

    assert completed.returncode == 0, completed.stderr
    document = record(repo)
    run_responder.validate_response(document)
    assert document["action"] == "escalate"
    assert "null" in document["escalation"]["decision_required"]
    assert document["changes"]["worktree"] is None
    assert not (repo / "worktrees").exists()
    assert not (tmp_path / "probe.json").exists()


@pytest.mark.parametrize("mode", ["silent", "invalid"])
def test_a_missing_or_invalid_response_escalates(tmp_path: Path, mode: str) -> None:
    repo, base_commit = make_repo(tmp_path)
    write_packet(repo, base_commit)
    fake = write_fake_responder(tmp_path, mode=mode)
    env = runner_env(tmp_path, fake)

    completed = invoke_runner(repo, env)

    assert completed.returncode == 0, completed.stderr
    document = record(repo)
    run_responder.validate_response(document)
    assert document["action"] == "escalate"
    assert document["escalation"]["decision_required"]


def test_a_fix_on_the_wrong_base_escalates(tmp_path: Path) -> None:
    repo, base_commit = make_repo(tmp_path)
    write_packet(repo, base_commit)
    fake = write_fake_responder(tmp_path, mode="fix", base_ref="develop")
    env = runner_env(tmp_path, fake)

    completed = invoke_runner(repo, env)

    assert completed.returncode == 0, completed.stderr
    document = record(repo)
    run_responder.validate_response(document)
    assert document["action"] == "escalate"
    assert "base" in document["escalation"]["decision_required"]
    assert document["changes"]["pr_url"] is None


def test_an_unset_responder_cmd_is_a_clear_error(tmp_path: Path) -> None:
    repo, base_commit = make_repo(tmp_path)
    write_packet(repo, base_commit)
    env = runner_env(tmp_path, Path("/nonexistent/responder.py"))
    del env["RESPONDER_CMD"]

    completed = invoke_runner(repo, env)

    assert completed.returncode == 2
    assert "RESPONDER_CMD" in completed.stderr
    assert not (repo / "on-call-engineer/incidents").exists()
    assert not (repo / "worktrees").exists()
