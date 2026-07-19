"""UDP trap listener: decode SNMPv1/v2c trap datagrams into TrapEvents.

Uses a plain asyncio DatagramProtocol with pysnmp's low-level proto.api
decoder (the documented manual trap-receiver pattern) instead of the full
SNMP engine. That keeps the source address of every datagram — the fix for
the multi-switch ambiguity in netgear_poe's in-process receiver — and lets
community acceptance be bridge policy (a configured list, or accept-any)
rather than engine registration. ifIndex extraction mirrors
netgear_poe/trap_receiver.py; the bridge itself applies no port filtering.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pyasn1.codec.ber import decoder
from pyasn1.error import PyAsn1Error
from pyasn1.type import univ
from pysnmp.proto import api
from pysnmp.proto.rfc1155 import IpAddress as IpAddressV1
from pysnmp.proto.rfc1902 import IpAddress as IpAddressV2

from .const import OID_IF_INDEX, OID_SNMP_TRAP, OID_SYS_UPTIME, SNMP_TRAPS_PREFIX

_LOGGER = logging.getLogger(__name__)


@dataclass
class TrapEvent:
    """One decoded trap, normalized to v2c semantics."""

    source_ip: str
    source_port: int
    version: str  # "1" or "2c"
    community: str
    trap_oid: str
    uptime: int | None = None
    varbinds: dict[str, Any] = field(default_factory=dict)

    @property
    def if_index(self) -> int | None:
        return extract_if_index(self.varbinds)


def extract_if_index(binds: dict[str, Any]) -> int | None:
    """Pull the ifIndex value out of a trap's varbinds (ported from netgear_poe)."""
    for oid, value in binds.items():
        if oid == OID_IF_INDEX or oid.startswith(OID_IF_INDEX + "."):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _to_python(value: Any) -> Any:
    """Convert a pyasn1 varbind value into a JSON-serializable Python value."""
    if isinstance(value, univ.Null) or value is None:
        return None
    if isinstance(value, univ.ObjectIdentifier):
        return str(value)
    if isinstance(value, IpAddressV1 | IpAddressV2):
        return value.prettyPrint()
    if isinstance(value, univ.Integer):
        # Covers TimeTicks, Counter and Gauge — all Integer subtypes.
        return int(value)
    if isinstance(value, univ.OctetString):
        raw = bytes(value)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + raw.hex()
        if text.isprintable() or text == "":
            return text
        return "0x" + raw.hex()
    return value.prettyPrint()


def _v1_trap_oid(enterprise: str, generic: int, specific: int) -> str:
    """RFC 2576 3.1: map a v1 trap-PDU to its v2c snmpTrapOID."""
    if 0 <= generic <= 5:
        return f"{SNMP_TRAPS_PREFIX}.{generic + 1}"
    return f"{enterprise}.0.{specific}"


def decode_datagram(data: bytes, addr: tuple[str, int]) -> list[TrapEvent]:
    """Decode one UDP datagram; returns [] for non-trap or malformed messages."""
    events: list[TrapEvent] = []
    msg = data
    while msg:
        try:
            version = int(api.decodeMessageVersion(msg))
            proto = api.PROTOCOL_MODULES[version]
            req_msg, msg = decoder.decode(msg, asn1Spec=proto.Message())
        except (PyAsn1Error, KeyError, ValueError, TypeError):
            _LOGGER.debug("Undecodable datagram from %s", addr[0], exc_info=True)
            return events
        community = str(proto.apiMessage.get_community(req_msg))
        pdu = proto.apiMessage.get_pdu(req_msg)
        if not pdu.isSameTypeWith(proto.TrapPDU()):
            _LOGGER.debug("Non-trap SNMP message from %s ignored", addr[0])
            continue
        if version == api.SNMP_VERSION_1:
            events.append(_decode_v1(proto, pdu, community, addr))
        else:
            events.append(_decode_v2c(proto, pdu, community, addr))
    return events


def _decode_v1(
    proto: Any, pdu: Any, community: str, addr: tuple[str, int]
) -> TrapEvent:
    trap_oid = _v1_trap_oid(
        str(proto.apiTrapPDU.get_enterprise(pdu)),
        int(proto.apiTrapPDU.get_generic_trap(pdu)),
        int(proto.apiTrapPDU.get_specific_trap(pdu)),
    )
    varbinds = {
        str(oid): _to_python(value)
        for oid, value in proto.apiTrapPDU.get_varbinds(pdu)
    }
    return TrapEvent(
        source_ip=addr[0],
        source_port=addr[1],
        version="1",
        community=community,
        trap_oid=trap_oid,
        uptime=int(proto.apiTrapPDU.get_timestamp(pdu)),
        varbinds=varbinds,
    )


def _decode_v2c(
    proto: Any, pdu: Any, community: str, addr: tuple[str, int]
) -> TrapEvent:
    varbinds = {
        str(oid): _to_python(value) for oid, value in proto.apiPDU.get_varbinds(pdu)
    }
    trap_oid = str(varbinds.get(OID_SNMP_TRAP, ""))
    uptime_raw = varbinds.get(OID_SYS_UPTIME)
    try:
        uptime = int(uptime_raw) if uptime_raw is not None else None
    except (TypeError, ValueError):
        uptime = None
    return TrapEvent(
        source_ip=addr[0],
        source_port=addr[1],
        version="2c",
        community=community,
        trap_oid=trap_oid,
        uptime=uptime,
        varbinds=varbinds,
    )


class TrapListener(asyncio.DatagramProtocol):
    """Bind UDP and hand every accepted TrapEvent to a callback."""

    def __init__(
        self,
        on_trap: Callable[[TrapEvent], None],
        communities: list[str],
    ) -> None:
        self._on_trap = on_trap
        self._communities = communities
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        for event in decode_datagram(data, addr):
            if self._communities and event.community not in self._communities:
                _LOGGER.warning(
                    "Dropped trap from %s: community %r not accepted",
                    event.source_ip,
                    event.community,
                )
                continue
            _LOGGER.debug(
                "Trap from %s: %s (ifIndex=%s)",
                event.source_ip,
                event.trap_oid,
                event.if_index,
            )
            self._on_trap(event)

    async def start(self, bind: str, port: int) -> None:
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: self, local_addr=(bind, port))
        _LOGGER.info("SNMP trap listener bound to %s:%d", bind, port)

    def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
