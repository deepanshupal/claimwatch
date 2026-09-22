from pathlib import Path

from claimwatch.core import diff, load_state, save_state
from claimwatch.models import Observation, Target


def test_first_seen_event():
    current = Observation(Target("github", "octocat"), "taken", owner="583231")
    assert [event.kind for event in diff({}, current)] == ["first_seen"]


def test_changes_are_specific():
    target = Target("domain", "example.com")
    current = Observation(target, "available", owner=None, last_activity="2026-01-01")
    previous = {target.key: {"status": "taken", "owner": "EXAMPLE", "last_activity": "2025-01-01"}}
    assert [event.kind for event in diff(previous, current)] == [
        "availability_changed", "owner_changed", "last_activity_changed"
    ]


def test_state_round_trip(tmp_path: Path):
    path = tmp_path / "state.json"
    item = Observation(Target("github", "octocat"), "taken", owner="583231")
    save_state(path, [item])
    assert load_state(path)[item.target.key]["owner"] == "583231"


def test_inconclusive_probe_does_not_emit_changes():
    target = Target("github", "octocat")
    previous = {
        target.key: {
            "status": "taken",
            "owner": "583231",
            "last_activity": "2026-09-20T00:00:00Z",
        }
    }
    current = Observation(target, "unknown", detail="public API HTTP 429")

    assert diff(previous, current) == []


def test_inconclusive_probe_preserves_last_conclusive_state(tmp_path: Path):
    path = tmp_path / "state.json"
    target = Target("github", "octocat")
    known = Observation(
        target,
        "taken",
        owner="583231",
        last_activity="2026-09-20T00:00:00Z",
    )
    save_state(path, [known])
    previous = load_state(path)

    save_state(
        path,
        [Observation(target, "error", detail="temporary network failure")],
        previous,
    )

    assert load_state(path) == previous
