# Copilot instructions

## Commands

Use Python 3.11 or newer. Commands are written for PowerShell.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m unittest discover -s tests
```

Run one test module, class, or method with `unittest` dotted names:

```powershell
python -m unittest tests.test_metadata
python -m unittest tests.test_metadata.MetadataTests
python -m unittest tests.test_metadata.MetadataTests.test_stale_plan_is_rejected_before_writing
```

Install optional OpenCV-based visual matching only when working on that path:

```powershell
pip install -e ".[visual]"
```

Start the local Flask application or generate an offline report:

```powershell
python -m street_art_photo_assistant
python -m street_art_photo_assistant cluster --output _runs\manual
python -m street_art_photo_assistant cluster --visual --output _runs\manual
```

## Architecture

The main data flow is local folders -> normalized immutable `PhotoRecord`s ->
selection preview -> deterministic tag/location clusters -> optional local
visual splitting -> optional Street Art Cities evidence -> persistent run
report -> browser review and metadata edits.

- `config.py` owns the versioned JSON configuration, default merging,
  validation, and atomic saves. Relative configured paths are resolved against
  the configuration file's directory, never the process working directory.
- `photos.py`, `clustering.py`, and `workflow.py` form the offline core.
  `workflow.py` is the composition layer shared by CLI and web execution.
- `sac.py` is the only Street Art Cities network boundary and is imported
  lazily only when matching is enabled. `matching.py` contains optional local
  OpenCV logic. Core scanning, clustering, reporting, and editing must continue
  to work without network access or visual dependencies.
- `runs.py` launches `python -m street_art_photo_assistant cluster` without a
  shell. Each run is a durable directory containing its config snapshot,
  manifest, command/log, structured `progress.json`, preview, and reports.
- `web.py` is the local Flask boundary: routes, preview tokens, persisted edit
  plans, source/cache path confinement, run review, and artist CSV updates.
  Templates and bundled static assets provide the review UI; Leaflet is local,
  while optional base-map tiles are display context only.
- `metadata.py` and `gps.py` are the photo-write boundary. They build exact
  preview plans and apply them only after validating allowed roots, file
  fingerprints, and current metadata. `change_log.py` records completed writes
  atomically, including partial progress if a later write fails.
- `models.py` holds shared typed contracts; `reporting.py` serializes cluster
  output; `diagnostics.py` creates bounded, privacy-redacted support bundles.

## Repository conventions

- Keep provider-specific behavior behind the narrow `sac.py` adapter. Disabled
  matching must make no network request, and provider/reference-image failures
  should remain explicit evidence rather than silently dropping a report.
- Preserve the preview/apply invariant for every metadata mutation: persist
  the exact approved targets, preflight the whole plan before the first write,
  reject stale or out-of-root files, preserve unrelated metadata, use atomic
  replacement, and write a JSON change log. Tag edits update both IPTC keywords
  and Windows `XPKeywords`.
- JSON configuration, plans, progress, manifests, reports, and logs are
  versioned/durable contracts. Write mutable JSON and CSV through a sibling
  temporary file followed by `os.replace`; retain the Windows sharing-violation
  retry behavior where already required.
- `_unknown` is the identity tag for untagged artwork and `_wall` identifies a
  wall grouping. Tags beginning with `_` are internal and are not artist CSV
  entries. Do not hardcode user-specific labels, paths, or exclusion policies.
- Clustering and plan generation are deterministic: normalize tag comparisons
  with `casefold()`, use stable tie-breakers, preserve exact target lists, and
  keep cluster IDs derived from tag plus photo paths.
- Source photo paths, reference-cache paths, run IDs, and plan IDs must remain
  confined to their configured roots. The web application is local-only;
  preserve localhost checks and explicit read-only-mode rejection for writes
  and local OS actions.
- Keep modules aligned to the documented boundaries and prefer a package
  function/subcommand plus focused tests over a standalone script. Use
  `pathlib.Path`, type hints at module boundaries, and explicit errors rather
  than success-shaped empty fallbacks.
- Tests use `unittest`, temporary directories, mocks for provider calls, and
  synthetic fixtures only. Never add personal photo paths, real/private
  datasets, credentials, generated runs, caches, or reference images.
- Update the relevant document under `docs/` and the README when observable
  behavior or a persisted data contract changes.
