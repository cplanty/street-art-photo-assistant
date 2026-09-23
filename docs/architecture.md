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
- `metadata.py` will own previewed tag/GPS writes and change logs.
- `gps.py` will create and validate deterministic repair plans.
- `matching.py` will contain optional local OpenCV comparisons.
- `sac.py` will be the only Street Art Cities network boundary.
- `runs.py` will persist manifests, progress, reports, and safe deletion.
- `web.py` owns local routes and renders templates.

The core modules do not import `sac.py`. The web/run layer invokes the adapter
only for an explicitly enabled target.

## Write boundary

Read operations return normalized immutable photo records. Write operations
accept a persisted plan containing file fingerprints and exact targets. They
preflight the complete plan before changing the first file and append a JSON
change log for every successful write.

