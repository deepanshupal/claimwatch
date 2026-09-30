import socket

import pytest

from claimwatch.checkers import DomainChecker, checker_for
from claimwatch.models import Target


@pytest.fixture(autouse=True)
def registry_fixture(monkeypatch):
    monkeypatch.setattr(
        "claimwatch.checkers._domain_endpoint", lambda domain: "https://rdap.org/domain/" + domain
    )


def test_supported_platforms():
    platforms = [
        "domain",
        "github",
        "x",
        "instagram",
        "tiktok",
        "youtube",
        "linkedin",
        "reddit",
        "threads",
        "twitch",
        "pinterest",
        "snapchat",
        "bluesky",
        "mastodon",
        "telegram",
        "producthunt",
        "substack",
        "medium",
        "dev.to",
        "npm",
        "pypi",
        "dockerhub",
    ]
    for platform in platforms:
        assert checker_for(platform)


@pytest.mark.parametrize("error", [socket.EAI_AGAIN, socket.EAI_FAIL])
def test_domain_temporary_dns_failure_is_not_available(monkeypatch, error):
    monkeypatch.setattr("claimwatch.checkers._request", lambda url: (503, b"", {}))

    def fail_lookup(domain, port):
        raise socket.gaierror(error, "DNS lookup failed")

    monkeypatch.setattr(socket, "getaddrinfo", fail_lookup)
    observation = DomainChecker().check(Target("domain", "example.com"))
    assert observation.status == "unknown"
    assert "RDAP HTTP 503" in observation.detail


def test_domain_missing_dns_does_not_prove_registrability(monkeypatch):
    monkeypatch.setattr("claimwatch.checkers._request", lambda url: (503, b"", {}))

    def no_name(domain, port):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", no_name)
    observation = DomainChecker().check(Target("domain", "example.com"))
    assert observation.status == "unknown"


def test_domain_dns_alone_does_not_prove_registration(monkeypatch):
    monkeypatch.setattr("claimwatch.checkers._request", lambda url: (503, b"", {}))
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda domain, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 0))],
    )
    observation = DomainChecker().check(Target("domain", "example.com"))
    assert observation.status == "unknown"
