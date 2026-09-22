from pathlib import Path

from claimwatch.cli import load_config


def test_scheduled_config_tracks_deepanshu_across_supported_shapes():
    config = load_config(Path("claimwatch.yml"))
    targets = config["targets"]

    assert len(targets) == 20
    assert {target["platform"] for target in targets} == {
        "domain", "github", "instagram", "youtube", "linkedin", "reddit",
        "threads", "twitch", "pinterest", "snapchat", "bluesky", "mastodon",
        "telegram", "producthunt", "substack", "medium", "dev.to", "npm",
        "pypi", "dockerhub",
    }
    assert {target.get("handle") or target.get("domain") for target in targets} == {
        "deepanshu", "deepanshu.com", "deepanshu.bsky.social",
        "deepanshu@mastodon.social",
    }
