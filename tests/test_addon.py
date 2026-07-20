"""Add-on options -> Config mapping tests."""

from __future__ import annotations

import pytest

from snmptrap2mqtt.addon import config_from_options, options_to_config_dict


def _options() -> dict:
    return {
        "mqtt_server": "mqtt://core-mosquitto:1883",
        "mqtt_username": "svc",
        "mqtt_password": "secret",
        "base_topic": "snmptrap2mqtt",
        "discovery": False,
        "listener_port": 1162,
        "communities": ["public", "jesselee"],
        "targets": [
            {"name": "boiler-switch", "host": "192.168.1.9", "model": "GS728TPv2"},
            {"name": "attic-switch", "host": "192.168.1.11"},
        ],
        "log_level": "info",
    }


def test_options_map_to_nested_config() -> None:
    data = options_to_config_dict(_options())
    assert data["mqtt"] == {
        "server": "mqtt://core-mosquitto:1883",
        "base_topic": "snmptrap2mqtt",
        "username": "svc",
        "password": "secret",
    }
    assert data["homeassistant"] == {"discovery": False}
    assert data["listener"] == {"port": 1162, "communities": ["public", "jesselee"]}
    assert data["targets"][0] == {
        "friendly_name": "boiler-switch",
        "host": "192.168.1.9",
        "model": "GS728TPv2",
    }
    # Optional fields omitted rather than sent as null.
    assert data["targets"][1] == {
        "friendly_name": "attic-switch",
        "host": "192.168.1.11",
    }


def test_config_from_options_validates() -> None:
    config = config_from_options(_options())
    assert config.mqtt.server == "mqtt://core-mosquitto:1883"
    assert config.homeassistant.discovery is False
    assert config.listener.port == 1162
    names = [t.friendly_name for t in config.targets]
    assert names == ["boiler-switch", "attic-switch"]


def test_minimal_options() -> None:
    """Only mqtt_server is required; everything else defaults."""
    config = config_from_options({"mqtt_server": "mqtt://localhost:1883"})
    assert config.mqtt.base_topic == "snmptrap2mqtt"  # model default
    assert config.targets == []
    assert config.listener.port == 162


def test_missing_server_is_an_error() -> None:
    with pytest.raises(KeyError):
        options_to_config_dict({"base_topic": "x"})
