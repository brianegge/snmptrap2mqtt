#!/bin/sh
# Pick the config source at startup so one image serves both worlds:
#   - Home Assistant add-on: HA writes /data/options.json; `main` maps it.
#   - Standalone container:  a config.yaml is mounted at /app/data/config.yaml.
# Extra args passed to the container are forwarded either way.
set -e

if [ -f /data/options.json ]; then
    exec snmptrap2mqtt "$@"
fi
exec snmptrap2mqtt -c /app/data/config.yaml "$@"
