import json

import pytest

from claimwatch.checkers import checker_for
from claimwatch.models import Target


@pytest.mark.parametrize("platform", ["dockerhub", "docker"])
def test_docker_namespace_redirect_resolves_matching_org(monkeypatch, platform):
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        if "/users/" in url:
            return 308, b"", {"location": "/v2/orgs/library"}
        return (
            200,
            json.dumps(
                {
                    "id": "33ef574274c011e4bea40242ac11001b",
                    "orgname": "library",
                    "type": "Organization",
                }
            ).encode(),
            {},
        )

    monkeypatch.setattr("claimwatch.checkers._request", request)
    result = checker_for(platform).check(Target(platform, "library"))
    assert result.status == "taken"
    assert result.owner == "33ef574274c011e4bea40242ac11001b"
    assert result.evidence_url == "https://hub.docker.com/v2/orgs/library/"
    assert calls == [
        "https://hub.docker.com/v2/users/library/",
        "https://hub.docker.com/v2/orgs/library/",
    ]


@pytest.mark.parametrize(
    "location",
    [
        None,
        "/v2/orgs/other",
        "https://evil.example/v2/orgs/library",
        "//evil.example/v2/orgs/library",
        "/v2/orgs/library?x=1",
    ],
)
def test_unexpected_redirect_never_followed(monkeypatch, location):
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        return 308, b"", {"Location": location} if location else {}

    monkeypatch.setattr("claimwatch.checkers._request", request)
    assert checker_for("dockerhub").check(Target("dockerhub", "library")).status == "unknown"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,payload",
    [
        (404, {}),
        (403, {}),
        (429, {}),
        (308, {}),
        (200, {"id": "a", "orgname": "other", "type": "Organization"}),
        (200, {"id": "", "orgname": "library", "type": "Organization"}),
        (200, {"id": True, "orgname": "library", "type": "Organization"}),
        (200, {"id": "a", "orgname": "library", "type": "User"}),
        (200, {"id": "a", "orgname": "library"}),
        (200, {"error": "denied"}),
    ],
)
def test_org_absence_or_mismatched_identity_stays_unknown(monkeypatch, status, payload):
    def request(url, **kwargs):
        if "/users/" in url:
            return 308, b"", {"Location": "/v2/orgs/library"}
        return status, json.dumps(payload).encode(), {}

    monkeypatch.setattr("claimwatch.checkers._request", request)
    assert checker_for("dockerhub").check(Target("dockerhub", "library")).status == "unknown"
