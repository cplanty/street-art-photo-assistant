# Architecture

## Data flow

```text
local folders
    -> metadata scan
    -> selection preview
    -> tag/location clustering
    -> optional local visual split
    -> optional Street Art Cities adapter
    -> persistent run report
    -> local review and previewed metadata edits
```

## Boundaries

- `config.py` owns versioned JSON configuration and atomic persistence.
- `models.py` defines shared photo, cluster, fingerprint, repair-plan, and run
  contracts.
- `photos.py` discovers photos and normalizes metadata.
- `clustering.py` selects and groups normalized records.
- `metadata.py` owns previewed atomic flat-keyword writes.
- `gps.py` creates and validates deterministic missing/manual GPS plans.
- `change_log.py` atomically records each applied metadata operation.
- `matching.py` contains optional local OpenCV comparisons.
- `workflow.py` composes the network-free scan, preview, cluster, and report
  pipeline used by both the CLI and web layer.
- `sac.py` is the only Street Art Cities network boundary. It refreshes one
  normalized city cache, gathers bounded nearby candidates, safely caches
  public reference images, and returns evidence without editing photos.
- `runs.py` launches package subcommands without a shell and persists
  cancellable run manifests, logs, reports, summaries, and safe deletion.
- `diagnostics.py` builds bounded, redacted, locally inspectable support
  packages without copying raw reports or photo metadata.
- `web.py` owns local routes, selection tokens, persisted edit plans, path
  boundaries, artist-assisted review data, local file actions, and templates.

The workflow imports `sac.py` lazily only for an explicitly enabled target.
Matching-disabled runs make no Street Art Cities requests.

Leaflet 1.9.4 is bundled under its BSD-2-Clause license for local GPS display.
Offline reports default to a generated coordinate grid. Optional network
base-map tiles are presentation only and do not enter the matching
pipeline.

## Write boundary

Read operations return normalized immutable photo records. Write operations
accept a persisted plan containing file fingerprints and exact targets. They
preflight the complete plan before changing the first file and append a JSON
change log for every successful write.
