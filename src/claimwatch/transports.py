from __future__ import annotations

import json
import smtplib
import ssl
import urllib.request
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Any

from .checkers import _NoRedirect
from .models import Event


class Transport(ABC):
    @abstractmethod
    def send(self, events: list[Event]) -> None: ...


class WebhookTransport(Transport):
    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self.url, self.headers = url, headers or {}

    def send(self, events: list[Event]) -> None:
        payload = json.dumps(
            {"source": "claimwatch", "events": [event.to_dict() for event in events]}
        ).encode()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "claimwatch/0.1",
            **self.headers,
        }
        with urllib.request.build_opener(_NoRedirect()).open(
            urllib.request.Request(self.url, data=payload, headers=headers, method="POST"),
            timeout=15,
        ):
            pass


class SMTPTransport(Transport):
    def __init__(self, config: dict[str, Any]) -> None:
        for flag in ("ssl", "starttls"):
            if flag in config and not isinstance(config[flag], bool):
                raise ValueError(f"{flag} must be a boolean")
        self.config = config

    def send(self, events: list[Event]) -> None:
        message = EmailMessage()
        message["Subject"] = self.config.get("subject", f"Claimwatch: {len(events)} change(s)")
        message["From"] = self.config["from"]
        message["To"] = self.config["to"]
        message.set_content(json.dumps([event.to_dict() for event in events], indent=2))
        host, port = self.config["host"], int(self.config.get("port", 587))
        if self.config.get("ssl", False):
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, context=ssl.create_default_context(), timeout=15
            )
        else:
            smtp = smtplib.SMTP(host, port, timeout=15)
        with smtp:
            if self.config.get("starttls", not self.config.get("ssl", False)):
                smtp.starttls(context=ssl.create_default_context())
            if self.config.get("username"):
                smtp.login(self.config["username"], self.config.get("password", ""))
            smtp.send_message(message)
