"""CLI entry point: snmptrap2mqtt [-c config.yaml]."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from . import __version__
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
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    config_path = args.config
    if config_path is None and Path("config.yaml").is_file():
        config_path = Path("config.yaml")

    try:
        config = load_config(config_path)
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
