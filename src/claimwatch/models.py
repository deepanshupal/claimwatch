from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Status = Literal["available", "not_registered", "taken", "unknown", "error"]


@dataclass(slots=True)
class Target:
    platform: str
    value: str
    label: str | None = None

    @property
    def key(self) -> str:
        return f"{self.platform.lower()}:{self.value.lower()}"


@dataclass(slots=True)
class Observation:
    target: Target
    status: Status
    owner: str | None = None
    last_activity: str | None = None
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    detail: str | None = None
    evidence_url: str | None = None
    evidence_version: int = 2

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["target"] = asdict(self.target)
        return result


@dataclass(slots=True)
class Event:
    kind: str
    target: Target
    before: Any
    after: Any
    observed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": asdict(self.target),
            "before": self.before,
            "after": self.after,
            "observed_at": self.observed_at,
        }
