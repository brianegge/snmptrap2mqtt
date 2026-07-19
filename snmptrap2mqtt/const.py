"""Shared constants: well-known OIDs and the built-in trap name map."""

from __future__ import annotations

from typing import Final

# RFC 1907 / SNMPv2-MIB
OID_SNMP_TRAP: Final = "1.3.6.1.6.3.1.1.4.1.0"  # snmpTrapOID.0 varbind
OID_SYS_UPTIME: Final = "1.3.6.1.2.1.1.3.0"
# IF-MIB ifIndex column; trap varbinds carry ifIndex.<n>
OID_IF_INDEX: Final = "1.3.6.1.2.1.2.2.1.1"

# RFC 2576 3.1: v1 generic-trap 0..5 map to snmpTraps.<generic+1>
SNMP_TRAPS_PREFIX: Final = "1.3.6.1.6.3.1.1.5"

# Built-in trap OID -> event name map; config `traps:` entries extend/override.
BUILTIN_TRAPS: Final[dict[str, str]] = {
    "1.3.6.1.6.3.1.1.5.1": "coldStart",
    "1.3.6.1.6.3.1.1.5.2": "warmStart",
    "1.3.6.1.6.3.1.1.5.3": "linkDown",
    "1.3.6.1.6.3.1.1.5.4": "linkUp",
    "1.3.6.1.6.3.1.1.5.5": "authenticationFailure",
    # POWER-ETHERNET-MIB pethPsePortOnOffNotification
    "1.3.6.1.2.1.105.0.1": "poePortChange",
}

# Event name used when a trap OID has no configured mapping. It is listed in
# the discovery event_types so HA's event entity accepts the payload.
UNKNOWN_EVENT: Final = "unknown"
