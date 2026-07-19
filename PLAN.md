# snmptrap2mqtt — Plan

A standalone daemon (modeled on zigbee2mqtt) that receives SNMP traps on a host
separate from Home Assistant, publishes them to MQTT, and integrates with the
`homeassistant-netgear-poe` custom component so its existing entities react to
traps without HA itself listening on UDP 162.

## Why

- `homeassistant-netgear-poe` already has an in-process trap receiver
  (`custom_components/netgear_poe/trap_receiver.py`) bound to UDP 162 on the HA
  host. That couples trap reception to the HA host (privileged port, container
  networking, single consumer) and can't distinguish which switch sent a trap
  (source IP is ignored).
- Moving reception to a dedicated bridge follows the proven zigbee2mqtt /
  zwavejs2mqtt pattern already used on this network (both run on the garage RPi
  and talk to HA over MQTT at 192.168.254.30).
- A generic bridge also serves future non-Netgear SNMP devices (UPSes, printers,
  cameras) via standard HA MQTT discovery, with no per-device HA code.

## Environment facts (from egge-network docs)

| Thing | Value |
|---|---|
| MQTT broker | 192.168.254.30 |
| LibreNMS + snmptrapd container | 192.168.254.35 (already binds UDP 162 there) |
| Candidate bridge host | garage RPi (already runs zigbee2mqtt/zwavejs2mqtt) or any other host — **not** .35 unless using a different port |
| Switches | boiler-switch GS728TPv2 (.250), attic-switch (.251), deck-switch (.252), dining-switch (192.168.253.2, IPCAMS VLAN) |

Coexistence with LibreNMS: Netgear Smart Managed switches support multiple trap
destinations, so switches send traps to both LibreNMS (.35) and the bridge.
`netgear_poe` already knows how to register a trap destination via the web API
(`async_ensure_trap_destination`, posts `snmp_trapConfgAdd`) — reuse that to
register the bridge's IP instead of HA's. The dining-switch is on the IPCAMS
VLAN; confirm UDP 162 is routable from 192.168.253.0/24 to the bridge host.

## Naming note

Named `snmptrap2mqtt` (decided 2026-07-19): the bridge is deliberately
event-only, the name follows the `snmptrapd` / `zigbee2mqtt` conventions, and
it avoids any tangle with dchesterton/snmp2mqtt (TypeScript, polling only, no
traps, dormant since Jan 2022).

## Architecture

```
switches ──UDP 162 traps──► snmptrap2mqtt daemon ──MQTT──► broker (.30) ──► Home Assistant
   ▲                        (separate host)                              ├─ mqtt discovery: event entities,
   └── also send to LibreNMS snmptrapd (.35), unchanged                  │  device triggers (generic devices)
                                                                         └─ netgear_poe: subscribes to trap
                                                                            topics, updates existing entities
```

### Stack

- **Python 3.12+ / asyncio** — enables direct reuse of the proven pysnmp
  receiver logic in `netgear_poe/trap_receiver.py` (pysnmp 7.1.x
  `NotificationReceiver`). MQTT via `aiomqtt` (or paho-mqtt v2).
- Config: single YAML file, zigbee2mqtt-style, env-var overrides
  (`SNMPTRAP2MQTT_CONFIG_MQTT_SERVER=...`).
- Distribution: Docker image (also runs bare with `pip install`). UDP 162 is
  privileged: run with `--net=host` + `cap_add: NET_BIND_SERVICE`, or bind an
  unprivileged port (default 162, configurable e.g. 1162) and port-map.

### Config file sketch

```yaml
mqtt:
  server: mqtt://192.168.254.30:1883
  base_topic: snmptrap2mqtt
  # username/password/tls optional
homeassistant:
  discovery: true
  discovery_prefix: homeassistant
listener:
  bind: 0.0.0.0
  port: 162
  communities: [public]        # accepted v2c/v1 communities; [] = accept any
targets:                        # optional; unknown sources still published under a sanitized IP id
  - friendly_name: boiler-switch
    host: 192.168.254.250
    manufacturer: Netgear
    model: GS728TPv2
    liveness:                   # drives availability topic
      oid: 1.3.6.1.2.1.1.3.0   # sysUpTime
      interval: 60
traps:                          # OID → event name map (built-ins included)
  1.3.6.1.6.3.1.1.5.3: linkDown
  1.3.6.1.6.3.1.1.5.4: linkUp
  1.3.6.1.2.1.105.0.1: poePortChange   # pethPsePortOnOffNotification
  1.3.6.1.6.3.1.1.5.1: coldStart
  1.3.6.1.6.3.1.1.5.5: authenticationFailure
```

### MQTT topic contract (the API the HA side consumes)

| Topic | Retained | Payload |
|---|---|---|
| `snmptrap2mqtt/bridge/state` | yes (LWT) | `{"state":"online"}` / `{"state":"offline"}` |
| `snmptrap2mqtt/bridge/info` | yes | version, config summary, target list |
| `snmptrap2mqtt/bridge/devices` | yes | JSON list of known targets (name, host, model) |
| `snmptrap2mqtt/<target>/trap` | **no** (events must not replay) | see below |
| `snmptrap2mqtt/<target>/availability` | yes | `{"state":"online"}` from liveness poll |
| `snmptrap2mqtt/bridge/request/<cmd>` → `response/<cmd>` | no | admin RPC (reload, add target) — later phase |

Trap payload (normalized; this is the correlation contract with `netgear_poe`):

```json
{
  "event_type": "linkDown",
  "trap_oid": "1.3.6.1.6.3.1.1.5.3",
  "source_ip": "192.168.254.250",
  "target": "boiler-switch",
  "if_index": 12,
  "uptime": 123456,
  "varbinds": {"1.3.6.1.2.1.2.2.1.1.12": 12, "...": "..."}
}
```

`if_index` is extracted when a varbind matches ifIndex (`1.3.6.1.2.1.2.2.1.1`),
mirroring `trap_receiver.py`'s parsing (including the `MAX_PHYSICAL_PORT = 64`
LAG/CPU filter — but do the filtering in HA, not the bridge; the bridge stays
policy-free). **Source IP is taken from the UDP transport address** — this fixes
the multi-switch ambiguity the in-process receiver has today.

### Home Assistant discovery (generic path)

- **Device-based discovery**: one retained payload per target at
  `homeassistant/device/snmptrap2mqtt_<id>/config` with `dev` (identifiers
  `snmptrap2mqtt_<host-or-mac>`, manufacturer/model from config), `o` origin block,
  and `cmps`:
  - `event` entity per target — `state_topic: snmptrap2mqtt/<target>/trap`,
    `event_types` = configured trap names; extra JSON keys (if_index, source_ip)
    become attributes. Non-retained by design.
  - `binary_sensor` (connectivity, diagnostic) from the availability topic.
- **Device triggers** (`device_automation`) per trap type for nice automation-UI
  UX, discovered lazily on first occurrence (zigbee2mqtt's pattern).
- Subscribe to `homeassistant/status`; on `online` re-publish all discovery
  configs and current availability states (canonical birth handling).
- Every entity lists two availability topics: `bridge/state` and the target's
  availability topic.

Note: these MQTT devices cannot merge into the existing `netgear_poe` device
registry entries (identifier domains differ), so for Netgear switches the
generic discovery is optional/off by default — the netgear_poe path below is
the primary integration and avoids duplicate devices.

### netgear_poe integration (the point of the exercise)

Changes in `homeassistant-netgear-poe`:

1. **New config option** per entry: trap source = `local` (today's UDP 162
   receiver) | `mqtt` (snmptrap2mqtt) | `disabled`. Add `mqtt` to
   `after_dependencies` in `manifest.json`.
2. **MQTT mode**: in `async_setup_entry`, subscribe via
   `homeassistant.components.mqtt.async_subscribe` to
   `snmptrap2mqtt/+/trap` (or a configured base topic). On message:
   - Match `source_ip` (or `target` name) against the entry's `CONF_HOST`.
   - Apply the ≤ `MAX_PHYSICAL_PORT` filter, then call the existing
     `coordinator.apply_link_trap(if_index, up)` for linkUp/linkDown —
     no changes needed downstream; entities update instantly exactly as today.
   - Wire `poePortChange` to the already-present-but-unused `on_poe_event`
     path: trigger `async_request_refresh()` so PoE power/state catches up.
3. **Trap destination registration**: extend the options so
   `async_ensure_trap_destination` registers the *bridge host IP* (new config
   field) instead of HA's local IP when in MQTT mode. The web-API plumbing
   already exists for all backend generations.
4. **Bridge availability**: subscribe to `snmptrap2mqtt/bridge/state`; when offline,
   log once and rely on the existing 30 s SNMP polling backstop (no entity
   changes needed — polling already covers dropped traps).

Nothing else in the component changes; the coordinator, entities, and unique IDs
stay as-is.

## Phases

**Phase 1 — core daemon (MVP)**
- Repo scaffold: `pyproject.toml`, `snmptrap2mqtt/` package, pytest, ruff.
- Config loader + validation (pydantic or voluptuous).
- Trap listener: port `trap_receiver.py`'s pysnmp NotificationReceiver logic,
  add source-IP capture, community filtering, v1+v2c.
- MQTT client with LWT (`bridge/state`), publish normalized trap JSON.
- Unit tests with synthesized trap PDUs (reuse patterns from
  `tests/test_trap_receiver.py` in netgear-poe).
- Exit criterion: unplug a device from boiler-switch → JSON appears on
  `snmptrap2mqtt/boiler-switch/trap` within ~1 s (verify with `mosquitto_sub`).

**Phase 2 — HA discovery + availability**
- Liveness poller (sysUpTime) → per-target availability topics.
- Device-based discovery publishing (event entity + connectivity sensor),
  `homeassistant/status` birth handling, discovery removal on target delete.
- Exit criterion: switches appear as HA devices with working event entities,
  survive HA restart, go unavailable when bridge stops.

**Phase 3 — netgear_poe MQTT mode**
- The four changes listed above, plus tests (mock MQTT messages →
  `apply_link_trap` calls; source-IP mismatch ignored).
- Exit criterion: with local receiver disabled, link binary_sensors flip within
  ~1 s of cable pull, and PoE state refreshes on poePortChange.

**Phase 4 — packaging & ops**
- Dockerfile + compose example (garage RPi, arm), README, MkDocs page in
  egge-network docs, systemd unit alternative.
- Register bridge as trap destination on all four switches; confirm LibreNMS
  still receives traps (both destinations configured).
- Optional/backlog: SNMPv3 traps, `bridge/request` RPC, arbitrary OID polling
  (dchesterton/snmp2mqtt already covers pure polling — low priority), frontend.

## Risks / open questions

- **UDP 162 on the bridge host**: needs cap/host networking in Docker; decide
  final host (garage RPi is natural but is a 3B+ — load is trivial though).
- **IPCAMS VLAN routing** for dining-switch traps to the bridge host.
- **Trap delivery is best-effort UDP** — the netgear_poe 30 s polling backstop
  stays enabled; the bridge does not attempt reliability.
- **Security**: v2c community is plaintext; restrict accepted communities and
  optionally source subnets in the listener; MQTT auth + TLS to broker.
- Whether to also emit per-port state topics from the bridge (would duplicate
  netgear_poe polling — recommend no; bridge stays event-only for Netgear).
