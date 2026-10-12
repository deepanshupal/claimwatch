import json

import pytest

from claimwatch.checkers import (
    DomainChecker,
    FederatedChecker,
    InstagramChecker,
    JsonProfileChecker,
    PublicIdentityChecker,
)
from claimwatch.models import Target


@pytest.fixture
def nested_body():
    # Below the transport size cap but beyond the decoder's recursion limit.
    return b"[" * 2000 + b"0" + b"]" * 2000


@pytest.mark.parametrize(
    "checker,target,request_path",
    [
        (JsonProfileChecker(), Target("github", "octocat"), "_request"),
        (PublicIdentityChecker(), Target("dev.to", "someone"), "_request"),
        (PublicIdentityChecker(), Target("bluesky", "someone.bsky.social"), "_request"),
        (DomainChecker(), Target("domain", "example.com"), "_request"),
        (FederatedChecker(), Target("mastodon", "someone@mastodon.social"), "_public_request"),
    ],
)
def test_nested_json_stays_unknown(monkeypatch, nested_body, checker, target, request_path):
    monkeypatch.setattr(
        "claimwatch.checkers._domain_endpoint", lambda name: "https://rdap.example/domain/" + name
    )
    monkeypatch.setattr(
        "claimwatch.checkers." + request_path, lambda *a, **k: (200, nested_body, {})
    )
    result = checker.check(target)
    assert result.status == "unknown"
    assert result.owner is None


def test_nested_rdap_negative_answer_stays_unknown(monkeypatch, nested_body):
    monkeypatch.setattr(
        "claimwatch.checkers._domain_endpoint", lambda name: "https://rdap.example/domain/" + name
    )
    monkeypatch.setattr("claimwatch.checkers._request", lambda *a, **k: (404, nested_body, {}))
    assert DomainChecker().check(Target("domain", "example.com")).status == "unknown"


def test_nested_instagram_payload_stays_unknown(monkeypatch, nested_body):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return nested_body

    class Opener:
        def open(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("urllib.request.build_opener", lambda *a: Opener())
    result = InstagramChecker(token="fixture-only").check(Target("instagram", "someone"))
    assert result.status == "unknown"
    assert result.owner is None


def test_nested_source_preserves_state_and_continues_watch(monkeypatch, tmp_path, nested_body):
    from claimwatch.core import run

    state = tmp_path / "state.json"
    previous = {"github:octocat": {"status": "taken", "owner": "583231", "evidence_version": 2}}
    state.write_text(json.dumps(previous))

    def request(url, **kwargs):
        if "github" in url:
            return 200, nested_body, {}
        return 200, json.dumps({"type_of": "user", "username": "someone", "id": 42}).encode(), {}

    monkeypatch.setattr("claimwatch.checkers._request", request)
    observations, events = run([Target("github", "octocat"), Target("dev.to", "someone")], state)
    assert [item.status for item in observations] == ["unknown", "taken"]
    assert json.loads(state.read_text())["github:octocat"] == previous["github:octocat"]
    assert len(events) == 1
    assert events[0].target.platform == "dev.to"
