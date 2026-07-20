"""Home Assistant add-on bootstrap.

When the bridge runs as a Supervisor add-on, Home Assistant writes the user's
UI options to ``/data/options.json`` (a flat set of keys). This module maps
those onto the bridge's native, nested :class:`~snmptrap2mqtt.config.Config`
so the *same* published image serves both standalone use (``-c config.yaml``)
and add-on use with no rebuild.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Config

# HA mounts the add-on's persistent volume at /data and writes options here.
OPTIONS_PATH = Path("/data/options.json")


def options_to_config_dict(options: dict[str, Any]) -> dict[str, Any]:
    """Translate flat add-on options into the bridge's nested config mapping."""
    mqtt: dict[str, Any] = {"server": options["mqtt_server"]}
    if options.get("base_topic"):
        mqtt["base_topic"] = options["base_topic"]
    if options.get("mqtt_username"):
        mqtt["username"] = options["mqtt_username"]
    if options.get("mqtt_password"):
        mqtt["password"] = options["mqtt_password"]

    listener: dict[str, Any] = {}
    if options.get("listener_port"):
        listener["port"] = options["listener_port"]
    if options.get("communities"):
        listener["communities"] = list(options["communities"])

    targets: list[dict[str, Any]] = []
    for entry in options.get("targets", []):
        target: dict[str, Any] = {
            "friendly_name": entry["name"],
            "host": entry["host"],
        }
        if entry.get("manufacturer"):
            target["manufacturer"] = entry["manufacturer"]
        if entry.get("model"):
            target["model"] = entry["model"]
        targets.append(target)

    data: dict[str, Any] = {"mqtt": mqtt, "targets": targets}
    if "discovery" in options:
        data["homeassistant"] = {"discovery": bool(options["discovery"])}
    if listener:
        data["listener"] = listener
    return data


def config_from_options(options: dict[str, Any]) -> Config:
    """Build a validated Config from parsed add-on options."""
    return Config.model_validate(options_to_config_dict(options))


def load_options(path: Path = OPTIONS_PATH) -> dict[str, Any]:
    """Read and parse the add-on options file."""
    return json.loads(path.read_text())
