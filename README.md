# Street Art Photo Assistant

Cluster, geotag, tag, and compare street-art photos from a local browser
interface.

Street Art Photo Assistant is an independent community project. It is not
affiliated with or endorsed by Street Art Cities.

## Current capabilities

- Configure reusable local photo folders.
- Read JPEG capture time, GPS, and flat IPTC/Windows keywords.
- Preview date/time, tag, tagged-state, and missing-GPS filters.
- Group photos by tag and location, retaining wide/multi-tag context photos.
- Optionally split ambiguous local clusters with OpenCV.
- Write offline JSON and Markdown cluster reports.
- Directly apply flat tag edits through atomic plans with stale-file rejection.
- Repair missing GPS from same-camera or trusted cross-camera references.
- Preview explicit manual GPS positioning and log every metadata change.
- Generate cancellable persistent runs and review clusters in the browser.
- Follow durable stage, percentage, item-count, warning, and log progress while
  a report is generated.
- Start each report on a cluster dashboard, then review it in a resizable
  two-pane photo/tag/GPS workspace.
- Sort the dashboard by index, tag, capture time, photo count, or SAC status;
  cluster navigation follows that order.
- Apply artist-assisted tags directly to one, selected, or all cluster images.
- Reposition selected images together or drag individual photo markers to
  independent coordinates before previewing the write.
- Optionally refresh a complete Street Art Cities city marker set and compare
  nearby candidates by artist, GPS, and local OpenCV evidence.
- Test the Street Art Cities OAuth API locally with authorization-code PKCE and
  in-memory `collections:read` and `markers:read` scopes.
- Select either the established public city snapshot or the authenticated,
  paginated Markers API while the newer API path is evaluated.
- Optionally cache all available SAC marker pictures for evidence and map
  thumbnails; this is disabled by default.
- Inspect exact tag/GPS plans before applying them from cluster detail pages.
- Keep all configuration, reports, and cached data on the local computer.
- Generate inspectable, privacy-redacted diagnostic ZIPs for issue reports.
- Use explicit typed data contracts for photos, clusters, repair plans, and
  runs.
- Start one local web application with no account or cloud service.

Street Art Cities matching is optional. Every other core workflow remains
fully offline.

## Install

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
Copy-Item config.example.json config.local.json
python -m street_art_photo_assistant
```

Open <http://127.0.0.1:8787/>.

Create an offline cluster report directly from the configured sources:

```powershell
python -m street_art_photo_assistant cluster --output _runs\manual
```

Install local visual matching support when needed:

```powershell
pip install -e ".[visual]"
python -m street_art_photo_assistant cluster --visual --output _runs\manual
```

## Privacy and safety

The core workflow is local and has no telemetry. Provider access is used only
when Street Art Cities matching is enabled. An offline report's GPS map can
optionally request third-party display tiles when the user selects a network
base map; tiles are never matching evidence. Tag edits apply immediately
through exact atomic plans; GPS writes require preview and confirmation. Both
preserve unrelated metadata and create a JSON change log.

Do not commit `config.local.json`, photos, run output, reference-image caches,
or other local data.

## Documentation

- [Requirements](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [Customization](docs/customization.md)
- [Data formats](docs/data-formats.md)
- [Workflows](docs/workflows.md)
- [Street Art Cities integration](docs/sac-integration.md)
- [Diagnostics and issue reports](docs/diagnostics.md)
- [Development](docs/development.md)

## License

[MIT](LICENSE)
