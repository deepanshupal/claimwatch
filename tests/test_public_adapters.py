import json

import pytest

from claimwatch.checkers import checker_for
from claimwatch.models import Target


@pytest.mark.parametrize(
    "platform,name,data,owner",
    [
        (
            "bluesky",
            "bsky.app",
            {"did": "did:plc:z72i7hdynmk6r22z27h6tvur", "handle": "bsky.app"},
            "did:plc:z72i7hdynmk6r22z27h6tvur",
        ),
        ("dev.to", "ben", {"type_of": "user", "id": 1, "username": "ben"}, "1"),
        ("devto", "ben", {"type_of": "user", "id": 1, "username": "ben"}, "1"),
    ],
)
def test_public_api_exact_identity_is_taken(monkeypatch, platform, name, data, owner):
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        return 200, json.dumps(data).encode(), {}

    monkeypatch.setattr("claimwatch.checkers._request", request)
    result = checker_for(platform).check(Target(platform, name))
    assert result.status == "taken"
    assert result.owner == owner
    assert calls


@pytest.mark.parametrize("platform,name", [("bluesky", "bsky.app"), ("devto", "ben")])
@pytest.mark.parametrize(
    "status,data",
    [
        (404, {}),
        (429, {}),
        (200, {}),
        (200, {"error": "blocked"}),
        (200, {"did": "did:plc:abc", "handle": "other.example"}),
        (200, {"type_of": "user", "id": True, "username": "ben"}),
    ],
)
def test_absence_and_wrong_identity_stay_unknown(monkeypatch, platform, name, status, data):
    monkeypatch.setattr(
        "claimwatch.checkers._request", lambda *a, **k: (status, json.dumps(data).encode(), {})
    )
    assert checker_for(platform).check(Target(platform, name)).status == "unknown"


def test_bluesky_handle_resolution_mismatch_is_unknown(monkeypatch):
    def request(url, **kwargs):
        data = {"did": "did:plc:z72i7hdynmk6r22z27h6tvur", "handle": "bsky.app"}
        if "resolveHandle" in url:
            data = {"did": "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"}
        return 200, json.dumps(data).encode(), {}

    monkeypatch.setattr("claimwatch.checkers._request", request)
    assert checker_for("bluesky").check(Target("bluesky", "bsky.app")).status == "unknown"


@pytest.mark.parametrize("name", ["bsky.app/path", "localhost", "bsky.app?x=1", "a@bsky.app"])
def test_invalid_bluesky_handles_never_query(monkeypatch, name):
    monkeypatch.setattr("claimwatch.checkers._request", lambda *a, **k: pytest.fail("queried"))
    assert checker_for("bluesky").check(Target("bluesky", name)).status == "unknown"


def test_dockerhub_user_does_not_require_mastodon_acct(monkeypatch):
    payload = {"id": "5eeadadf871c4ee59181db058c6dfbb1", "username": "deepanshu", "type": "User"}
    monkeypatch.setattr(
        "claimwatch.checkers._request", lambda *a, **k: (200, json.dumps(payload).encode(), {})
    )
    result = checker_for("dockerhub").check(Target("dockerhub", "deepanshu"))
    assert result.status == "taken"
    assert result.owner == payload["id"]
