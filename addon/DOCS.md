# snmptrap2mqtt

Run the [snmptrap2mqtt](https://github.com/brianegge/snmptrap2mqtt) SNMP-trap →
MQTT bridge as a Home Assistant add-on. It listens for SNMPv1/v2c traps on UDP
162, normalizes them to JSON, and publishes them to your MQTT broker with Home
Assistant discovery — moving trap reception off the HA host and capturing
**which device sent each trap** from the UDP source address.

> This add-on only runs on Supervised / Home Assistant OS installs (add-ons
> need the Supervisor). On a bare Docker/Container install, run the published
> image directly instead — see the project README.

## Installation

1. Settings → Add-ons → Add-on Store → ⋮ → **Repositories**, and add
   `https://github.com/brianegge/snmptrap2mqtt`.
2. Install **snmptrap2mqtt** from the store, configure the options below, and
   start it.
3. Point your switches' SNMP trap recipients at this Home Assistant host, UDP
   162, with a community string listed in `communities`.

The add-on uses **host networking** so trap source IPs are preserved and it can
bind UDP 162 directly.

## Options

| Option | Required | Description |
|---|---|---|
| `mqtt_server` | yes | Broker URL, e.g. `mqtt://core-mosquitto:1883` (or `mqtts://…`). |
| `mqtt_username` | no | Broker username, if your broker requires auth. |
| `mqtt_password` | no | Broker password. |
| `base_topic` | no | MQTT topic root (default `snmptrap2mqtt`). |
| `discovery` | no | Publish HA MQTT discovery for each target (default `true`). Set `false` if another integration already represents the devices. |
| `listener_port` | no | UDP port to listen on (default `162`). |
| `communities` | no | Accepted v1/v2c community strings. An empty list accepts any. |
| `targets` | no | Known senders, matched by source IP — each `name` + `host`, optional `manufacturer`/`model`. Traps from unknown IPs are still published under a sanitized-IP topic but get no discovery. |
| `log_level` | no | `debug` / `info` / `warning` / `error`. |

### Example

```yaml
mqtt_server: mqtt://core-mosquitto:1883
mqtt_username: mqtt_user
mqtt_password: mqtt_pass
base_topic: snmptrap2mqtt
discovery: true
listener_port: 162
communities:
  - public
targets:
  - name: rack-switch
    host: 192.168.1.10
    manufacturer: Netgear
    model: GS728TP
log_level: info
```

## Topics & payloads

See the [project README](https://github.com/brianegge/snmptrap2mqtt#mqtt-topic-contract)
for the full topic contract and the normalized trap payload. The bridge also
appears as its own `snmptrap2mqtt` device (version, status, target count, and
the trap-destination address).
