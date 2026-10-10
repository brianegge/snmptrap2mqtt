"""Home Assistant MQTT discovery payload builders (pure functions).

Device-based discovery: one retained document per target at
<prefix>/device/snmptrap2mqtt_<id>/config carrying an event entity and,
when liveness polling is configured, a connectivity binary_sensor. Device
triggers are published lazily per (target, event name) on first occurrence,
zigbee2mqtt-style.
"""

from __future__ import annotations

import re
from typing import Any

from . import __version__
from .config import Config, TargetConfig
from .const import UNKNOWN_EVENT

ORIGIN = {
    "name": "snmptrap2mqtt",
    "sw": __version__,
    "url": "https://github.com/brianegge/snmptrap2mqtt",
}

# Stable node id for the bridge daemon's own HA device.
BRIDGE_NODE = "snmptrap2mqtt_bridge"


def object_id(target: TargetConfig) -> str:
    """Stable discovery node id derived from the target host."""
    return "snmptrap2mqtt_" + re.sub(r"[^A-Za-z0-9]", "_", target.host)


def device_discovery_topic(config: Config, target: TargetConfig) -> str:
    return f"{config.homeassistant.discovery_prefix}/device/{object_id(target)}/config"


def trigger_discovery_topic(config: Config, target: TargetConfig, event: str) -> str:
    prefix = config.homeassistant.discovery_prefix
    return f"{prefix}/device_automation/{object_id(target)}/{event}/config"


def _availability(config: Config, target: TargetConfig) -> list[dict[str, Any]]:
    base = config.mqtt.base_topic
    topics = [f"{base}/bridge/state"]
    if target.liveness is not None:
        topics.append(f"{base}/{target.friendly_name}/availability")
    return [
        {"topic": topic, "value_template": "{{ value_json.state }}"}
        for topic in topics
    ]


def device_discovery_payload(config: Config, target: TargetConfig) -> dict[str, Any]:
    """Retained device-based discovery document for one target."""
    base = config.mqtt.base_topic
    node = object_id(target)
    trap_topic = f"{base}/{target.friendly_name}/trap"
    event_types = sorted(set(config.trap_names.values()) | {UNKNOWN_EVENT})

    components: dict[str, Any] = {
        "trap": {
            "p": "event",
            "unique_id": f"{node}_trap",
            "name": "Trap",
            "state_topic": trap_topic,
            "event_types": event_types,
            # No device_class: HA's event platform accepts only doorbell,
            # button or motion, and rejects an explicit null.
            "json_attributes_topic": trap_topic,
        }
    }
    if target.liveness is not None:
        components["connectivity"] = {
            "p": "binary_sensor",
            "unique_id": f"{node}_connectivity",
            "name": "Connectivity",
            "device_class": "connectivity",
            "entity_category": "diagnostic",
            "state_topic": f"{base}/{target.friendly_name}/availability",
            "value_template": "{{ value_json.state }}",
            "payload_on": "online",
            "payload_off": "offline",
            # The sensor mirrors the liveness poll, so only bridge liveness
            # gates it — not its own topic.
            "availability": [
                {
                    "topic": f"{base}/bridge/state",
                    "value_template": "{{ value_json.state }}",
                }
            ],
        }

    device: dict[str, Any] = {
        "ids": [node],
        "name": target.friendly_name,
    }
    if target.manufacturer:
        device["mf"] = target.manufacturer
    if target.model:
        device["mdl"] = target.model

    return {
        "dev": device,
        "o": ORIGIN,
        "availability": _availability(config, target),
        "availability_mode": "all",
        "cmps": components,
    }


def trigger_discovery_payload(
    config: Config, target: TargetConfig, event: str
) -> dict[str, Any]:
    """Retained device-trigger discovery document for one trap event type."""
    return {
        "automation_type": "trigger",
        "type": event,
        "subtype": "trap",
        "topic": f"{config.mqtt.base_topic}/{target.friendly_name}/trap",
        "payload": event,
        "value_template": "{{ value_json.event_type }}",
        "device": {"ids": [object_id(target)]},
        "o": ORIGIN,
    }


def bridge_device_topic(config: Config) -> str:
    return f"{config.homeassistant.discovery_prefix}/device/{BRIDGE_NODE}/config"


def bridge_device_payload(config: Config, address: str | None = None) -> dict[str, Any]:
    """Retained HA discovery for the bridge daemon itself.

    Surfaces the daemon as a device carrying its version, an up/down
    connectivity sensor, the configured-target count, and — so the netgear_poe
    config no longer has to be told by hand — the routable address switches
    should send traps to. Published unconditionally (independent of the
    ``homeassistant.discovery`` target-mirroring switch) because it never
    duplicates the consumer's port entities; it only reports the bridge's own
    health.
    """
    base = config.mqtt.base_topic
    state_topic = f"{base}/bridge/state"
    info_topic = f"{base}/bridge/info"

    components: dict[str, Any] = {
        "status": {
            "p": "binary_sensor",
            "unique_id": f"{BRIDGE_NODE}_status",
            "name": "Status",
            "device_class": "connectivity",
            "entity_category": "diagnostic",
            "state_topic": state_topic,
            "value_template": "{{ value_json.state }}",
            "payload_on": "online",
            "payload_off": "offline",
        },
        "version": {
            "p": "sensor",
            "unique_id": f"{BRIDGE_NODE}_version",
            "name": "Version",
            "entity_category": "diagnostic",
            "state_topic": info_topic,
            "value_template": "{{ value_json.version }}",
        },
        "targets": {
            "p": "sensor",
            "unique_id": f"{BRIDGE_NODE}_targets",
            "name": "Targets",
            "entity_category": "diagnostic",
            "state_class": "measurement",
            "state_topic": info_topic,
            "value_template": "{{ value_json.targets | length }}",
        },
    }
    if address:
        components["trap_destination"] = {
            "p": "sensor",
            "unique_id": f"{BRIDGE_NODE}_trap_destination",
            "name": "Trap destination",
            "entity_category": "diagnostic",
            "icon": "mdi:ip-network",
            "state_topic": info_topic,
            "value_template": "{{ value_json.listener.address }}",
        }

    return {
        "dev": {
            "ids": [BRIDGE_NODE],
            "name": "snmptrap2mqtt",
            "mf": "snmptrap2mqtt",
            "sw": __version__,
            "cu": ORIGIN["url"],
        },
        "o": ORIGIN,
        # Availability is carried by the `status` connectivity entity rather
        # than a device-level `availability` block: gating the device on the
        # LWT would make `status` go "unavailable" on death instead of "off",
        # hiding the very signal it exists to show.
        "cmps": components,
    }


def bridge_info_payload(config: Config, address: str | None = None) -> dict[str, Any]:
    return {
        "version": __version__,
        "mqtt": {"server": config.mqtt.server, "base_topic": config.mqtt.base_topic},
        "listener": {
            "bind": config.listener.bind,
            # The routable address switches should target, resolved past a
            # 0.0.0.0 bind-all; null if it could not be determined.
            "address": address,
            "port": config.listener.port,
            "communities": len(config.listener.communities),
        },
        "targets": [t.friendly_name for t in config.targets],
    }


def bridge_devices_payload(config: Config) -> list[dict[str, Any]]:
    return [
        {
            "friendly_name": t.friendly_name,
            "host": t.host,
            "manufacturer": t.manufacturer,
            "model": t.model,
        }
        for t in config.targets
    ]
