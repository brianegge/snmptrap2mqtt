"""Decode tests with synthesized trap PDUs (patterned on netgear_poe's suite)."""

from __future__ import annotations

import asyncio

from snmptrap2mqtt.const import OID_IF_INDEX
from snmptrap2mqtt.listener import (
    TrapEvent,
    TrapListener,
    decode_datagram,
    extract_if_index,
)

from .conftest import SWITCH_IP, make_v1_trap, make_v2c_trap

LINK_DOWN = "1.3.6.1.6.3.1.1.5.3"
LINK_UP = "1.3.6.1.6.3.1.1.5.4"
ADDR = (SWITCH_IP, 50161)


def test_extract_if_index() -> None:
    assert extract_if_index({f"{OID_IF_INDEX}.7": 7}) == 7
    assert extract_if_index({OID_IF_INDEX: 3}) == 3
    assert extract_if_index({"1.2.3": 9}) is None
    assert extract_if_index({f"{OID_IF_INDEX}.7": "junk"}) is None


def test_decode_v2c_link_down() -> None:
    data = make_v2c_trap(LINK_DOWN, [(f"{OID_IF_INDEX}.12", 12)])
    events = decode_datagram(data, ADDR)
    assert len(events) == 1
    event = events[0]
    assert event.trap_oid == LINK_DOWN
    assert event.source_ip == SWITCH_IP
    assert event.source_port == 50161
    assert event.version == "2c"
    assert event.community == "public"
    assert event.uptime == 123456
    assert event.if_index == 12
    assert event.varbinds[f"{OID_IF_INDEX}.12"] == 12


def test_decode_v2c_string_varbind() -> None:
    data = make_v2c_trap(LINK_UP, [("1.3.6.1.2.1.2.2.1.2.3", "Port 3: uplink")])
    (event,) = decode_datagram(data, ADDR)
    assert event.varbinds["1.3.6.1.2.1.2.2.1.2.3"] == "Port 3: uplink"


def test_decode_v1_generic_maps_to_v2_oid() -> None:
    # generic-trap 2 (linkDown) must normalize to the v2c linkDown OID.
    data = make_v1_trap(generic=2, varbinds=[(f"{OID_IF_INDEX}.5", 5)])
    (event,) = decode_datagram(data, ADDR)
    assert event.trap_oid == LINK_DOWN
    assert event.version == "1"
    assert event.if_index == 5


def test_decode_v1_enterprise_specific() -> None:
    data = make_v1_trap(enterprise="1.3.6.1.4.1.4526", generic=6, specific=17)
    (event,) = decode_datagram(data, ADDR)
    assert event.trap_oid == "1.3.6.1.4.1.4526.0.17"


def test_decode_garbage_returns_nothing() -> None:
    assert decode_datagram(b"not-snmp", ADDR) == []
    assert decode_datagram(b"", ADDR) == []


async def test_listener_community_filter() -> None:
    events: list[TrapEvent] = []
    listener = TrapListener(events.append, communities=["secret"])
    listener.datagram_received(make_v2c_trap(LINK_DOWN, community="public"), ADDR)
    assert events == []
    listener.datagram_received(make_v2c_trap(LINK_DOWN, community="secret"), ADDR)
    assert len(events) == 1


async def test_listener_accepts_any_when_unrestricted() -> None:
    events: list[TrapEvent] = []
    listener = TrapListener(events.append, communities=[])
    listener.datagram_received(make_v2c_trap(LINK_DOWN, community="whatever"), ADDR)
    assert len(events) == 1


async def test_listener_end_to_end_udp() -> None:
    """A real UDP round-trip on an ephemeral port."""
    events: list[TrapEvent] = []
    got_one = asyncio.Event()

    def on_trap(event: TrapEvent) -> None:
        events.append(event)
        got_one.set()

    listener = TrapListener(on_trap, communities=["public"])
    await listener.start("127.0.0.1", 0)
    port = listener._transport.get_extra_info("sockname")[1]

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, remote_addr=("127.0.0.1", port)
    )
    transport.sendto(make_v2c_trap(LINK_UP, [(f"{OID_IF_INDEX}.2", 2)]))
    await asyncio.wait_for(got_one.wait(), timeout=5)
    transport.close()
    listener.stop()

    assert events[0].trap_oid == LINK_UP
    assert events[0].source_ip == "127.0.0.1"
