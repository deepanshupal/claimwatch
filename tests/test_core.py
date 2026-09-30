from pathlib import Path

from claimwatch.core import diff, load_state, save_state
from claimwatch.models import Observation, Target


def test_first_seen_event():
    current = Observation(Target("github", "octocat"), "taken", owner="583231")
    assert [event.kind for event in diff({}, current)] == ["first_seen"]


def test_changes_are_specific():
    target = Target("github", "octocat")
    current = Observation(target, "taken", owner="NEW-ID", last_activity="2026-01-01")
    previous = {
        target.key: {"status": "unknown", "owner": "EXAMPLE", "last_activity": "2025-01-01"}
    }
    assert [event.kind for event in diff(previous, current)] == [
        "availability_changed",
        "owner_changed",
        "last_activity_changed",
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


def test_conclusive_account_with_missing_activity_preserves_known_activity(tmp_path):
    target = Target("github", "octocat")
    prior = Observation(target, "taken", owner="583231", last_activity="2026-09-01")
    previous = {target.key: prior.to_dict()}
    current = Observation(target, "taken", owner="583231")
    assert diff(previous, current) == []
    path = tmp_path / "state.json"
    save_state(path, [current], previous)
    assert load_state(path)[target.key]["last_activity"] == "2026-09-01"


def test_first_inconclusive_probe_does_not_send_first_seen():
    assert diff({}, Observation(Target("x", "agentcommerce"), "unknown")) == []


def test_state_rejects_invalid_schema(tmp_path):
    import pytest

    path = tmp_path / "state.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="state"):
        load_state(path)


def test_legacy_available_state_does_not_keep_false_claim(tmp_path):
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps({"x:agentcommerce": {"status": "available", "owner": None}}))
    assert load_state(path)["x:agentcommerce"]["status"] == "unknown"


def test_registry_record_id_is_not_registrant_identity():
    target = Target("domain", "example.com")
    previous = {target.key: {"status": "taken", "owner": "OLD-RECORD"}}
    assert diff(previous, Observation(target, "taken", owner="NEW-RECORD")) == []


def test_legacy_html_taken_is_not_preserved_as_proof(tmp_path):
    import json

    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "instagram:analoghouse": {
                    "status": "taken",
                    "detail": "Public profile URL returned 200",
                }
            }
        )
    )
    assert load_state(path)["instagram:analoghouse"]["status"] == "unknown"
