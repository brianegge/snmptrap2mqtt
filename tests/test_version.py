"""The add-on manifest and the package must declare the same version.

Supervisor offers addon/config.yaml's ``version`` and pulls that image tag, while
the bridge reports ``snmptrap2mqtt.__version__`` at startup and as its Home
Assistant device's sw_version. Both are bumped by hand, so keep them in step.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

import snmptrap2mqtt

ROOT = Path(__file__).resolve().parent.parent


def test_addon_version_matches_package() -> None:
    manifest = yaml.safe_load((ROOT / "addon" / "config.yaml").read_text())
    assert str(manifest["version"]) == snmptrap2mqtt.__version__


def test_version_is_plain_semver() -> None:
    # release.yml tags vX.Y.Z and docker.yml's semver rules derive the image
    # tags from it; a pre-release or build suffix would not round-trip.
    assert re.fullmatch(r"\d+\.\d+\.\d+", snmptrap2mqtt.__version__)
