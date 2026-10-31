from pathlib import Path

from homelab_status.config import load_settings


def test_loads_expected_peers(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[server]
database_path = "status.sqlite3"
stale_after_seconds = 1800
missing_after_seconds = 7200

[[peers]]
name = "u59"
wireguard_ip = "10.0.1.2"
display_order = 20

[[peers]]
name = "awesom"
wireguard_ip = "10.0.1.1"
display_order = 10
""",
        encoding="utf-8",
    )

    settings = load_settings(config)

    assert [peer.name for peer in settings.peers] == ["awesom", "u59"]
    assert settings.peers_by_ip["10.0.1.2"].name == "u59"

