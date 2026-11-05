"""T5.3 (issue #48) AC1-AC6 as executable properties of the release workflow.

CI behaviour itself cannot run under pytest, so this pins the things the
criteria name: one tag of the exact shape, one build per run, the workflow's
own token, nothing published from a pull request, no mask over a failed push,
and no deploy step.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
WORKFLOW_TEXT = WORKFLOW_PATH.read_text(encoding="utf-8")

IMAGE = "ghcr.io/cancinoray/stockroom"
TAG_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{7}$")

# The fields buildx's `imagetools inspect` template input actually exposes
# (buildx util/imagetools/printers.go: tplInput). Anything else is a template
# error, and with `set -e` that turns the publish step red.
BUILDX_TOP_LEVEL_FIELDS = {"Name", "Manifest", "Image", "SBOM", "Provenance"}

DEPLOY_MARKERS = (
    "ssh ",
    "scp ",
    "kubectl",
    "helm ",
    "aws ",
    "gcloud",
    "az ",
    "flyctl",
    "railway",
    "render",
    "cloud run",
    "ecs",
    "webhook",
    "repository_dispatch",
)


def _workflow() -> dict[str, Any]:
    """Parse with BaseLoader so the `on:` key stays ``"on"`` instead of ``True``."""
    return yaml.load(WORKFLOW_TEXT, Loader=yaml.BaseLoader)


def _jobs() -> dict[str, dict[str, Any]]:
    return _workflow()["jobs"]


def _run_blocks(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(_run_blocks(job))


def _strings(node: Any) -> list[str]:
    """Every string value in a nested mapping/list, for marker searches."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        found: list[str] = []
        for key, value in node.items():
            found.append(str(key))
            found.extend(_strings(value))
        return found
    if isinstance(node, list):
        found = []
        for item in node:
            found.extend(_strings(item))
        return found
    return []


def test_release_tag_shape_is_the_documented_pattern() -> None:
    """AC1: UTC timestamp plus the first 7 hex characters of the commit."""
    derived = "20261105-174105-f4c2184"
    assert TAG_RE.match(derived)
    for wrong in ("latest", "main", "20261105-174105-F4C2184", "20261105-174105-f4c218"):
        assert not TAG_RE.match(wrong), wrong


def test_release_runs_on_push_to_main_and_on_dispatch() -> None:
    """AC1: the trigger set is push->main plus workflow_dispatch."""
    triggers = _workflow()["on"]
    assert isinstance(triggers, dict)
    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]


def test_tag_is_computed_once_and_echoed_to_the_summary() -> None:
    """AC1/AC2: one derivation, shared through GITHUB_ENV, in one place."""
    release = _jobs()["release"]
    blocks = _run_blocks(release)
    derivation = [block for block in blocks if "date -u +%Y%m%d-%H%M%S" in block]

    assert len(derivation) == 1, "the tag must be derived in exactly one step"
    assert "${GITHUB_SHA::7}" in derivation[0]
    assert "GITHUB_ENV" in derivation[0]
    assert "GITHUB_STEP_SUMMARY" in derivation[0]
    assert WORKFLOW_TEXT.count("date -u +%Y%m%d-%H%M%S") == 1


def test_image_is_built_once_per_run() -> None:
    """AC2: one build per event, one push of that same image, no `push: true`."""
    jobs = _jobs()
    builds = [
        (job_name, step)
        for job_name, job in jobs.items()
        for step in job["steps"]
        if "uses" in step and "build-push-action" in step["uses"]
    ]
    assert len(builds) == 2, "PR build and release build, mutually exclusive"

    gates = {job_name: jobs[job_name].get("if", "") for job_name, _ in builds}
    assert "pull_request" in gates["docker-build"]
    assert "push" in gates["release"] and "workflow_dispatch" in gates["release"]

    for _, step in builds:
        assert step["with"].get("push") != "true"
        assert step["with"].get("load") == "true"

    assert WORKFLOW_TEXT.count("docker push ") == 1
    assert "docker push " in _run_text(jobs["release"])


def test_publishing_uses_the_built_in_token_only() -> None:
    """AC3: job-level permissions plus `github.token`, no repository secret."""
    release = _jobs()["release"]
    assert release["permissions"] == {"contents": "read", "packages": "write"}
    assert "packages" not in _workflow()["permissions"]

    text = _run_text(release)
    assert 'echo "${{ github.token }}" | docker login ghcr.io' in text
    assert '-u "${{ github.actor }}"' in text
    assert "secrets." not in WORKFLOW_TEXT


def test_pull_requests_never_publish() -> None:
    """AC4: the publishing and its permission are unreachable from a PR."""
    jobs = _jobs()
    assert "pull_request" in jobs["docker-build"]["if"]
    release_if = jobs["release"]["if"]
    assert "github.event_name == 'push'" in release_if
    assert "github.event_name == 'workflow_dispatch'" in release_if
    assert "pull_request" not in release_if

    publishing = [name for name, job in jobs.items() if "packages" in job.get("permissions", {})]
    assert publishing == ["release"], "only the non-PR job may request packages: write"


def test_no_failed_push_can_be_masked() -> None:
    """AC6: no continue-on-error and no shell short-circuit around the push."""
    for job_name, job in _jobs().items():
        for step in job["steps"]:
            assert "continue-on-error" not in step, job_name
            run = step.get("run", "")
            for mask in ("|| true", "set +e"):
                assert mask not in run, f"{job_name}: {mask}"

    push_blocks = [block for block in _run_text(_jobs()["release"]).split("\n\n")]
    assert any("docker push " in block for block in push_blocks)
    for block in push_blocks:
        if "docker push " in block:
            assert "set -euo pipefail" in block


def test_buildx_template_fields_actually_exist() -> None:
    """AC2: the digest echo must not use a template field buildx does not have."""
    for match in re.finditer(r"imagetools\s+inspect[^\n]*?--format\s+'([^']*)'", WORKFLOW_TEXT):
        template = match.group(1)
        # A root field is a `.Name` that starts an action (``{{`` / pipe / space),
        # not the second half of a dotted path such as ``.Manifest.Digest``.
        roots = set(re.findall(r"(?:\{\{|\||\s)\.([A-Za-z_][A-Za-z0-9_]*)", template))
        unknown = roots - BUILDX_TOP_LEVEL_FIELDS
        assert not unknown, f"{template!r} uses non-existent buildx field(s): {unknown}"


def test_workflow_has_no_deploy_step() -> None:
    """AC5: the run ends at the pushed tag."""
    workflow = _workflow()
    for job_name, job in workflow["jobs"].items():
        assert "environment" not in job, job_name

    text = _run_text(workflow["jobs"]["release"]).lower()
    for marker in DEPLOY_MARKERS:
        assert marker not in text, marker
    assert "environment:" not in WORKFLOW_TEXT
