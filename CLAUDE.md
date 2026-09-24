# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Goal

Maintain a small, local-first application for clustering, geotagging, tagging,
and optionally comparing street-art photos with Street Art Cities.

## Commands

```powershell
pip install -e .
python -m unittest discover -s tests
python -m street_art_photo_assistant
```

Run a single test module or case:

```powershell
python -m unittest tests.test_gps
python -m unittest tests.test_gps.GpsTests.test_repair_from_same_camera
```

Generate an offline cluster report directly from the CLI (no web server):

```powershell
python -m street_art_photo_assistant cluster --output _runs\manual
```

Optional visual support (OpenCV-based local cluster splitting/matching):

```powershell
pip install -e ".[visual]"
python -m street_art_photo_assistant cluster --visual --output _runs\manual
```

## Architecture

Data flow: local folders -> metadata scan -> selection preview -> tag/location
clustering -> optional local visual split -> optional Street Art Cities
adapter -> persistent run report -> local review and previewed metadata edits.

Each module owns one boundary; keep changes inside the right one rather than
cross-cutting:

- `config.py` — versioned JSON configuration, atomic persistence.
- `models.py` — shared photo, cluster, fingerprint, repair-plan, and run
  contracts (the typed data shapes other modules pass around).
- `photos.py` — discovers photos, normalizes metadata (capture time, GPS,
  flat IPTC/Windows keywords).
- `clustering.py` — selects and groups normalized records by tag/location,
  with optional OpenCV-assisted splitting.
- `metadata.py` — previewed, atomic flat-keyword writes only.
- `gps.py` — deterministic missing/manual GPS repair plans (same-camera or
  trusted cross-camera references).
- `change_log.py` — atomically records every applied metadata operation as
  JSON.
- `matching.py` — optional local OpenCV comparisons (no network).
- `workflow.py` — composes the network-free scan/preview/cluster/report
  pipeline used by both the CLI and the web layer.
- `sac.py` — the *only* Street Art Cities network boundary: refreshes the
  normalized city cache, gathers bounded nearby candidates, caches public
  reference images, and returns evidence without ever editing photos itself.
  `workflow.py` imports it lazily, only for an explicitly enabled target;
  matching-disabled runs make no SAC requests.
- `runs.py` — launches package subcommands without a shell; persists
  cancellable run manifests, logs, reports, summaries, and safe deletion.
- `diagnostics.py` — builds bounded, redacted, locally inspectable support
  ZIPs without copying raw reports or photo metadata.
- `web.py` — local Flask routes, selection tokens, persisted edit plans, path
  boundaries, artist-assisted review data, local file actions, and templates
  (`templates/`, `static/`). Leaflet 1.9.4 is bundled (BSD-2-Clause) for local
  GPS display; offline reports default to a generated coordinate grid, and
  optional network base-map tiles are presentation-only, never matching
  evidence.

### Write boundary

Read operations return normalized, immutable photo records. Write operations
accept a persisted plan containing file fingerprints and exact targets: the
full plan is preflighted before the first file changes, and a JSON change log
entry is appended for every successful write. Follow this preview-then-replay
pattern for any new metadata-writing feature — see Repository rules below.

## Repository rules

- Keep core workflows usable without network access.
- Put provider-specific behavior behind a narrow adapter.
- Never add personal photo paths, private datasets, credentials, or generated
  caches.
- Synthetic fixtures only.
- `_unknown` identifies an untagged artwork; `_wall` identifies a wall grouping.
- Do not hardcode user-specific labels or exclusion policies.
- Preview every metadata write, replay the exact approved target list, preserve
  unrelated metadata, and write a JSON change log.
- Prefer a focused module and test over a new standalone script.
- Update the relevant documentation with behavior changes.

## Further documentation

- [Requirements](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [Customization](docs/customization.md)
- [Data formats](docs/data-formats.md)
- [Workflows](docs/workflows.md)
- [Street Art Cities integration](docs/sac-integration.md)
- [Diagnostics and issue reports](docs/diagnostics.md)
- [Development](docs/development.md)
