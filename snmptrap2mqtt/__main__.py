"""CLI entry point: snmptrap2mqtt [-c config.yaml]."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from . import __version__
from .addon import OPTIONS_PATH, config_from_options, load_options
from .bridge import Bridge
from .config import load_config

_LOGGER = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="snmptrap2mqtt",
        description="SNMP trap to MQTT bridge with Home Assistant discovery",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="path to YAML config (default: ./config.yaml if present)",
    )
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser.parse_args(argv)


async def _run(bridge: Bridge) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, bridge.stop)
    await bridge.run()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config_path = args.config

    # Add-on mode: no explicit -c, but HA left options at /data/options.json.
    addon_options: dict | None = None
    if config_path is None and OPTIONS_PATH.is_file():
        try:
            addon_options = load_options()
        except (OSError, ValueError) as err:
            logging.basicConfig(level=logging.ERROR)
            _LOGGER.error("Could not read add-on options: %s", err)
            return 2

    debug = args.debug or (
        isinstance(addon_options, dict)
        and str(addon_options.get("log_level", "")).lower() == "debug"
    )
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if config_path is None and addon_options is None and Path("config.yaml").is_file():
        config_path = Path("config.yaml")

    try:
        config = (
            config_from_options(addon_options)
            if addon_options is not None
            else load_config(config_path)
        )
    except Exception as err:
        _LOGGER.error("Invalid configuration: %s", err)
        return 2

    _LOGGER.info(
        "snmptrap2mqtt %s starting (broker %s, listener %s:%d, %d target(s))",
        __version__,
        config.mqtt.server,
        config.listener.bind,
        config.listener.port,
        len(config.targets),
    )
    try:
        asyncio.run(_run(Bridge(config)))
    except OSError as err:
        _LOGGER.error(
            "Could not bind UDP %s:%d (%s) — port 162 needs CAP_NET_BIND_SERVICE "
            "or use listener.port: 1162 with a port mapping",
            config.listener.bind,
            config.listener.port,
            err,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
