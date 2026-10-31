"""Supply chain guard for GitHub Actions.

Every `uses:` reference in workflows and composite actions must point at an
approved action and be pinned to a version tag or a full commit SHA.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SHA_PIN = re.compile(r"^[0-9a-f]{40}$")


class _Loader(yaml.SafeLoader):
    """Safe loader that tolerates CloudFormation short tags such as !Ref."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)

TAG_PIN = re.compile(r"^v?\d+(\.\d+){0,2}$")


@dataclass(frozen=True)
class Policy:
    allowed: tuple[str, ...]
    pinning: str = "tag-or-sha"
    allow_local: bool = True
    allow_docker: bool = False

    @classmethod
    def load(cls, path: str | Path) -> Policy:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        pinning = str(data.get("pinning", "tag-or-sha"))
        if pinning not in {"tag-or-sha", "sha"}:
            raise ValueError("pinning must be tag-or-sha or sha")
        return cls(
            allowed=tuple(str(a) for a in data.get("allowed") or ()),
            pinning=pinning,
            allow_local=bool(data.get("allow_local", True)),
            allow_docker=bool(data.get("allow_docker", False)),
        )


@dataclass(frozen=True)
class Violation:
    file: str
    uses: str
    problem: str


@dataclass
class Report:
    checked: int = 0
    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def _collect_uses(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                found.append(value.strip())
            else:
                found.extend(_collect_uses(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_collect_uses(item))
    return found


def _is_allowed(action: str, allowed: tuple[str, ...]) -> bool:
    owner_repo = "/".join(action.split("/")[:2])
    for entry in allowed:
        pattern = entry.strip().rstrip("/")
        if fnmatch.fnmatchcase(action, pattern) or fnmatch.fnmatchcase(owner_repo, pattern):
            return True
        if action.startswith(pattern + "/"):
            return True
    return False


def check_reference(uses: str, policy: Policy) -> str | None:
    """Return a problem description, or None when the reference is fine."""
    if uses.startswith("./"):
        return None if policy.allow_local else "local actions are not allowed"
    if uses.startswith("docker://"):
        return None if policy.allow_docker else "docker:// actions are not allowed"
    if "@" not in uses:
        return "not pinned: add @<version tag> or @<commit sha>"
    action, ref = uses.rsplit("@", 1)
    if not _is_allowed(action, policy.allowed):
        return f"{action} is not on the approved list"
    if SHA_PIN.match(ref):
        return None
    if policy.pinning == "sha":
        return f"ref {ref} must be a full 40 character commit SHA"
    if TAG_PIN.match(ref):
        return None
    return f"ref {ref} is a branch or unknown ref; pin a version tag or commit SHA"


def _candidate_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(p for p in path.rglob("*.y*ml") if p.suffix in {".yml", ".yaml"}))
    return files


def _is_actions_file(path: Path, data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if path.name in {"action.yml", "action.yaml"}:
        return True
    return "jobs" in data


def scan(paths: list[str], policy: Policy) -> Report:
    report = Report()
    for file in _candidate_files(paths):
        try:
            data = yaml.load(file.read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506
        except yaml.YAMLError as exc:
            report.violations.append(Violation(str(file), "-", f"invalid YAML: {exc}"))
            continue
        if not _is_actions_file(file, data):
            continue
        for uses in _collect_uses(data):
            report.checked += 1
            problem = check_reference(uses, policy)
            if problem:
                report.violations.append(Violation(str(file), uses, problem))
    return report
