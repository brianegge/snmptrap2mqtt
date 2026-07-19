"""Discovery payload shape tests."""

from __future__ import annotations

from snmptrap2mqtt.config import Config
from snmptrap2mqtt.discovery import (
    bridge_devices_payload,
    bridge_info_payload,
    device_discovery_payload,
    device_discovery_topic,
    trigger_discovery_payload,
    trigger_discovery_topic,
)


def test_device_discovery_with_liveness(config: Config) -> None:
    target = config.targets[0]  # boiler-switch, has liveness
    topic = device_discovery_topic(config, target)
    assert topic == "homeassistant/device/snmptrap2mqtt_192_168_254_250/config"

    payload = device_discovery_payload(config, target)
    assert payload["dev"]["ids"] == ["snmptrap2mqtt_192_168_254_250"]
    assert payload["dev"]["name"] == "boiler-switch"
    assert payload["dev"]["mf"] == "Netgear"
    assert payload["dev"]["mdl"] == "GS728TPv2"
    assert payload["o"]["name"] == "snmptrap2mqtt"

    trap = payload["cmps"]["trap"]
    assert trap["p"] == "event"
    assert trap["state_topic"] == "snmptrap2mqtt/boiler-switch/trap"
    assert "linkDown" in trap["event_types"]
    assert "poePortChange" in trap["event_types"]
    assert "unknown" in trap["event_types"]

    connectivity = payload["cmps"]["connectivity"]
    assert connectivity["p"] == "binary_sensor"
    assert connectivity["state_topic"] == "snmptrap2mqtt/boiler-switch/availability"

    # Both the bridge LWT and the target availability topic gate the entity.
    topics = [a["topic"] for a in payload["availability"]]
    assert topics == [
        "snmptrap2mqtt/bridge/state",
        "snmptrap2mqtt/boiler-switch/availability",
    ]


def test_device_discovery_without_liveness(config: Config) -> None:
    target = config.targets[1]  # attic-switch, no liveness
    payload = device_discovery_payload(config, target)
    assert "connectivity" not in payload["cmps"]
    topics = [a["topic"] for a in payload["availability"]]
    assert topics == ["snmptrap2mqtt/bridge/state"]


def test_trigger_discovery(config: Config) -> None:
    target = config.targets[0]
    topic = trigger_discovery_topic(config, target, "linkDown")
    assert topic == (
        "homeassistant/device_automation/snmptrap2mqtt_192_168_254_250/"
        "linkDown/config"
    )
    payload = trigger_discovery_payload(config, target, "linkDown")
    assert payload["automation_type"] == "trigger"
    assert payload["type"] == "linkDown"
    assert payload["topic"] == "snmptrap2mqtt/boiler-switch/trap"
    assert payload["payload"] == "linkDown"
    assert payload["value_template"] == "{{ value_json.event_type }}"
    assert payload["device"]["ids"] == ["snmptrap2mqtt_192_168_254_250"]


def test_bridge_payloads(config: Config) -> None:
    info = bridge_info_payload(config)
    assert info["targets"] == ["boiler-switch", "attic-switch"]
    devices = bridge_devices_payload(config)
    assert devices[0]["host"] == "192.168.254.250"
    assert devices[0]["model"] == "GS728TPv2"
