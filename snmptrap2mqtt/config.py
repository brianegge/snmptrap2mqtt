"""YAML configuration with zigbee2mqtt-style env-var overrides.

Any config key can be overridden with SNMPTRAP2MQTT_CONFIG_<PATH> where <PATH>
is the upper-cased key path joined by underscores, e.g.
SNMPTRAP2MQTT_CONFIG_MQTT_SERVER or SNMPTRAP2MQTT_CONFIG_MQTT_BASE_TOPIC.
Because key names themselves contain underscores, segments are matched
greedily against the known schema at each nesting level.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .const import BUILTIN_TRAPS

ENV_PREFIX = "SNMPTRAP2MQTT_CONFIG_"


class MqttConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: str = "mqtt://localhost:1883"
    base_topic: str = "snmptrap2mqtt"
    username: str | None = None
    password: str | None = None
    client_id: str = "snmptrap2mqtt"
    keepalive: int = 60

    @field_validator("server")
    @classmethod
    def _server_scheme(cls, value: str) -> str:
        scheme = urlparse(value).scheme
        if scheme not in ("mqtt", "mqtts"):
            raise ValueError(f"mqtt.server must be mqtt:// or mqtts://, got {value!r}")
        return value

    @field_validator("base_topic")
    @classmethod
    def _topic_safe(cls, value: str) -> str:
        if not value or re.search(r"[+#/\s]", value):
            raise ValueError("mqtt.base_topic must be a single non-empty topic level")
        return value

    @property
    def host(self) -> str:
        return urlparse(self.server).hostname or "localhost"

    @property
    def port(self) -> int:
        parsed = urlparse(self.server)
        return parsed.port or (8883 if parsed.scheme == "mqtts" else 1883)

    @property
    def tls(self) -> bool:
        return urlparse(self.server).scheme == "mqtts"


class HomeAssistantConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discovery: bool = True
    discovery_prefix: str = "homeassistant"
    status_topic: str = "homeassistant/status"


class ListenerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bind: str = "0.0.0.0"
    port: int = Field(default=162, ge=1, le=65535)
    # Accepted v1/v2c community strings; an empty list accepts any community.
    communities: list[str] = ["public"]


class LivenessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oid: str = "1.3.6.1.2.1.1.3.0"  # sysUpTime
    interval: int = Field(default=60, ge=5)
    community: str | None = None  # falls back to first listener community
    port: int = Field(default=161, ge=1, le=65535)
    # Consecutive failed polls before the target is marked offline.
    retries: int = Field(default=2, ge=1)


class TargetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    friendly_name: str
    host: str
    manufacturer: str | None = None
    model: str | None = None
    liveness: LivenessConfig | None = None

    @field_validator("friendly_name")
    @classmethod
    def _name_topic_safe(cls, value: str) -> str:
        if not value or re.search(r"[+#/\s]", value):
            raise ValueError(
                "friendly_name must be non-empty and contain no '/', '+', '#' or"
                " whitespace (it becomes an MQTT topic level)"
            )
        return value


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mqtt: MqttConfig = MqttConfig()
    homeassistant: HomeAssistantConfig = HomeAssistantConfig()
    listener: ListenerConfig = ListenerConfig()
    targets: list[TargetConfig] = []
    traps: dict[str, str] = {}

    @field_validator("targets")
    @classmethod
    def _unique_targets(cls, value: list[TargetConfig]) -> list[TargetConfig]:
        for key in ("friendly_name", "host"):
            seen: set[str] = set()
            for target in value:
                item = getattr(target, key)
                if item in seen:
                    raise ValueError(f"duplicate target {key}: {item}")
                seen.add(item)
        return value

    @property
    def trap_names(self) -> dict[str, str]:
        """Effective OID -> event name map (built-ins + config overrides)."""
        return {**BUILTIN_TRAPS, **self.traps}

    def target_for_ip(self, ip: str) -> TargetConfig | None:
        for target in self.targets:
            if target.host == ip:
                return target
        return None


def _apply_env_overrides(data: dict, environ: dict[str, str]) -> dict:
    """Merge SNMPTRAP2MQTT_CONFIG_* environment variables into raw config."""
    for name, raw in sorted(environ.items()):
        if not name.startswith(ENV_PREFIX):
            continue
        segments = name[len(ENV_PREFIX) :].lower().split("_")
        _set_path(data, Config, segments, raw, name)
    return data


def _set_path(
    node: dict, model: type[BaseModel] | None, segments: list[str], raw: str, name: str
) -> None:
    fields = set(model.model_fields) if model else set()
    # Greedy: prefer the longest field name assembled from leading segments so
    # MQTT_BASE_TOPIC resolves to mqtt -> base_topic, not mqtt -> base -> topic.
    for split in range(len(segments), 0, -1):
        key = "_".join(segments[:split])
        rest = segments[split:]
        known = key in fields
        if not known and model is not None:
            continue
        if not rest:
            node[key] = yaml.safe_load(raw)
            return
        sub_model = None
        if known:
            annotation = model.model_fields[key].annotation
            # Unwrap Optional[Model]
            for candidate in getattr(annotation, "__args__", (annotation,)):
                if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                    sub_model = candidate
        child = node.setdefault(key, {})
        if isinstance(child, dict):
            _set_path(child, sub_model, rest, raw, name)
            return
    raise ValueError(f"cannot map environment override {name} onto the config schema")


def load_config(
    path: str | Path | None, environ: dict[str, str] | None = None
) -> Config:
    """Load YAML config from path (optional) and apply env-var overrides."""
    data: dict = {}
    if path is not None:
        text = Path(path).read_text()
        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"config file {path} must contain a YAML mapping")
        data = loaded
    _apply_env_overrides(data, environ if environ is not None else dict(os.environ))
    return Config.model_validate(data)
