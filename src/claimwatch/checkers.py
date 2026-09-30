from __future__ import annotations

import http.client
import ipaddress
import json
import os
import queue
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any, ClassVar

from .models import Observation, Target

USER_AGENT = "claimwatch/0.2 (+https://github.com/DeepanshuPal/claimwatch)"


def _domain(value: str) -> str:
    import idna

    name = idna.encode(
        value.strip().lower().removesuffix("."), uts46=True, transitional=False
    ).decode("ascii")
    if len(name) > 253 or "." not in name:
        raise ValueError("Use a complete DNS domain name")
    try:
        ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        raise ValueError("An IP address is not a domain name")
    if any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in name.split(".")
    ):
        raise ValueError("Invalid domain label")
    return name


def _handle(value: str, platform: str) -> str:
    name = value.strip()
    if platform != "npm":
        name = name.removeprefix("@")
    pattern = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}"
    if platform == "npm" and name.startswith("@"):
        pattern = r"@[a-z0-9_.-]+/[a-z0-9_.-]+"
    if not re.fullmatch(pattern, name) or ".." in name:
        raise ValueError("Invalid handle or package name")
    if platform in {"github", "substack"} and not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", name
    ):
        raise ValueError("Invalid handle for this platform")
    return name


def _unknown(target: Target, detail: str, url: str | None = None) -> Observation:
    return Observation(target, "unknown", detail=detail, evidence_url=url)


def _object(body: bytes) -> dict[str, Any]:
    data = json.loads(body)
    if not isinstance(data, dict) or data.get("errorCode") or data.get("error"):
        raise ValueError("Source did not return a valid identity record")
    return data


@lru_cache(maxsize=1)
def _bootstrap() -> list:
    status, body, _ = _request("https://data.iana.org/rdap/dns.json")
    data = _object(body)
    if status != 200 or not isinstance(data.get("services"), list):
        raise ValueError("IANA RDAP bootstrap is unavailable")
    return data["services"]


def _domain_endpoint(domain: str) -> str:
    for service in _bootstrap():
        if not isinstance(service, list) or len(service) != 2:
            continue
        tlds, endpoints = service
        if not isinstance(tlds, list) or not isinstance(endpoints, list):
            continue
        if domain.rsplit(".", 1)[-1] not in tlds:
            continue
        for endpoint in endpoints:
            if not isinstance(endpoint, str):
                continue
            parsed = urllib.parse.urlsplit(endpoint)
            if (
                parsed.scheme == "https"
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment
            ):
                _domain(parsed.hostname)
                return endpoint.rstrip("/") + "/domain/" + urllib.parse.quote(domain, safe="")
    raise ValueError(
        "No HTTPS RDAP bootstrap service for this TLD; WHOIS absence is not proof of availability"
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(
    url: str, *, timeout: int = 12, headers: dict[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("Source response exceeds size limit")
            return response.status, body, dict(response.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Source response exceeds size limit")
        return exc.code, body, dict(exc.headers)


def _public_request(url: str) -> tuple[int, bytes, dict[str, str]]:
    """Pin an HTTPS connection to validated public IPs, retaining TLS hostname checks."""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname
    answers: queue.Queue = queue.Queue(maxsize=1)

    def resolve():
        try:
            answers.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError as exc:
            answers.put(exc)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses = answers.get(timeout=12)
    except queue.Empty:
        raise OSError("DNS lookup timed out") from None
    if isinstance(addresses, Exception):
        raise addresses
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Mastodon instance must resolve only to public addresses")

    def connect(address, timeout=None, source_address=None):
        # Never resolve host again: this closes the DNS-rebinding window.
        last_error = None
        for family, kind, proto, _, sockaddr in addresses:
            sock = socket.socket(family, kind, proto)
            sock.settimeout(timeout)
            try:
                sock.connect(sockaddr)
                return sock
            except OSError as exc:
                sock.close()
                last_error = exc
        raise last_error or OSError("Cannot connect to instance")

    connection = http.client.HTTPSConnection(host, timeout=12)
    connection._create_connection = connect
    try:
        connection.request(
            "GET",
            parsed.path + "?" + parsed.query,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        response = connection.getresponse()
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Source response exceeds size limit")
        return response.status, body, dict(response.headers)
    finally:
        connection.close()


class Checker(ABC):
    @abstractmethod
    def check(self, target: Target) -> Observation: ...


class JsonProfileChecker(Checker):
    ENDPOINTS: ClassVar[dict[str, tuple[str, str]]] = {
        "github": ("https://api.github.com/users/{handle}", "html_url"),
        "npm": ("https://registry.npmjs.org/{handle}", "homepage"),
        "pypi": ("https://pypi.org/pypi/{handle}/json", "package_url"),
        "dockerhub": ("https://hub.docker.com/v2/users/{handle}/", "profile_url"),
        "docker": ("https://hub.docker.com/v2/users/{handle}/", "profile_url"),
    }

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def check(self, target: Target) -> Observation:
        platform = target.platform.lower()
        url = None
        try:
            handle = _handle(target.value, platform)
            template, _ = self.ENDPOINTS[platform]
            url = template.format(handle=urllib.parse.quote(handle, safe=""))
            headers = {}
            if platform == "github":
                headers = {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"
            status, body, _ = _request(url, headers=headers)
            if status != 200:
                return _unknown(
                    target,
                    f"{platform} API HTTP {status}; missing records do not prove a name is claimable",
                    url,
                )
            data = _object(body)
            if platform == "github":
                if (
                    not isinstance(data.get("id"), int)
                    or isinstance(data.get("id"), bool)
                    or data["id"] <= 0
                    or not isinstance(data.get("login"), str)
                    or data["login"].lower() != handle.lower()
                ):
                    return _unknown(target, "API response is not a matching GitHub account", url)
                return Observation(
                    target,
                    "taken",
                    owner=str(data["id"]),
                    last_activity=data.get("updated_at")
                    if isinstance(data.get("updated_at"), str)
                    else None,
                    detail=f"Verified GitHub account login={data['login']}",
                    evidence_url=f"https://github.com/{urllib.parse.quote(handle, safe='')}",
                )
            if platform == "pypi":
                info = data.get("info")
                normalize = lambda n: re.sub(r"[-_.]+", "-", n).lower()
                if (
                    not isinstance(info, dict)
                    or not isinstance(info.get("name"), str)
                    or normalize(info["name"]) != normalize(handle)
                ):
                    return _unknown(target, "API response is not a matching PyPI package", url)
                # Package authors are not stable owner IDs; versions are not activity dates.
                return Observation(
                    target,
                    "taken",
                    detail=f"Verified PyPI package; latest={info.get('version', 'unknown')}",
                    evidence_url=f"https://pypi.org/project/{urllib.parse.quote(handle, safe='')}/",
                )
            if platform == "npm":
                if data.get("name") != handle or not isinstance(data.get("versions"), dict):
                    return _unknown(target, "API response is not a matching npm package", url)
                return Observation(
                    target,
                    "taken",
                    detail="Verified npm package record",
                    evidence_url=f"https://www.npmjs.com/package/{urllib.parse.quote(handle, safe='')}",
                )
            if (
                not isinstance(data.get("username"), str)
                or data["username"].lower() != handle.lower()
                or not isinstance(data.get("id"), str)
                or not data["id"]
            ):
                return _unknown(target, "API response is not a matching Docker Hub user", url)
            return Observation(
                target,
                "taken",
                owner=str(data["id"]),
                detail="Verified Docker Hub user",
                evidence_url=f"https://hub.docker.com/u/{urllib.parse.quote(handle, safe='')}",
            )
        except (OSError, ValueError, TypeError) as exc:
            return _unknown(target, f"Cannot verify {platform} record: {exc}", url)


class PublicIdentityChecker(Checker):
    """Read exact account identities from public provider-owned JSON APIs."""

    def check(self, target: Target) -> Observation:
        platform = target.platform.lower()
        url = None
        try:
            if platform == "bluesky":
                # Bluesky names are full DNS handles, including custom domains.
                name = _domain(target.value.strip().removeprefix("@"))
                url = (
                    "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor="
                    + urllib.parse.quote(name, safe="")
                )
            else:
                name = _handle(target.value, platform)
                url = "https://dev.to/api/users/by_username?url=" + urllib.parse.quote(
                    name, safe=""
                )
            status, body, _ = _request(url)
            if status != 200:
                return _unknown(
                    target, f"Public identity API HTTP {status}; absence is not claimability", url
                )
            data = _object(body)
            if platform == "bluesky":
                did = data.get("did")
                if (
                    not isinstance(data.get("handle"), str)
                    or data["handle"].lower() != name
                    or not isinstance(did, str)
                    or not re.fullmatch(r"did:(?:plc:[a-z2-7]{24}|web:[A-Za-z0-9._%:-]+)", did)
                ):
                    return _unknown(
                        target, "Bluesky API did not return a matching handle and DID", url
                    )
                lookup = (
                    "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle="
                    + urllib.parse.quote(name, safe="")
                )
                code, identity, _ = _request(lookup)
                if code != 200 or _object(identity).get("did") != did:
                    return _unknown(
                        target, "Bluesky handle resolution did not match the profile DID", url
                    )
                return Observation(
                    target,
                    "taken",
                    owner=did,
                    detail="Matching Bluesky profile and handle-resolution DID",
                    evidence_url=url,
                )
            account_id = data.get("id")
            if (
                data.get("type_of") != "user"
                or not isinstance(account_id, int)
                or isinstance(account_id, bool)
                or account_id <= 0
                or not isinstance(data.get("username"), str)
                or data["username"].lower() != name.lower()
            ):
                return _unknown(target, "DEV API did not return a matching user identity", url)
            return Observation(
                target,
                "taken",
                owner=str(account_id),
                detail="Matching DEV public user ID and username",
                evidence_url=url,
            )
        except (OSError, ValueError, TypeError) as exc:
            return _unknown(target, f"Cannot verify public identity: {exc}", url)


class DomainChecker(Checker):
    def check(self, target: Target) -> Observation:
        url = None
        try:
            domain = _domain(target.value)
            url = _domain_endpoint(domain)
            status, body, _ = _request(url)
            if status == 404:
                # RFC 7480 section 5.3 permits an empty negative-answer body.
                data = json.loads(body) if body.strip() else None
                if not body.strip() or (isinstance(data, dict) and data.get("errorCode") == 404):
                    return Observation(
                        target,
                        "not_registered",
                        detail="Authoritative registry RDAP reports no record. Reserved, premium or policy restrictions may still prevent registration; confirm with a registrar.",
                        evidence_url=url,
                    )
            if status != 200:
                return _unknown(
                    target,
                    f"RDAP HTTP {status}; no verified registration record. Absence does not prove registrability; check a registrar.",
                    url,
                )
            data = _object(body)
            record_name = data.get("ldhName") or data.get("unicodeName")
            if (
                data.get("objectClassName") != "domain"
                or not isinstance(record_name, str)
                or _domain(record_name) != domain
            ):
                return _unknown(
                    target, "RDAP response is not a matching domain registration record", url
                )
            raw_events = data.get("events", [])
            if not isinstance(raw_events, list) or any(not isinstance(e, dict) for e in raw_events):
                return _unknown(target, "RDAP returned malformed registration events", url)
            events = {
                e.get("eventAction"): e.get("eventDate")
                for e in raw_events
                if isinstance(e.get("eventAction"), str) and isinstance(e.get("eventDate"), str)
            }
            return Observation(
                target,
                "taken",
                last_activity=events.get("last changed") or events.get("registration"),
                detail=f"Matching RDAP registration record; expiration={events.get('expiration', 'unknown')}; registration is not an offer for sale",
                evidence_url=url,
            )
        except (OSError, ValueError, TypeError) as exc:
            return _unknown(target, f"Cannot verify domain registration: {exc}", url)


class InstagramChecker(Checker):
    """Use Apify when configured; otherwise return an inconclusive public-page signal."""

    ACTOR = "apify~instagram-profile-scraper"

    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.getenv("APIFY_TOKEN")

    def check(self, target: Target) -> Observation:
        try:
            handle = _handle(target.value, "instagram")
        except ValueError as exc:
            return _unknown(target, str(exc))
        profile_url = f"https://www.instagram.com/{urllib.parse.quote(handle)}/"
        if not self.token:
            return BestEffortProfileChecker().check(target)
        url = f"https://api.apify.com/v2/acts/{self.ACTOR}/run-sync-get-dataset-items"
        payload = json.dumps({"usernames": [handle], "resultsLimit": 1}).encode()
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Authorization": f"Bearer {self.token}",
            },
            method="POST",
        )
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=90) as response:
                items = json.loads(response.read())
            if (
                isinstance(items, list)
                and items
                and isinstance(items[0], dict)
                and not items[0].get("error")
                and items[0].get("id")
                and isinstance(items[0].get("username"), str)
                and items[0]["username"].lower() == handle.lower()
            ):
                item = items[0]
                owner = str(item.get("id") or item.get("username") or handle.lower())
                activity = item.get("latestPostTimestamp") or item.get("latestIgtvVideoTimestamp")
                return Observation(
                    target,
                    "taken",
                    owner=owner,
                    last_activity=activity if isinstance(activity, str) else None,
                    detail="Profile found through configured Apify Instagram scraper",
                    evidence_url=profile_url,
                )
            return Observation(
                target,
                "unknown",
                detail="Apify returned no profile record; absence is not enough to claim availability",
                evidence_url=profile_url,
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return Observation(
                target,
                "unknown",
                detail="Configured Instagram source failed; no verified profile",
                evidence_url=profile_url,
            )


class BestEffortProfileChecker(Checker):
    URLS: ClassVar[dict[str, str]] = {
        "x": "https://x.com/{handle}",
        "twitter": "https://x.com/{handle}",
        "instagram": "https://www.instagram.com/{handle}/",
        "tiktok": "https://www.tiktok.com/@{handle}",
        "youtube": "https://www.youtube.com/@{handle}",
        "linkedin": "https://www.linkedin.com/in/{handle}",
        "reddit": "https://www.reddit.com/user/{handle}/about.json",
        "threads": "https://www.threads.net/@{handle}",
        "twitch": "https://www.twitch.tv/{handle}",
        "pinterest": "https://www.pinterest.com/{handle}/",
        "snapchat": "https://www.snapchat.com/add/{handle}",
        "bluesky": "https://bsky.app/profile/{handle}",
        "telegram": "https://t.me/{handle}",
        "producthunt": "https://www.producthunt.com/@{handle}",
        "substack": "https://{handle}.substack.com/",
        "medium": "https://medium.com/@{handle}",
        "devto": "https://dev.to/{handle}",
        "dev.to": "https://dev.to/{handle}",
    }

    def check(self, target: Target) -> Observation:
        platform = target.platform.lower()
        try:
            handle = _handle(target.value, platform)
            url = self.URLS[platform].format(handle=urllib.parse.quote(handle, safe=""))
        except ValueError as exc:
            return _unknown(target, str(exc))
        # Generic HTML can be a login page, soft 404, challenge or redirect.
        # Do not spend a request on a source that cannot prove either state.
        return _unknown(
            target,
            "Public profile pages do not verify identity or claimability. Check the platform directly.",
            url,
        )


class FederatedChecker(Checker):
    def check(self, target: Target) -> Observation:
        url = None
        try:
            value = target.value.strip().removeprefix("@")
            handle, instance = value.rsplit("@", 1)
            handle = _handle(handle, "mastodon")
            instance = _domain(instance)
            url = f"https://{instance}/api/v1/accounts/lookup?acct={urllib.parse.quote(handle, safe='')}"
            status, body, _ = _public_request(url)
            if status != 200:
                return _unknown(
                    target,
                    f"Mastodon HTTP {status}; missing accounts may be reserved or deleted",
                    url,
                )
            data = _object(body)
            if (
                not isinstance(data.get("username"), str)
                or data["username"].lower() != handle.lower()
                or not isinstance(data.get("acct"), str)
                or data["acct"].lower() != handle.lower()
                or not isinstance(data.get("id"), str)
                or not data["id"]
            ):
                return _unknown(target, "Instance response is not a matching Mastodon account", url)
            return Observation(
                target,
                "taken",
                owner=str(data["id"]),
                last_activity=data.get("last_status_at")
                if isinstance(data.get("last_status_at"), str)
                else None,
                detail="Matching Mastodon instance account",
                evidence_url=url,
            )
        except (OSError, ValueError, TypeError) as exc:
            return _unknown(target, f"Cannot verify Mastodon account: {exc}", url)


def checker_for(platform: str, *, github_token: str | None = None) -> Checker:
    normalized = platform.lower()
    if normalized in {"bluesky", "dev.to", "devto"}:
        return PublicIdentityChecker()
    if normalized == "domain":
        return DomainChecker()
    if normalized in JsonProfileChecker.ENDPOINTS:
        return JsonProfileChecker(github_token)
    if normalized == "mastodon":
        return FederatedChecker()
    if normalized == "instagram":
        return InstagramChecker()
    if normalized in BestEffortProfileChecker.URLS:
        return BestEffortProfileChecker()
    raise ValueError(f"Unsupported platform: {platform}")
