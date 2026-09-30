from pathlib import Path

from claimwatch.cli import load_config


def test_scheduled_config_tracks_deepanshu_across_supported_shapes():
    config = load_config(Path("claimwatch.yml"))
    targets = config["targets"]

    assert len(targets) == 20
    assert {target["platform"] for target in targets} == {
        "domain",
        "github",
        "instagram",
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
    }
    assert {target.get("handle") or target.get("domain") for target in targets} == {
        "deepanshu",
        "deepanshu.com",
        "deepanshu.bsky.social",
        "deepanshu@mastodon.social",
    }


def test_smtp_string_false_is_not_enabled(monkeypatch):
    import pytest

    from claimwatch.transports import SMTPTransport

    with pytest.raises(ValueError, match="boolean"):
        SMTPTransport({"ssl": "False", "host": "example.com", "from": "a", "to": "b"})


def test_empty_config_has_clear_error(tmp_path):
    import pytest

    path = tmp_path / "empty.yml"
    path.write_text("")
    with pytest.raises(ValueError, match="config"):
        load_config(path)


def test_alert_failure_keeps_state_retryable(tmp_path, monkeypatch):
    import json
    import sys

    import pytest

    from claimwatch import cli
    from claimwatch.models import Observation

    target = {"platform": "github", "handle": "octocat"}
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"targets": [target], "alerts": {"webhook": {"url": "https://example.com"}}})
    )
    state = tmp_path / "state.json"
    monkeypatch.setattr(sys, "argv", ["claimwatch", "-c", str(config), "--state", str(state)])

    class Checker:
        def check(self, target):
            return Observation(target, "taken", owner="583231")

    monkeypatch.setattr("claimwatch.core.checker_for", lambda *a, **k: Checker())

    def fail_send(self, events):
        raise OSError("delivery failed")

    monkeypatch.setattr("claimwatch.cli.WebhookTransport.send", fail_send)
    with pytest.raises(OSError, match="delivery failed"):
        cli.main()
    assert not state.exists()


def test_smtp_config_preserves_yaml_booleans(tmp_path, monkeypatch):
    import sys

    from claimwatch import cli
    from claimwatch.models import Observation

    config = tmp_path / "config.yml"
    config.write_text(
        "targets:\n  - {platform: github, handle: octocat}\nalerts:\n  smtp: {host: example.com, from: a, to: b, ssl: false, starttls: true}\n"
    )
    monkeypatch.setattr(
        sys, "argv", ["claimwatch", "-c", str(config), "--state", str(tmp_path / "state.json")]
    )

    class Checker:
        def check(self, target):
            return Observation(target, "taken", owner="583231")

    monkeypatch.setattr("claimwatch.core.checker_for", lambda *a, **k: Checker())

    def send(self, events):
        assert self.config["ssl"] is False
        assert self.config["starttls"] is True

    monkeypatch.setattr("claimwatch.cli.SMTPTransport.send", send)
    cli.main()


def test_bad_alert_config_rejected_before_probes(tmp_path):
    import json

    import pytest

    for alerts in [
        {"smtp": False},
        {"webhook": "https://example.com"},
        {"webhook": {"url": "$UNSET_CLAIMWATCH_TEST_URL"}},
        {"smtp": {"host": "example.com", "from": "a", "to": "b", "ssl": "false"}},
    ]:
        path = tmp_path / "bad.json"
        path.write_text(
            json.dumps({"targets": [{"platform": "github", "handle": "octocat"}], "alerts": alerts})
        )
        with pytest.raises((ValueError, TypeError)):
            load_config(path)
