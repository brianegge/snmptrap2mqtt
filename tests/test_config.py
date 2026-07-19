"""Config loading, validation, and env-var overrides."""

from __future__ import annotations

import pytest

from snmptrap2mqtt.config import Config, load_config


def test_defaults() -> None:
    config = load_config(None, environ={})
    assert config.mqtt.host == "localhost"
    assert config.mqtt.port == 1883
    assert config.listener.port == 162
    assert config.listener.communities == ["public"]
    assert config.trap_names["1.3.6.1.6.3.1.1.5.3"] == "linkDown"


def test_load_yaml(config: Config) -> None:
    assert config.mqtt.host == "192.168.254.30"
    assert [t.friendly_name for t in config.targets] == [
        "boiler-switch",
        "attic-switch",
    ]
    assert config.targets[0].liveness is not None
    assert config.targets[1].liveness is None
    assert config.target_for_ip("192.168.254.250").friendly_name == "boiler-switch"
    assert config.target_for_ip("10.0.0.1") is None


def test_env_overrides(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("mqtt:\n  server: mqtt://old:1883\n")
    config = load_config(
        path,
        environ={
            "SNMPTRAP2MQTT_CONFIG_MQTT_SERVER": "mqtt://192.168.254.30:1883",
            "SNMPTRAP2MQTT_CONFIG_MQTT_BASE_TOPIC": "traps",
            "SNMPTRAP2MQTT_CONFIG_LISTENER_PORT": "1162",
            "SNMPTRAP2MQTT_CONFIG_HOMEASSISTANT_DISCOVERY": "false",
            "UNRELATED": "ignored",
        },
    )
    assert config.mqtt.host == "192.168.254.30"
    assert config.mqtt.base_topic == "traps"
    assert config.listener.port == 1162
    assert config.homeassistant.discovery is False


def test_env_override_unknown_key_rejected() -> None:
    with pytest.raises(ValueError, match="cannot map"):
        load_config(None, environ={"SNMPTRAP2MQTT_CONFIG_BOGUS_KEY": "1"})


def test_traps_merge_overrides_builtin(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("traps:\n  1.3.6.1.6.3.1.1.5.3: portDown\n  1.2.3.4: custom\n")
    config = load_config(path, environ={})
    assert config.trap_names["1.3.6.1.6.3.1.1.5.3"] == "portDown"
    assert config.trap_names["1.2.3.4"] == "custom"
    assert config.trap_names["1.3.6.1.6.3.1.1.5.4"] == "linkUp"


def test_bad_server_scheme_rejected(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("mqtt:\n  server: http://broker\n")
    with pytest.raises(ValueError, match=r"mqtt\.server"):
        load_config(path, environ={})


def test_friendly_name_topic_safety(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "targets:\n  - friendly_name: 'bad/name'\n    host: 10.0.0.1\n"
    )
    with pytest.raises(ValueError, match="friendly_name"):
        load_config(path, environ={})


def test_duplicate_target_host_rejected(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "targets:\n"
        "  - friendly_name: a\n    host: 10.0.0.1\n"
        "  - friendly_name: b\n    host: 10.0.0.1\n"
    )
    with pytest.raises(ValueError, match="duplicate target"):
        load_config(path, environ={})
