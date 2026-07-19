"""Trap normalization — the correlation contract consumed by netgear_poe."""

from __future__ import annotations

from snmptrap2mqtt.bridge import normalize_trap
from snmptrap2mqtt.config import Config
from snmptrap2mqtt.const import OID_IF_INDEX
from snmptrap2mqtt.listener import decode_datagram

from .conftest import SWITCH_IP, make_v2c_trap

LINK_DOWN = "1.3.6.1.6.3.1.1.5.3"


def _event(config: Config, data: bytes, ip: str = SWITCH_IP):
    (event,) = decode_datagram(data, (ip, 50161))
    return normalize_trap(config, event)


def test_normalize_known_target(config: Config) -> None:
    target_id, payload = _event(
        config, make_v2c_trap(LINK_DOWN, [(f"{OID_IF_INDEX}.12", 12)])
    )
    assert target_id == "boiler-switch"
    assert payload == {
        "event_type": "linkDown",
        "trap_oid": LINK_DOWN,
        "source_ip": SWITCH_IP,
        "target": "boiler-switch",
        "if_index": 12,
        "uptime": 123456,
        "varbinds": {
            "1.3.6.1.2.1.1.3.0": 123456,
            "1.3.6.1.6.3.1.1.4.1.0": LINK_DOWN,
            f"{OID_IF_INDEX}.12": 12,
        },
    }


def test_normalize_unknown_source_gets_sanitized_ip(config: Config) -> None:
    target_id, payload = _event(config, make_v2c_trap(LINK_DOWN), ip="10.0.0.99")
    assert target_id == "10_0_0_99"
    assert payload["target"] == "10_0_0_99"
    assert payload["source_ip"] == "10.0.0.99"


def test_normalize_unmapped_oid_is_unknown_event(config: Config) -> None:
    _, payload = _event(config, make_v2c_trap("1.2.3.4.5"))
    assert payload["event_type"] == "unknown"
    assert payload["trap_oid"] == "1.2.3.4.5"


def test_normalize_lag_ifindex_not_filtered(config: Config) -> None:
    """The bridge stays policy-free: ifIndex > 64 passes through untouched."""
    _, payload = _event(
        config, make_v2c_trap(LINK_DOWN, [(f"{OID_IF_INDEX}.1000", 1000)])
    )
    assert payload["if_index"] == 1000
