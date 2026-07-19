"""Shared fixtures and trap-PDU synthesis helpers."""

from __future__ import annotations

import pytest
from pyasn1.codec.ber import encoder
from pysnmp.proto import api

from snmptrap2mqtt.config import Config

SWITCH_IP = "192.168.254.250"

CONFIG_YAML = """
mqtt:
  server: mqtt://192.168.254.30:1883
listener:
  communities: [public]
targets:
  - friendly_name: boiler-switch
    host: 192.168.254.250
    manufacturer: Netgear
    model: GS728TPv2
    liveness:
      interval: 60
  - friendly_name: attic-switch
    host: 192.168.254.251
"""


@pytest.fixture
def config(tmp_path) -> Config:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_YAML)
    from snmptrap2mqtt.config import load_config

    return load_config(path, environ={})


def make_v2c_trap(
    trap_oid: str,
    varbinds: list[tuple[str, object]] | None = None,
    community: str = "public",
    uptime: int = 123456,
) -> bytes:
    """Encode a v2c TRAP message the way a switch would send it."""
    proto = api.PROTOCOL_MODULES[api.SNMP_VERSION_2C]
    pdu = proto.TrapPDU()
    proto.apiPDU.set_defaults(pdu)
    binds = [
        ("1.3.6.1.2.1.1.3.0", proto.TimeTicks(uptime)),
        ("1.3.6.1.6.3.1.1.4.1.0", proto.ObjectIdentifier(trap_oid)),
    ]
    for oid, value in varbinds or []:
        if isinstance(value, int):
            value = proto.Integer(value)
        elif isinstance(value, str):
            value = proto.OctetString(value)
        binds.append((oid, value))
    proto.apiPDU.set_varbinds(pdu, binds)
    msg = proto.Message()
    proto.apiMessage.set_defaults(msg)
    proto.apiMessage.set_community(msg, community)
    proto.apiMessage.set_pdu(msg, pdu)
    return encoder.encode(msg)


def make_v1_trap(
    enterprise: str = "1.3.6.1.4.1.4526",
    generic: int = 2,  # linkDown
    specific: int = 0,
    community: str = "public",
    varbinds: list[tuple[str, object]] | None = None,
) -> bytes:
    """Encode a classic SNMPv1 Trap-PDU."""
    proto = api.PROTOCOL_MODULES[api.SNMP_VERSION_1]
    pdu = proto.TrapPDU()
    proto.apiTrapPDU.set_defaults(pdu)
    proto.apiTrapPDU.set_enterprise(pdu, enterprise)
    proto.apiTrapPDU.set_generic_trap(pdu, generic)
    proto.apiTrapPDU.set_specific_trap(pdu, specific)
    binds = []
    for oid, value in varbinds or []:
        if isinstance(value, int):
            value = proto.Integer(value)
        elif isinstance(value, str):
            value = proto.OctetString(value)
        binds.append((oid, value))
    proto.apiTrapPDU.set_varbinds(pdu, binds)
    msg = proto.Message()
    proto.apiMessage.set_defaults(msg)
    proto.apiMessage.set_community(msg, community)
    proto.apiMessage.set_pdu(msg, pdu)
    return encoder.encode(msg)
