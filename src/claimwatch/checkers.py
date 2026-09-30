from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from .models import Observation, Target

USER_AGENT = "claimwatch/0.2 (+https://github.com/DeepanshuPal/claimwatch)"


def _request(url: str, *, timeout: int = 12, headers: dict[str, str] | None = None) -> tuple[int, bytes, dict[str, str]]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


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
        handle = target.value.lstrip("@").strip()
        template, _link_key = self.ENDPOINTS[platform]
        url = template.format(handle=urllib.parse.quote(handle))
        headers: dict[str, str] = {}
        if platform == "github":
            headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
        try:
            status, body, response_headers = _request(url, headers=headers)
            if status == 404:
                return Observation(target, "available", detail=f"{platform} public API returned 404", evidence_url=url)
            if status == 200:
                data = json.loads(body)
                if platform == "github":
                    return Observation(target, "taken", owner=str(data.get("id")) if data.get("id") else handle.lower(), last_activity=data.get("updated_at"), detail=f"account login={data.get('login')}", evidence_url=data.get("html_url") or url)
                if platform == "pypi":
                    info = data.get("info", {})
                    return Observation(target, "taken", owner=info.get("author") or handle.lower(), last_activity=info.get("version"), detail=f"package exists; latest={info.get('version', 'unknown')}", evidence_url=info.get("package_url") or f"https://pypi.org/project/{urllib.parse.quote(handle)}/")
                if platform == "npm":
                    latest = data.get("dist-tags", {}).get("latest")
                    return Observation(target, "taken", owner=data.get("_id") or handle.lower(), last_activity=latest, detail=f"package exists; latest={latest or 'unknown'}", evidence_url=f"https://www.npmjs.com/package/{urllib.parse.quote(handle)}")
                return Observation(target, "taken", owner=str(data.get("id") or data.get("username") or handle.lower()), detail="Docker Hub user exists", evidence_url=f"https://hub.docker.com/u/{urllib.parse.quote(handle)}")
            remaining = response_headers.get("X-RateLimit-Remaining")
            suffix = f"; rate-limit remaining={remaining}" if remaining is not None else ""
            return Observation(target, "unknown", detail=f"{platform} public API HTTP {status}{suffix}", evidence_url=url)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return Observation(target, "error", detail=str(exc), evidence_url=url)


class DomainChecker(Checker):
    def check(self, target: Target) -> Observation:
        domain = target.value.strip().lower().rstrip(".")
        url = f"https://rdap.org/domain/{urllib.parse.quote(domain)}"
        try:
            status, body, _ = _request(url)
            if status == 200:
                data: dict[str, Any] = json.loads(body)
                events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events", [])}
                owner = data.get("handle") or data.get("ldhName")
                return Observation(target, "taken", owner=str(owner) if owner else domain, last_activity=events.get("last changed") or events.get("registration"), detail=f"RDAP registration found; expiration={events.get('expiration', 'unknown')}", evidence_url=url)
            if status == 404:
                try:
                    socket.getaddrinfo(domain, None)
                    return Observation(target, "taken", owner=domain, detail="No RDAP record; DNS resolves", evidence_url=url)
                except socket.gaierror as exc:
                    # A temporary resolver failure does not prove DNS absence.
                    # Treat only a definitive no-name response as negative evidence.
                    no_name_codes = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)}
                    if exc.errno in no_name_codes:
                        return Observation(target, "available", detail="No RDAP record and DNS does not resolve; confirm with registrar", evidence_url=url)
                    return Observation(target, "unknown", detail=f"No RDAP record; DNS lookup failed: {exc}", evidence_url=url)
            return Observation(target, "unknown", detail=f"RDAP HTTP {status}", evidence_url=url)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return Observation(target, "error", detail=str(exc), evidence_url=url)


class InstagramChecker(Checker):
    """Use Apify when configured; preserve raw probing as a zero-cost fallback."""

    ACTOR = "apify~instagram-profile-scraper"

    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.getenv("APIFY_TOKEN")

    def check(self, target: Target) -> Observation:
        handle = target.value.lstrip("@").strip()
        profile_url = f"https://www.instagram.com/{urllib.parse.quote(handle)}/"
        if not self.token:
            return BestEffortProfileChecker().check(target)
        url = f"https://api.apify.com/v2/acts/{self.ACTOR}/run-sync-get-dataset-items?token={urllib.parse.quote(self.token)}"
        payload = json.dumps({"usernames": [handle], "resultsLimit": 1}).encode()
        request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", "User-Agent": USER_AGENT}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                items = json.loads(response.read())
            if items and not items[0].get("error"):
                item = items[0]
                owner = str(item.get("id") or item.get("username") or handle.lower())
                activity = item.get("latestPostTimestamp") or item.get("latestIgtvVideoTimestamp")
                return Observation(target, "taken", owner=owner, last_activity=activity, detail="Profile found through configured Apify Instagram scraper", evidence_url=profile_url)
            return Observation(target, "unknown", detail="Apify returned no profile record; absence is not enough to claim availability", evidence_url=profile_url)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return Observation(target, "unknown", detail=f"Apify Instagram check failed: {exc}", evidence_url=profile_url)


class BestEffortProfileChecker(Checker):
    URLS: ClassVar[dict[str, str]] = {
        "x": "https://x.com/{handle}", "twitter": "https://x.com/{handle}",
        "instagram": "https://www.instagram.com/{handle}/", "tiktok": "https://www.tiktok.com/@{handle}",
        "youtube": "https://www.youtube.com/@{handle}", "linkedin": "https://www.linkedin.com/in/{handle}",
        "reddit": "https://www.reddit.com/user/{handle}/about.json", "threads": "https://www.threads.net/@{handle}",
        "twitch": "https://www.twitch.tv/{handle}", "pinterest": "https://www.pinterest.com/{handle}/",
        "snapchat": "https://www.snapchat.com/add/{handle}", "bluesky": "https://bsky.app/profile/{handle}",
        "telegram": "https://t.me/{handle}", "producthunt": "https://www.producthunt.com/@{handle}",
        "substack": "https://{handle}.substack.com/", "medium": "https://medium.com/@{handle}",
        "devto": "https://dev.to/{handle}", "dev.to": "https://dev.to/{handle}",
    }
    # These sites have meaningful 404s for public profile URLs. Other adapters treat 404 as unknown.
    TRUST_404: ClassVar[set[str]] = {"youtube", "reddit", "twitch", "pinterest", "bluesky", "producthunt", "substack", "medium", "devto", "dev.to"}

    def check(self, target: Target) -> Observation:
        platform = target.platform.lower()
        handle = target.value.lstrip("@").strip()
        url = self.URLS[platform].format(handle=urllib.parse.quote(handle))
        try:
            status, _, _ = _request(url, headers={"Accept": "text/html,application/json"})
            if status == 404 and platform in self.TRUST_404:
                return Observation(target, "available", detail="Public profile URL returned 404; confirm in-platform before claiming", evidence_url=url)
            if status == 404:
                return Observation(target, "unknown", detail="Public profile returned 404, but this platform does not expose a dependable availability signal", evidence_url=url)
            if status == 200:
                return Observation(target, "taken", owner=handle.lower(), detail="Public profile URL returned 200; ownership and activity are not verified", evidence_url=url)
            return Observation(target, "unknown", detail=f"Public profile HTTP {status}; platform may be throttling, redirecting, or challenging requests", evidence_url=url)
        except OSError as exc:
            return Observation(target, "error", detail=str(exc), evidence_url=url)


class FederatedChecker(Checker):
    def check(self, target: Target) -> Observation:
        value = target.value.lstrip("@").strip()
        if "@" not in value:
            return Observation(target, "unknown", detail="Mastodon is federated; use handle@instance so Claimwatch can query the correct server")
        handle, instance = value.rsplit("@", 1)
        url = f"https://{instance}/api/v1/accounts/lookup?acct={urllib.parse.quote(handle)}"
        try:
            status, body, _ = _request(url)
            if status == 404:
                return Observation(target, "available", detail="Instance account lookup returned 404; confirm on that instance", evidence_url=url)
            if status == 200:
                data = json.loads(body)
                return Observation(target, "taken", owner=str(data.get("id") or value.lower()), last_activity=data.get("last_status_at"), detail="Mastodon instance account lookup succeeded", evidence_url=data.get("url") or url)
            return Observation(target, "unknown", detail=f"Mastodon instance HTTP {status}", evidence_url=url)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return Observation(target, "error", detail=str(exc), evidence_url=url)


def checker_for(platform: str, *, github_token: str | None = None) -> Checker:
    normalized = platform.lower()
    if normalized == "domain": return DomainChecker()
    if normalized in JsonProfileChecker.ENDPOINTS: return JsonProfileChecker(github_token)
    if normalized == "mastodon": return FederatedChecker()
    if normalized == "instagram": return InstagramChecker()
    if normalized in BestEffortProfileChecker.URLS: return BestEffortProfileChecker()
    raise ValueError(f"Unsupported platform: {platform}")
