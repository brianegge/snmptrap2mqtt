# snmptrap2mqtt

An SNMP trap → MQTT bridge: a small daemon that listens for SNMPv1/v2c traps on
UDP 162, normalizes them to JSON, and publishes them to an MQTT broker with Home
Assistant MQTT discovery. It moves trap reception off the Home Assistant host
(privileged port, container networking, single consumer) onto any box on the
network, and captures **which device sent each trap** from the UDP source
address.

It's built to pair with the
[homeassistant-netgear-poe](https://github.com/brianegge/homeassistant-netgear-poe)
integration: the bridge delivers instant link/PoE trap events that the
integration applies to its switch entities, so changes show up immediately
instead of waiting for the next poll. It works fine standalone too.

```
switches ──UDP 162 traps──► snmptrap2mqtt ──MQTT──► broker ──► Home Assistant
   └── can also keep sending to LibreNMS snmptrapd, unchanged
```

The bridge is deliberately **event-only**: no polling of arbitrary OIDs, no
per-port state mirroring. Its one poll is an optional per-target liveness
check (sysUpTime) that drives availability topics. For SNMP *polling* to MQTT
see [dchesterton/snmp2mqtt](https://github.com/dchesterton/snmp2mqtt).

## Quick start

```sh
pip install .
cp example-config.yaml config.yaml   # edit broker/targets
snmptrap2mqtt -c config.yaml
```

Verify with a cable pull (or `snmptrap` from net-snmp) and:

```sh
mosquitto_sub -h 192.168.254.30 -t 'snmptrap2mqtt/#' -v
```

### Docker

A multi-arch image (amd64/arm64) is published to GHCR on every push to `main`
and on version tags:

```sh
docker pull ghcr.io/brianegge/snmptrap2mqtt:latest
docker compose up -d    # see docker-compose.example.yml
```

UDP 162 is privileged. Either run with host networking plus
`cap_add: [NET_BIND_SERVICE]`, or set `listener.port: 1162` and port-map
`162:1162/udp`.

A systemd alternative is in `systemd/snmptrap2mqtt.service`.

### Home Assistant add-on

On **Supervised / Home Assistant OS** installs you can run the bridge as an
add-on (the same GHCR image — no rebuild): Settings → Add-ons → Add-on Store →
⋮ → **Repositories**, add `https://github.com/brianegge/snmptrap2mqtt`, then
install **snmptrap2mqtt** and configure it in the UI. See [`addon/DOCS.md`](addon/DOCS.md).
The image detects the add-on's `/data/options.json` and configures itself from
it; standalone runs keep reading `config.yaml`.

## Configuration

See [`example-config.yaml`](example-config.yaml). Every key can be overridden
via environment: `SNMPTRAP2MQTT_CONFIG_MQTT_SERVER=mqtt://host:1883`,
`SNMPTRAP2MQTT_CONFIG_LISTENER_PORT=1162`, etc.

- `listener.communities`: accepted v1/v2c community strings; `[]` accepts any.
- `targets`: known senders, matched by source IP. Traps from unknown IPs are
  still published under a sanitized IP topic (`snmptrap2mqtt/10_0_0_99/trap`)
  but get no HA discovery.
- `traps`: OID → event-name map. linkUp/linkDown, coldStart/warmStart,
  authenticationFailure and poePortChange (POWER-ETHERNET-MIB) are built in.

## MQTT topic contract

| Topic | Retained | Payload |
|---|---|---|
| `snmptrap2mqtt/bridge/state` | yes (LWT) | `{"state":"online"}` / `{"state":"offline"}` |
| `snmptrap2mqtt/bridge/info` | yes | version, config summary, target list, `listener.address` |
| `snmptrap2mqtt/bridge/devices` | yes | JSON list of configured targets |
| `snmptrap2mqtt/<target>/trap` | **no** | normalized trap (below) |
| `snmptrap2mqtt/<target>/availability` | yes | `{"state":"online"}` from the liveness poll |

Trap payload — the correlation contract consumed by
[homeassistant-netgear-poe](https://github.com/brianegge/homeassistant-netgear-poe)'s
MQTT trap mode:

```json
{
  "event_type": "linkDown",
  "trap_oid": "1.3.6.1.6.3.1.1.5.3",
  "source_ip": "192.168.254.250",
  "target": "boiler-switch",
  "if_index": 12,
  "uptime": 123456,
  "varbinds": {"1.3.6.1.2.1.2.2.1.1.12": 12}
}
```

`if_index` is extracted when a varbind matches IF-MIB ifIndex
(`1.3.6.1.2.1.2.2.1.1`). The bridge applies **no policy** — LAG/CPU interface
filtering (ifIndex > 64) is the consumer's job. SNMPv1 traps are normalized to
v2c semantics (RFC 2576 trap-OID mapping), so consumers see one format.

## Home Assistant

The **bridge itself** always appears in HA as a device named `snmptrap2mqtt`,
independent of the `homeassistant.discovery` switch below — it reports the
daemon, not the switch ports, so it never duplicates a consumer's entities. It
carries the running **version**, a **Status** connectivity sensor (online/off
via the LWT), a **Targets** count, and a **Trap destination** sensor: the
routable address (`listener.address` in `bridge/info`) switches should send
traps to, resolved past a `0.0.0.0` bind-all. A downstream integration can read
that field to learn where to point trap recipients instead of asking for it.

With `homeassistant.discovery: true`, each configured **target** additionally
appears as an MQTT device with an **event entity** (trap stream; extra payload
keys become attributes) and, when liveness polling is configured, a
**connectivity** diagnostic sensor. MQTT **device triggers** are published
lazily the first time each trap type occurs, so trap-driven automations can be
built in the automation UI. Discovery and availability are replayed whenever HA
announces itself on `homeassistant/status` (birth message).

Traps are best-effort UDP: keep an authoritative polling backstop (netgear_poe
polls every 30 s) for anything that must not miss a state change.

## Development

```sh
uv venv && uv pip install -e '.[dev]'
pytest
ruff check .
```
