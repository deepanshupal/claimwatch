from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .checkers import checker_for
from .models import Event, Observation, Target

TRACKED_FIELDS = {
    "status": "availability_changed",
    "owner": "owner_changed",
    "last_activity": "last_activity_changed",
}


def load_state(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or any(
        not isinstance(v, dict)
        or v.get("status") not in {"available", "not_registered", "taken", "unknown", "error"}
        for v in data.values()
    ):
        raise ValueError("Invalid state file schema; state was not overwritten")
    for record in data.values():
        if record.get("status") == "available" or (
            record.get("status") == "taken" and record.get("evidence_version") != 2
        ):
            record["status"] = "unknown"
            record["detail"] = (
                "Legacy evidence was not verified under the current checks; recheck with a registrar or platform"
            )
    return data


def save_state(
    path: Path,
    observations: list[Observation],
    previous: dict[str, dict[str, Any]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, dict[str, Any]] = {}
    for item in observations:
        old = (previous or {}).get(item.target.key)
        # Keep the last conclusive signal through transient blocks and errors.
        # The current observation is still returned to the caller for diagnostics.
        if old is not None and item.status in {"unknown", "error"}:
            state[item.target.key] = old
        else:
            record = item.to_dict()
            if old and old.get("status") == item.status and item.status == "taken":
                for field in ("owner", "last_activity"):
                    if record.get(field) is None:
                        record[field] = old.get(field)
            state[item.target.key] = record
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def diff(previous: dict[str, dict[str, Any]], current: Observation) -> list[Event]:
    old = previous.get(current.target.key)
    if current.status in {"unknown", "error"}:
        return []
    if old is None:
        return [Event("first_seen", current.target, None, current.status, current.checked_at)]
    events: list[Event] = []
    now = current.to_dict()
    for field, kind in TRACKED_FIELDS.items():
        if field == "owner" and current.target.platform.lower() == "domain":
            continue
        before, after = old.get(field), now.get(field)
        if (
            field != "status"
            and current.status == "taken"
            and old.get("status") == "taken"
            and after is None
        ):
            continue
        if before != after and (before is not None or after is not None):
            events.append(Event(kind, current.target, before, after, current.checked_at))
    return events


def run(
    targets: list[Target],
    state_path: Path,
    *,
    github_token: str | None = None,
    persist: bool = True,
) -> tuple[list[Observation], list[Event]]:
    previous = load_state(state_path)
    observations: list[Observation] = []
    events: list[Event] = []
    for target in targets:
        observation = checker_for(target.platform, github_token=github_token).check(target)
        observations.append(observation)
        events.extend(diff(previous, observation))
    if persist:
        save_state(state_path, observations, previous)
    return observations, events
