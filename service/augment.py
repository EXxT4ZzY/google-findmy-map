"""Enrich a raw poll result with the data the web UI needs.

``locations.poll_all_devices()`` returns one dict per device holding just
the latest fix (or an error). Before handing that to the frontend we
attach:

* ``history`` - the trailing track (last few geo fixes) from the store;
* ``color`` - the pin colour for the map (see ``colors.resolve_color``);
* ``name`` / ``default_name`` - the effective display name and the
  unmodified name reported by Google Find My (so the editor can offer a
  "reset to default");
* ``last_location_time`` - the timestamp of the most recent known fix,
  which survives a failed poll because it comes from the store.

It also persists the polled name into the store on every call, so it
survives the device later dropping out of the live poll list (see
``LocationStore.known_devices()``, used by the timeline's device picker).
"""

import colors

RECENT_TRACK_LENGTH = 5


def augment_device(
    device: dict,
    store,
    color_overrides: dict,
    color_index: int = 0,
    settings: dict | None = None,
) -> dict:
    """Mutate and return ``device`` with history/name/colour/last-seen fields.

    A fresh geo fix on ``device`` is written to ``store``. ``color_index``
    is the device's position in a stable ordering, used to pick a distinct
    palette colour when nothing else applies. ``settings`` is the
    ``{device_id: {"name", "color"}}`` map of per-device overrides made in
    the web UI.
    """
    if device.get("type") == "geo":
        store.add(device["id"], {
            "latitude": device["latitude"],
            "longitude": device["longitude"],
            "time": device.get("time"),
            "accuracy": device.get("accuracy"),
        })

    override = (settings or {}).get(device["id"], {})

    # Preserve the polled name across repeated augmentation of the same dict.
    device.setdefault("default_name", device.get("name", ""))
    device["name"] = override.get("name") or device["default_name"]
    device["name_is_custom"] = bool(override.get("name"))
    device["color_is_custom"] = bool(override.get("color"))
    device["group"] = override.get("group") or None
    # Remembered even after the device drops out of the live poll list --
    # see LocationStore.known_devices().
    store.set_last_seen_name(device["id"], device["default_name"])

    track = store.recent(device["id"], RECENT_TRACK_LENGTH)
    device["history"] = track
    device["color"] = colors.resolve_color(
        device["id"],
        device["name"],
        color_overrides,
        color_index,
        override_color=override.get("color"),
    )
    device["last_location_time"] = track[-1]["time"] if track else device.get("time")
    return device
