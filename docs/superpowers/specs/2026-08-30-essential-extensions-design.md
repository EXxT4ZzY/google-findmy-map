# findmy-map — the four "nearly essential" extensions

## Summary

Four functionality gaps identified in a 2026-08-30 feature brainstorm, all
judged close to indispensable for a self-hosted Find My Device dashboard:

1. History retention/pruning — `history.db` currently grows unbounded.
2. Timeline device picker sourced from the DB, not the live poll — a
   removed device currently disappears from the picker even though its
   history is still there.
3. "Ring a device" (Play Sound) — the defining Find My Device action
   beyond passively viewing a map.
4. Semantic locations (named places without coordinates, e.g. "Home")
   surfaced in the UI instead of silently dropped.

## Findings that shaped the design

- **Play Sound is already fully implemented in the vendored upstream
  library** (`GoogleFindMyTools/NovaApi/ExecuteAction/PlaySound/`), using
  the same FCM-registration/`nova_request` pattern as the already-used
  `LocateTracker`. Only a thin wrapper plus an endpoint and a button were
  needed — no new protocol work.
- **A pre-existing bug**: `service/locations.py::poll_all_devices()` merges
  a device's latest fix straight into a `{"name": device_name, "id": ...}`
  entry via `dict.update()`. The semantic-location branch of
  `_extract_locations()` used to return a dict that *also* had a `"name"`
  key (the place name) — silently overwriting the device's own display
  name whenever its last fix was semantic-only. Fixed as part of (4) by
  renaming that key to `"place_name"`.
- **`SemanticLocation` has no coordinate fields at all**
  (`ProtoDecoders/Common.proto`: `message SemanticLocation { string
  locationName = 1; }`). A map pin for these is not just unimplemented, it
  is impossible with the data Google's API provides — the fix is
  necessarily UI-list-only, not a map marker.

## Goals

- `GFM_HISTORY_RETENTION_DAYS`, unset by default (unbounded history is
  preserved for every existing install unless the operator opts in),
  pruned at most once a day.
- `GET /api/devices`: every device ever seen (from `locations` and/or
  `device_settings`), with a name that survives the device dropping out of
  the live poll (`device_settings.last_known_name`, persisted on every
  poll, distinct from the user's manual rename).
- `POST /api/devices/{id}/ring` / `.../ring/stop`, wrapping
  `locations.start_sound`/`stop_sound`; a 🔔 button per device row.
- `place_name` on a semantic-only device entry, shown in the device list
  (`"{place} · {time}"`) instead of just a bare timestamp with no context.

## Non-goals (YAGNI)

Geofencing/arrival notifications (separate backlog item), a map
representation for semantic locations (technically impossible), a
server-side auto-stop timer for ringing (Google times it out on its own;
the client-side 30 s button reset is enough), per-device retention
overrides (one global knob is enough for a single-operator deployment).

## Architecture

No new tables. `device_settings` gains one nullable column,
`last_known_name TEXT`, added via an explicit migration
(`_migrate_schema()` in `store.py`, since `CREATE TABLE IF NOT EXISTS` is a
no-op on a DB that already has the table). `LocationStore` gains
`prune_older_than`, `known_devices`, `set_last_seen_name`.
`augment_device()` calls `set_last_seen_name` on every poll cycle, for
every device (geo, semantic, or error), so the name persists regardless of
fix type.

`service/main.py`'s poll loop gets a `_maybe_prune_history()` step,
checked once per cycle via a remembered last-pruned timestamp — no new
thread. Two new endpoints for devices/ring, following the existing
`Depends(block_cross_site)` pattern for anything state-changing.

`service/locations.py` gains `start_sound`/`stop_sound`, mirroring
`_fetch_device_update`'s FCM-registration/cleanup discipline but without
waiting for a response (Play Sound has none) — a short grace sleep instead
of a timeout-wait before removing the callback.

Frontend: `web/index.html` gets a ring button per row and renders
`place_name` for semantic devices; `web/timeline.html`'s device `<select>`
is populated from `GET /api/devices` instead of `GET /api/locations`
(still consulting `/api/locations` for the pin-colour map, best-effort).
