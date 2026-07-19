"""Per-target liveness polling (sysUpTime GET) driving availability topics."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from pysnmp.hlapi.v1arch.asyncio import (
    CommunityData,
    ObjectIdentity,
    ObjectType,
    SnmpDispatcher,
    UdpTransportTarget,
    get_cmd,
)

from .config import TargetConfig

_LOGGER = logging.getLogger(__name__)


async def snmp_get(
    host: str, port: int, community: str, oid: str, timeout: float = 5.0
) -> bool:
    """One SNMP v2c GET; True when the target answered with a value."""
    dispatcher = SnmpDispatcher()
    try:
        transport = await UdpTransportTarget.create((host, port), timeout=timeout)
        error_indication, error_status, _, varbinds = await get_cmd(
            dispatcher,
            CommunityData(community),
            transport,
            ObjectType(ObjectIdentity(oid)),
        )
        return error_indication is None and not error_status and bool(varbinds)
    except Exception:
        _LOGGER.debug("SNMP GET %s failed", host, exc_info=True)
        return False
    finally:
        dispatcher.transport_dispatcher.close_dispatcher()


class LivenessPoller:
    """Poll one target's liveness OID and report online/offline transitions.

    The callback fires on every state determination (not just changes); the
    bridge decides when to publish. `retries` consecutive failures flip the
    target offline — one lost UDP poll must not flap availability.
    """

    def __init__(
        self,
        target: TargetConfig,
        default_community: str,
        on_state: Callable[[TargetConfig, bool], Awaitable[None]],
    ) -> None:
        assert target.liveness is not None
        self._target = target
        self._liveness = target.liveness
        self._community = target.liveness.community or default_community
        self._on_state = on_state
        self._failures = 0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(
            self._run(), name=f"liveness:{self._target.friendly_name}"
        )

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        while True:
            up = await snmp_get(
                self._target.host,
                self._liveness.port,
                self._community,
                self._liveness.oid,
            )
            if up:
                self._failures = 0
                await self._on_state(self._target, True)
            else:
                self._failures += 1
                if self._failures >= self._liveness.retries:
                    await self._on_state(self._target, False)
            await asyncio.sleep(self._liveness.interval)
