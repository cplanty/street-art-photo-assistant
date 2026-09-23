# Diagnostics and issue reports

The application records a local JSON-lines request log under
`paths.runs/_logs/app.jsonl`. Entries contain time, HTTP method, route pattern,
status, duration, and explicit application errors. Query strings and request
bodies are never logged. Logs rotate at 2 MB and retain three older files.

## Generate a package

Use **Configuration → Diagnostics → Generate diagnostic package**. Packages are
created under `paths.runs/_diagnostics/`; nothing is uploaded automatically.
Open the folder and inspect the ZIP before attaching it to an issue.

The safe package contains:

- application, Python, operating-system, and dependency versions;
- configuration shape and counts without source names, paths, tag values, or
  configured city;
- up to ten run summaries without commands, labels, output paths, or reports;
- a bounded, path- and email-redacted application log;
- a manifest listing included and excluded data.

**Include sanitized recent run logs** adds bounded logs from up to three recent
runs. Absolute Windows paths and email addresses are replaced. This detailed
option remains opt-in because arbitrary dependency errors can contain
unexpected user data.

Packages always exclude photos, thumbnails, raw configuration, cluster
reports, GPS coordinates, artist mappings, reference caches, metadata plans,
and change logs.
