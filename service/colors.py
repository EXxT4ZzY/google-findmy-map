"""Assign each device a distinct pin colour for the map.

A device's colour can be pinned explicitly via the ``GFM_DEVICE_COLORS``
environment variable (a JSON object mapping a device's canonic id *or*
its display name to a CSS colour). Anything not listed is given a colour
from a fixed palette by position, so devices in one poll never collide
(until there are more devices than palette entries, after which colours
repeat).
"""

import json
import logging
import re

log = logging.getLogger("findmy-map")

# A conservative set of CSS colour values: hex, or a plain CSS colour
# keyword. This is deliberately strict because the value ends up in an
# inline `style` attribute in the browser -- nothing with quotes,
# semicolons or angle brackets can get through.
_SAFE_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$|^[a-zA-Z]{3,20}$")

# Colour-blind-friendly qualitative palette (based on the classic
# "Wong"/"Tol" style sets), dark enough to read as a filled pin on the
# dark map tiles.
PALETTE = [
    "#4e9bff",  # blue
    "#f2545b",  # red
    "#2ec4b6",  # teal
    "#ffb400",  # amber
    "#b085f5",  # purple
    "#5ad469",  # green
    "#ff8c42",  # orange
    "#e879c7",  # pink
]


def parse_overrides(raw) -> dict:
    """Parse the ``GFM_DEVICE_COLORS`` value; ``{}`` on anything unusable."""
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("Ignoring invalid GFM_DEVICE_COLORS (%s)", exc)
        return {}
    if not isinstance(data, dict):
        log.warning("Ignoring GFM_DEVICE_COLORS: expected a JSON object")
        return {}

    clean = {}
    for key, value in data.items():
        if isinstance(value, str) and _SAFE_COLOR.match(value.strip()):
            clean[key] = value.strip()
        else:
            log.warning("Ignoring GFM_DEVICE_COLORS entry %r: %r is not a plain colour", key, value)
    return clean


def resolve_color(
    device_id: str,
    device_name: str,
    overrides: dict,
    fallback_index: int = 0,
    override_color=None,
) -> str:
    """Return the pin colour for a device.

    Precedence: ``override_color`` (an explicit per-device choice made in
    the web UI), then the ``GFM_DEVICE_COLORS`` override by id, then by
    name, then ``PALETTE[fallback_index % len(PALETTE)]``. The caller
    supplies ``fallback_index`` (e.g. the device's position in a stably
    sorted list) so unconfigured devices get different colours.
    """
    if override_color:
        return override_color
    if device_id in overrides:
        return overrides[device_id]
    if device_name in overrides:
        return overrides[device_name]

    return PALETTE[fallback_index % len(PALETTE)]
