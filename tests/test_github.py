import json

import pytest

from sentinel import MARKER
from sentinel.github import (
    PAGE_SIZE,
    GitHubClient,
    GitHubError,
    append_env_file,
    pull_request_number,
)


class FakeTransport:
    """Records requests and replays canned responses keyed by method and path."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers, body):
        path = url.split("/repos/owner/repo", 1)[1]
        self.calls.append((method, path, json.loads(body) if body else None))
        for (m, prefix), response in self.routes.items():
            if m == method and path.startswith(prefix):
                return response(path) if callable(response) else response
        return 404, {"message": "not found"}


def client(routes):
    transport = FakeTransport(routes)
    return GitHubClient("token", "owner/repo", transport=transport), transport


def test_creates_comment_when_none_exists():
    gh, t = client(
        {
            ("GET", "/issues/7/comments"): (200, [{"id": 1, "body": "unrelated"}]),
            ("POST", "/issues/7/comments"): (201, {"id": 99}),
        }
    )
    assert gh.upsert_comment(7, f"{MARKER}\nreport") == ("created", 99)
    assert t.calls[-1] == ("POST", "/issues/7/comments", {"body": f"{MARKER}\nreport"})


def test_updates_sticky_comment_found_on_second_page():
    page1 = [{"id": i, "body": "noise"} for i in range(PAGE_SIZE)]
    page2 = [{"id": 555, "body": f"{MARKER}\nold report"}]

    def comments(path):
        return (200, page2 if "page=2" in path else page1)

    gh, t = client(
        {
            ("GET", "/issues/7/comments"): comments,
            ("PATCH", "/issues/comments/555"): (200, {"id": 555}),
        }
    )
    assert gh.upsert_comment(7, f"{MARKER}\nnew report") == ("updated", 555)
    assert not any(m == "POST" for m, _, _ in t.calls)


def test_labels_and_label_actor():
    events = [
        {"event": "labeled", "label": {"name": "risk-accepted"}, "actor": {"login": "first"}},
        {"event": "unlabeled", "label": {"name": "risk-accepted"}, "actor": {"login": "first"}},
        {"event": "labeled", "label": {"name": "risk-accepted"}, "actor": {"login": "lead-eng"}},
        {"event": "labeled", "label": {"name": "infra"}, "actor": {"login": "bot"}},
    ]
    gh, _ = client(
        {
            ("GET", "/issues/7/labels"): (200, [{"name": "risk-accepted"}, {"name": "infra"}]),
            ("GET", "/issues/7/events"): (200, events),
        }
    )
    assert gh.list_labels(7) == ["risk-accepted", "infra"]
    assert gh.label_actor(7, "risk-accepted") == "lead-eng"


def test_error_status_raises():
    gh, _ = client({("GET", "/issues/7/labels"): (403, {"message": "forbidden"})})
    with pytest.raises(GitHubError, match="403"):
        gh.list_labels(7)


def test_client_validates_inputs():
    with pytest.raises(ValueError, match="token"):
        GitHubClient("", "owner/repo")
    with pytest.raises(ValueError, match="owner/name"):
        GitHubClient("t", "just-a-name")


def test_pull_request_number_from_event(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 42}}))
    assert pull_request_number(str(event)) == 42
    assert pull_request_number(str(tmp_path / "missing.json")) is None


def test_append_env_file(tmp_path, monkeypatch):
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    assert append_env_file("GITHUB_STEP_SUMMARY", "hello")
    assert target.read_text() == "hello\n"
    monkeypatch.delenv("GITHUB_STEP_SUMMARY")
    assert not append_env_file("GITHUB_STEP_SUMMARY", "x")
