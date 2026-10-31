"""Minimal GitHub REST client on the standard library.

No third party HTTP dependency keeps the action fast to install and easy to audit.
The transport is injectable so tests run without network access.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sentinel import MARKER

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any]]
PAGE_SIZE = 100


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API {status}: {message[:300]}")
        self.status = status


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, Any]:
    if not url.startswith("https://"):
        raise ValueError("GitHub API calls must use https")
    request = urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raise GitHubError(err.code, err.read().decode("utf-8", "replace")) from err


class GitHubClient:
    def __init__(
        self,
        token: str,
        repository: str,
        api_url: str = "https://api.github.com",
        transport: Transport | None = None,
    ) -> None:
        if not token:
            raise ValueError("a GitHub token is required")
        if repository.count("/") != 1:
            raise ValueError("repository must look like owner/name")
        self.repository = repository
        self.api_url = api_url.rstrip("/")
        self._transport = transport or urllib_transport
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "changeset-sentinel",
        }

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self.api_url}/repos/{self.repository}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = dict(self._headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        status, data = self._transport(method, url, headers, body)
        if status >= 400:
            raise GitHubError(status, json.dumps(data))
        return data

    def _paginate(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            sep = "&" if "?" in path else "?"
            batch = self._request("GET", f"{path}{sep}per_page={PAGE_SIZE}&page={page}") or []
            items.extend(batch)
            if len(batch) < PAGE_SIZE:
                return items
            page += 1

    def list_comments(self, number: int) -> list[dict[str, Any]]:
        return self._paginate(f"/issues/{number}/comments")

    def upsert_comment(self, number: int, body: str, marker: str = MARKER) -> tuple[str, int]:
        """Create the sticky comment once, then keep editing it on every run."""
        for comment in self.list_comments(number):
            if marker in (comment.get("body") or ""):
                self._request("PATCH", f"/issues/comments/{comment['id']}", {"body": body})
                return "updated", int(comment["id"])
        created = self._request("POST", f"/issues/{number}/comments", {"body": body})
        return "created", int(created["id"])

    def list_labels(self, number: int) -> list[str]:
        return [label["name"] for label in self._paginate(f"/issues/{number}/labels")]

    def label_actor(self, number: int, label: str) -> str | None:
        """Login of the person who most recently applied `label`, for audit evidence."""
        actor = None
        for event in self._paginate(f"/issues/{number}/events"):
            if event.get("event") == "labeled" and (event.get("label") or {}).get("name") == label:
                actor = (event.get("actor") or {}).get("login")
        return actor


def pull_request_number(event_path: str | None = None) -> int | None:
    path = event_path or os.environ.get("GITHUB_EVENT_PATH")
    if not path or not Path(path).is_file():
        return None
    event = json.loads(Path(path).read_text(encoding="utf-8"))
    number = (event.get("pull_request") or {}).get("number") or event.get("number")
    return int(number) if number else None


def append_env_file(variable: str, text: str) -> bool:
    """Append to a GitHub Actions file such as GITHUB_STEP_SUMMARY or GITHUB_OUTPUT."""
    target = os.environ.get(variable)
    if not target:
        return False
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write(text if text.endswith("\n") else text + "\n")
    return True


def set_output(name: str, value: str) -> bool:
    return append_env_file("GITHUB_OUTPUT", f"{name}={value}")
