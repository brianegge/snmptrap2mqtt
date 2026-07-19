"""Bridge orchestration: listener + MQTT session + discovery + availability."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import aiomqtt

from .config import Config, TargetConfig
from .const import UNKNOWN_EVENT
from .discovery import (
    bridge_devices_payload,
    bridge_info_payload,
    device_discovery_payload,
    device_discovery_topic,
    trigger_discovery_payload,
    trigger_discovery_topic,
)
from .listener import TrapEvent, TrapListener
from .liveness import LivenessPoller

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 5


def normalize_trap(config: Config, event: TrapEvent) -> tuple[str, dict[str, Any]]:
    """Return (target id, payload) — the correlation contract with netgear_poe.

    The bridge stays policy-free: ifIndex is surfaced but never filtered
    (netgear_poe applies its MAX_PHYSICAL_PORT cut on its own side).
    """
    target = config.target_for_ip(event.source_ip)
    target_id = (
        target.friendly_name
        if target is not None
        else re.sub(r"[^A-Za-z0-9]", "_", event.source_ip)
    )
    payload = {
        "event_type": config.trap_names.get(event.trap_oid, UNKNOWN_EVENT),
        "trap_oid": event.trap_oid,
        "source_ip": event.source_ip,
        "target": target_id,
        "if_index": event.if_index,
        "uptime": event.uptime,
        "varbinds": event.varbinds,
    }
    return target_id, payload


class Bridge:
    """Owns the MQTT session and fans everything through it."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client: aiomqtt.Client | None = None
        self._listener = TrapListener(self._on_trap, config.listener.communities)
        self._pollers: list[LivenessPoller] = []
        self._availability: dict[str, bool] = {}
        self._published_triggers: set[tuple[str, str]] = set()
        self._stopping = asyncio.Event()

    # -- topics ------------------------------------------------------------

    @property
    def _base(self) -> str:
        return self._config.mqtt.base_topic

    def _state_topic(self) -> str:
        return f"{self._base}/bridge/state"

    # -- lifecycle ---------------------------------------------------------

    async def run(self) -> None:
        """Run until stop(); reconnects to the broker with backoff."""
        await self._listener.start(
            self._config.listener.bind, self._config.listener.port
        )
        default_community = next(iter(self._config.listener.communities), "public")
        for target in self._config.targets:
            if target.liveness is not None:
                poller = LivenessPoller(
                    target, default_community, self._publish_availability
                )
                poller.start()
                self._pollers.append(poller)

        try:
            while not self._stopping.is_set():
                try:
                    await self._session()
                except aiomqtt.MqttError as err:
                    if self._stopping.is_set():
                        break
                    _LOGGER.warning(
                        "MQTT connection lost (%s); retrying in %ds",
                        err,
                        RECONNECT_DELAY,
                    )
                    await asyncio.sleep(RECONNECT_DELAY)
        finally:
            self._shutdown_tasks()

    def stop(self) -> None:
        self._stopping.set()

    def _shutdown_tasks(self) -> None:
        self._listener.stop()
        for poller in self._pollers:
            poller.stop()
        self._pollers.clear()

    async def _session(self) -> None:
        """One broker connection: birth publishes, then serve messages."""
        cfg = self._config.mqtt
        will = aiomqtt.Will(
            topic=self._state_topic(),
            payload=json.dumps({"state": "offline"}),
            qos=1,
            retain=True,
        )
        async with aiomqtt.Client(
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.username,
            password=cfg.password,
            identifier=cfg.client_id,
            keepalive=cfg.keepalive,
            will=will,
            tls_params=aiomqtt.TLSParameters() if cfg.tls else None,
        ) as client:
            self._client = client
            _LOGGER.info("Connected to MQTT broker %s:%d", cfg.host, cfg.port)
            try:
                await self._publish_birth()
                await client.subscribe(self._config.homeassistant.status_topic)
                stop_wait = asyncio.ensure_future(self._stopping.wait())
                try:
                    await self._serve(client, stop_wait)
                finally:
                    stop_wait.cancel()
                if self._stopping.is_set():
                    # Graceful shutdown: leave a retained offline state so the
                    # LWT (only sent on ungraceful drops) isn't relied upon.
                    await self._publish(
                        self._state_topic(), {"state": "offline"}, retain=True
                    )
            finally:
                self._client = None

    async def _serve(self, client: aiomqtt.Client, stop_wait: asyncio.Future) -> None:
        messages = client.messages
        while not self._stopping.is_set():
            get_message = asyncio.ensure_future(anext(messages))
            done, _ = await asyncio.wait(
                (get_message, stop_wait), return_when=asyncio.FIRST_COMPLETED
            )
            if get_message not in done:
                get_message.cancel()
                return
            message = get_message.result()
            if message.topic.matches(self._config.homeassistant.status_topic):
                payload = (
                    message.payload.decode()
                    if isinstance(message.payload, bytes | bytearray)
                    else str(message.payload)
                )
                if payload == "online":
                    _LOGGER.info("Home Assistant is back online; replaying discovery")
                    await self._publish_birth()

    # -- publishing --------------------------------------------------------

    async def _publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        client = self._client
        if client is None:
            _LOGGER.warning("MQTT not connected; dropping publish to %s", topic)
            return
        try:
            await client.publish(topic, json.dumps(payload), qos=1, retain=retain)
        except aiomqtt.MqttError as err:
            _LOGGER.warning("Publish to %s failed: %s", topic, err)

    async def _publish_birth(self) -> None:
        """Bridge state, info, devices, discovery and availability snapshots."""
        await self._publish(self._state_topic(), {"state": "online"}, retain=True)
        await self._publish(
            f"{self._base}/bridge/info", bridge_info_payload(self._config), retain=True
        )
        await self._publish(
            f"{self._base}/bridge/devices",
            bridge_devices_payload(self._config),
            retain=True,
        )
        if self._config.homeassistant.discovery:
            for target in self._config.targets:
                await self._publish(
                    device_discovery_topic(self._config, target),
                    device_discovery_payload(self._config, target),
                    retain=True,
                )
            for name, event in self._published_triggers:
                target = self._target_by_name(name)
                if target is not None:
                    await self._publish(
                        trigger_discovery_topic(self._config, target, event),
                        trigger_discovery_payload(self._config, target, event),
                        retain=True,
                    )
        for name, online in self._availability.items():
            await self._publish(
                f"{self._base}/{name}/availability",
                {"state": "online" if online else "offline"},
                retain=True,
            )

    def _target_by_name(self, name: str) -> TargetConfig | None:
        for target in self._config.targets:
            if target.friendly_name == name:
                return target
        return None

    async def _publish_availability(self, target: TargetConfig, online: bool) -> None:
        if self._availability.get(target.friendly_name) == online:
            return
        self._availability[target.friendly_name] = online
        _LOGGER.info(
            "Target %s is %s", target.friendly_name, "online" if online else "offline"
        )
        await self._publish(
            f"{self._base}/{target.friendly_name}/availability",
            {"state": "online" if online else "offline"},
            retain=True,
        )

    # -- trap handling -----------------------------------------------------

    def _on_trap(self, event: TrapEvent) -> None:
        asyncio.get_running_loop().create_task(self._handle_trap(event))

    async def _handle_trap(self, event: TrapEvent) -> None:
        target_id, payload = normalize_trap(self._config, event)
        _LOGGER.info(
            "Trap %s from %s (%s)", payload["event_type"], event.source_ip, target_id
        )
        # Events must never replay on subscribe: not retained.
        await self._publish(f"{self._base}/{target_id}/trap", payload, retain=False)

        target = self._config.target_for_ip(event.source_ip)
        if (
            target is not None
            and self._config.homeassistant.discovery
            and payload["event_type"] != UNKNOWN_EVENT
            and (target_id, payload["event_type"]) not in self._published_triggers
        ):
            self._published_triggers.add((target_id, payload["event_type"]))
            await self._publish(
                trigger_discovery_topic(self._config, target, payload["event_type"]),
                trigger_discovery_payload(
                    self._config, target, payload["event_type"]
                ),
                retain=True,
            )
