import json

import pytest

from claimwatch.checkers import (
    BestEffortProfileChecker,
    DomainChecker,
    FederatedChecker,
    JsonProfileChecker,
)
from claimwatch.models import Target


@pytest.fixture(autouse=True)
def registry_fixture(monkeypatch):
    monkeypatch.setattr(
        "claimwatch.checkers._domain_endpoint", lambda domain: "https://rdap.org/domain/" + domain
    )


def response(monkeypatch, status, data):
    monkeypatch.setattr(
        "claimwatch.checkers._request", lambda *a, **k: (status, json.dumps(data).encode(), {})
    )


@pytest.mark.parametrize(
    "data",
    [
        {},
        [],
        {"errorCode": 404},
        {"objectClassName": "entity"},
        {"objectClassName": "domain", "ldhName": "other.com"},
        {"objectClassName": "domain", "ldhName": "example.com", "events": [None]},
    ],
)
def test_rdap_invalid_record_is_not_taken(monkeypatch, data):
    response(monkeypatch, 200, data)
    assert DomainChecker().check(Target("domain", "example.com")).status == "unknown"


@pytest.mark.parametrize("status", [404, 403, 429, 500, 503])
def test_rdap_absence_or_failure_is_not_registrability(monkeypatch, status):
    response(monkeypatch, status, {"errorCode": status})
    assert DomainChecker().check(Target("domain", "reserved.com")).status == (
        "not_registered" if status == 404 else "unknown"
    )


@pytest.mark.parametrize(
    "domain",
    [
        "http://example.com",
        "a/b.com",
        "-bad.com",
        "x..com",
        "localhost",
        "1.2.3.4",
        "a" * 64 + ".com",
    ],
)
def test_invalid_domain_never_queries(monkeypatch, domain):
    def unexpected(*a, **k):
        pytest.fail("invalid input caused a network request")

    monkeypatch.setattr("claimwatch.checkers._request", unexpected)
    assert DomainChecker().check(Target("domain", domain)).status == "unknown"


def test_idn_normalization_matches_record(monkeypatch):
    def request(url, **kwargs):
        assert url.endswith("/xn--bcher-kva.de")
        return (
            200,
            json.dumps(
                {"objectClassName": "domain", "ldhName": "XN--BCHER-KVA.DE", "events": []}
            ).encode(),
            {},
        )

    monkeypatch.setattr("claimwatch.checkers._request", request)
    assert DomainChecker().check(Target("domain", "BÜCHER.de.")).status == "taken"


@pytest.mark.parametrize("platform", list(BestEffortProfileChecker.URLS))
@pytest.mark.parametrize("status", [200, 404, 302, 403, 429])
def test_html_status_alone_is_not_identity_or_availability(monkeypatch, platform, status):
    response(monkeypatch, status, {"login": "sign in"})
    assert BestEffortProfileChecker().check(Target(platform, "somebody")).status == "unknown"


@pytest.mark.parametrize("platform", ["github", "npm", "pypi", "dockerhub"])
@pytest.mark.parametrize("data", [{}, [], None, {"message": "challenge"}])
def test_api_wrong_payload_is_not_taken(monkeypatch, platform, data):
    response(monkeypatch, 200, data)
    assert JsonProfileChecker().check(Target(platform, "somebody")).status == "unknown"


@pytest.mark.parametrize("platform", ["github", "npm", "pypi", "dockerhub"])
def test_api_404_does_not_prove_name_is_claimable(monkeypatch, platform):
    response(monkeypatch, 404, {})
    assert JsonProfileChecker().check(Target(platform, "reserved")).status == "unknown"


def test_github_identity_must_match(monkeypatch):
    response(monkeypatch, 200, {"id": 1, "login": "someoneelse"})
    assert JsonProfileChecker().check(Target("github", "somebody")).status == "unknown"


def test_github_valid_identity(monkeypatch):
    response(
        monkeypatch,
        200,
        {"id": 583231, "login": "octocat", "html_url": "https://github.com/octocat"},
    )
    result = JsonProfileChecker().check(Target("github", "octocat"))
    assert result.status == "taken"
    assert result.owner == "583231"


@pytest.mark.parametrize("handle", ["../evil", "a/b", "name?x=y", "x#y", ""])
def test_invalid_handle_never_queries(monkeypatch, handle):
    def unexpected(*a, **k):
        pytest.fail("invalid input caused a request")

    monkeypatch.setattr("claimwatch.checkers._request", unexpected)
    assert JsonProfileChecker().check(Target("github", handle)).status == "unknown"


@pytest.mark.parametrize(
    "value",
    [
        "name@localhost",
        "name@127.0.0.1",
        "name@host:8080",
        "name@host/path",
        "name@169.254.169.254",
    ],
)
def test_mastodon_invalid_host_never_queries(monkeypatch, value):
    def unexpected(*a, **k):
        pytest.fail("unsafe instance queried")

    monkeypatch.setattr("claimwatch.checkers._request", unexpected)
    assert FederatedChecker().check(Target("mastodon", value)).status == "unknown"


def test_mastodon_missing_profile_is_not_claimable(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))],
    )
    response(monkeypatch, 404, {})
    assert (
        FederatedChecker().check(Target("mastodon", "reserved@mastodon.social")).status == "unknown"
    )


@pytest.mark.parametrize("platform,handle", [("instagram", "analoghouse"), ("x", "agentcommerce")])
@pytest.mark.parametrize("status", [200, 404, 429])
def test_reported_social_cases_never_infer_availability(monkeypatch, platform, handle, status):
    # Spellings are candidate variants of the user's phrases, not asserted exact identities.
    response(monkeypatch, status, {"message": "Sign in or not found"})
    assert BestEffortProfileChecker().check(Target(platform, handle)).status == "unknown"


def test_redirects_are_not_followed_and_cannot_leak_auth():
    import urllib.error
    import urllib.request

    from claimwatch.checkers import _NoRedirect

    request = urllib.request.Request(
        "https://api.github.com/users/octocat", headers={"Authorization": "Bearer test-only"}
    )
    assert (
        _NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://other.example/")
        is None
    )


@pytest.mark.parametrize("data", [[], None, {}, {"data": "bad"}, [None]])
def test_apify_malformed_data_is_unknown(monkeypatch, data):
    import io

    from claimwatch.checkers import InstagramChecker

    class Opener:
        def open(self, request, **kwargs):
            assert "token=" not in request.full_url
            assert request.get_header("Authorization") == "Bearer fixture-only"
            return io.BytesIO(json.dumps(data).encode())

    monkeypatch.setattr("urllib.request.build_opener", lambda *a: Opener())
    assert (
        InstagramChecker(token="fixture-only").check(Target("instagram", "analoghouse")).status
        == "unknown"
    )


def test_mastodon_private_dns_never_requested(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )

    def unexpected(*a, **k):
        pytest.fail("private address was queried")

    monkeypatch.setattr("claimwatch.checkers._request", unexpected)
    assert FederatedChecker().check(Target("mastodon", "name@private.example")).status == "unknown"


def test_domain_uses_registry_bootstrap(monkeypatch):
    from claimwatch import checkers

    monkeypatch.setattr(
        checkers,
        "_domain_endpoint",
        lambda domain: "https://rdap.verisign.com/com/v1/domain/" + domain,
    )

    def request(url, **kwargs):
        assert url == "https://rdap.verisign.com/com/v1/domain/example.com"
        return 200, json.dumps({"objectClassName": "domain", "ldhName": "example.com"}).encode(), {}

    monkeypatch.setattr(checkers, "_request", request)
    assert DomainChecker().check(Target("domain", "example.com")).status == "taken"


def test_domain_unsupported_registry_is_unknown(monkeypatch):
    from claimwatch import checkers

    def unsupported(domain):
        raise ValueError("No HTTPS RDAP bootstrap service for this TLD")

    monkeypatch.setattr(checkers, "_domain_endpoint", unsupported)
    assert DomainChecker().check(Target("domain", "example.unsupported")).status == "unknown"


def test_empty_authoritative_404_is_not_registered(monkeypatch):
    monkeypatch.setattr("claimwatch.checkers._request", lambda *a, **k: (404, b"", {}))
    assert DomainChecker().check(Target("domain", "example.com")).status == "not_registered"


@pytest.mark.parametrize(
    "payload", [b'{"errorCode":404}', b'{"errorCode":500}', b"<html>Not found</html>"]
)
def test_no_record_needs_valid_rdap_error(monkeypatch, payload):
    monkeypatch.setattr("claimwatch.checkers._request", lambda *a, **k: (404, payload, {}))
    result = DomainChecker().check(Target("domain", "example.com"))
    assert result.status == ("not_registered" if payload == b'{"errorCode":404}' else "unknown")


def test_idna_deviation_is_not_silently_rewritten(monkeypatch):
    def request(url, **kwargs):
        assert url.endswith("/xn--fa-hia.de")
        return 200, json.dumps({"objectClassName": "domain", "ldhName": "fass.de"}).encode(), {}

    monkeypatch.setattr("claimwatch.checkers._request", request)
    assert DomainChecker().check(Target("domain", "faß.de")).status == "unknown"


def test_mastodon_requires_id_and_local_identity(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))],
    )
    response(monkeypatch, 200, {"id": "1", "username": "name", "acct": "name@remote.example"})
    assert FederatedChecker().check(Target("mastodon", "name@mastodon.social")).status == "unknown"


def test_mastodon_connection_pins_ip_and_keeps_tls_host(monkeypatch):
    import socket

    from claimwatch.checkers import _public_request

    lookups = []

    def resolve(*args, **kwargs):
        lookups.append(args[0])
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    class Socket:
        def settimeout(self, timeout):
            pass

        def connect(self, address):
            assert address == ("1.1.1.1", 443)

    monkeypatch.setattr(socket, "socket", lambda *a: Socket())

    class Response:
        status = 200

        def __init__(self):
            self.headers = {}

        def read(self, limit):
            return b"{}"

    class Connection:
        def __init__(self, host, **kwargs):
            assert host == "mastodon.social"

        def request(self, *args, **kwargs):
            self._create_connection(("mastodon.social", 443), 12)

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    assert _public_request("https://mastodon.social/api/v1/accounts/lookup?acct=name")[0] == 200
    assert lookups == ["mastodon.social"]
