import http.client

import pytest

from claimwatch.checkers import (
    DomainChecker,
    FederatedChecker,
    InstagramChecker,
    JsonProfileChecker,
    PublicIdentityChecker,
)
from claimwatch.models import Target


@pytest.mark.parametrize(
    "error",
    [http.client.IncompleteRead(b"partial", 10), http.client.BadStatusLine("bad")],
)
@pytest.mark.parametrize(
    "checker,target,request_path",
    [
        (JsonProfileChecker(), Target("github", "octocat"), "_request"),
        (PublicIdentityChecker(), Target("dev.to", "someone"), "_request"),
        (PublicIdentityChecker(), Target("bluesky", "someone.bsky.social"), "_request"),
        (DomainChecker(), Target("domain", "example.com"), "_request"),
        (
            FederatedChecker(),
            Target("mastodon", "someone@mastodon.social"),
            "_public_request",
        ),
    ],
)
def test_http_protocol_failure_stays_unknown(monkeypatch, error, checker, target, request_path):
    monkeypatch.setattr(
        "claimwatch.checkers._domain_endpoint", lambda name: "https://rdap.example/domain/" + name
    )

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("claimwatch.checkers." + request_path, fail)
    result = checker.check(target)
    assert result.status == "unknown"
    assert result.owner is None


@pytest.mark.parametrize(
    "error",
    [http.client.IncompleteRead(b"partial", 10), http.client.BadStatusLine("bad")],
)
def test_configured_instagram_protocol_failure_stays_unknown(monkeypatch, error):
    class BrokenOpener:
        def open(self, *args, **kwargs):
            raise error

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: BrokenOpener())
    result = InstagramChecker(token="fixture-only").check(Target("instagram", "someone"))
    assert result.status == "unknown"
    assert result.owner is None


def test_truncated_source_does_not_abort_other_targets_or_erase_state(monkeypatch, tmp_path):
    import json

    from claimwatch.core import run

    state = tmp_path / "state.json"
    previous = {
        "github:octocat": {
            "status": "taken",
            "owner": "583231",
            "evidence_version": 2,
        }
    }
    state.write_text(json.dumps(previous))

    def request(url, **kwargs):
        if "github" in url:
            raise http.client.IncompleteRead(b"partial", 10)
        return 200, json.dumps({"type_of": "user", "username": "someone", "id": 42}).encode(), {}

    monkeypatch.setattr("claimwatch.checkers._request", request)
    observations, events = run([Target("github", "octocat"), Target("dev.to", "someone")], state)
    assert [item.status for item in observations] == ["unknown", "taken"]
    assert json.loads(state.read_text())["github:octocat"] == previous["github:octocat"]
    assert len(events) == 1
    assert events[0].target.platform == "dev.to"
