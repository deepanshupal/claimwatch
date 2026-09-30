from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import yaml

from .core import load_state, run, save_state
from .models import Target
from .transports import SMTPTransport, WebhookTransport


def load_config(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        if path.suffix.lower() == ".json":
            data = json.load(handle)
        else:
            data = yaml.safe_load(handle)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("targets"), list)
        or not data["targets"]
    ):
        raise ValueError("config must contain a nonempty targets list")
    for item in data["targets"]:
        if not isinstance(item, dict) or not isinstance(item.get("platform"), str):
            raise TypeError("config target must have a platform")
        value = item.get("handle") or item.get("domain") or item.get("value")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("config target must have a nonempty handle, domain or value")
        from .checkers import checker_for

        checker_for(item["platform"])
    if not isinstance(data.get("alerts", {}), dict):
        raise TypeError("config alerts must be a mapping")
    alerts = data.get("alerts", {})
    for kind, alert in alerts.items():
        if kind not in {"smtp", "webhook"} or not isinstance(alert, dict):
            raise TypeError("alerts entries must be smtp or webhook mappings")
        for key, value in list(alert.items()):
            if isinstance(value, str):
                value = os.path.expandvars(value)
                if re.search(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[^}]+\})", value):
                    raise ValueError("An alert environment variable is unset")
                alert[key] = value
        if kind == "webhook":
            url = alert.get("url")
            if (
                not isinstance(url, str)
                or urllib.parse.urlsplit(url).scheme != "https"
                or not urllib.parse.urlsplit(url).hostname
            ):
                raise ValueError("Webhook URL must be HTTPS")
            headers = alert.get("headers", {})
            if not isinstance(headers, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()
            ):
                raise TypeError("Webhook headers must map strings to strings")
        else:
            if any(
                not isinstance(alert.get(key), str) or not alert[key]
                for key in ("host", "from", "to")
            ):
                raise ValueError("SMTP requires host, from and to")
            port = alert.get("port", 587)
            if isinstance(port, bool) or not str(port).isdigit() or not 1 <= int(port) <= 65535:
                raise ValueError("SMTP port must be between 1 and 65535")
            SMTPTransport(alert)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="claimwatch", description="Watch handles and domains for identity changes."
    )
    parser.add_argument("--config", "-c", type=Path, default=Path("claimwatch.yml"))
    parser.add_argument("--state", type=Path, default=Path(".claimwatch/state.json"))
    parser.add_argument(
        "--no-alerts", action="store_true", help="Check and persist state without sending alerts"
    )
    args = parser.parse_args()
    config = load_config(args.config)
    targets = [
        Target(
            item["platform"],
            item.get("handle") or item.get("domain") or item["value"],
            item.get("label"),
        )
        for item in config.get("targets", [])
    ]
    if not targets:
        parser.error("config must contain at least one target")
    observations, events = run(
        targets, args.state, github_token=os.getenv("GITHUB_TOKEN"), persist=False
    )
    print(
        json.dumps(
            {
                "observations": [item.to_dict() for item in observations],
                "events": [item.to_dict() for item in events],
            },
            indent=2,
        )
    )
    if events and not args.no_alerts:
        alert_config = config.get("alerts", {})
        if webhook := alert_config.get("webhook"):
            WebhookTransport(webhook["url"], webhook.get("headers")).send(events)
        if smtp := alert_config.get("smtp"):
            SMTPTransport(smtp).send(events)
    save_state(args.state, observations, load_state(args.state))
    if any(item.status == "error" for item in observations):
        sys.exit(2)


if __name__ == "__main__":
    main()
