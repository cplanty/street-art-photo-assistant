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
- `photos.py` will discover photos and normalize metadata.
- `clustering.py` will select and group normalized records.
- `metadata.py` owns previewed atomic flat-keyword writes.
- `gps.py` creates and validates deterministic missing/manual GPS plans.
- `change_log.py` atomically records each applied metadata operation.
- `matching.py` will contain optional local OpenCV comparisons.
- `workflow.py` composes the network-free scan, preview, cluster, and report
  pipeline used by both the CLI and web layer.
- `sac.py` will be the only Street Art Cities network boundary.
- `runs.py` launches package subcommands without a shell and persists
  cancellable run manifests, logs, reports, summaries, and safe deletion.
- `web.py` owns local routes, selection tokens, persisted edit plans, path
  boundaries, and templates.

The core modules do not import `sac.py`. The web/run layer invokes the adapter
only for an explicitly enabled target.

## Write boundary

Read operations return normalized immutable photo records. Write operations
accept a persisted plan containing file fingerprints and exact targets. They
preflight the complete plan before changing the first file and append a JSON
change log for every successful write.
