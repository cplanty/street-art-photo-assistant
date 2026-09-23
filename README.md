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
- Preview and atomically apply flat tag edits with stale-plan rejection.
- Repair missing GPS from same-camera or trusted cross-camera references.
- Preview explicit manual GPS positioning and log every metadata change.
- Generate cancellable persistent runs and review clusters in the browser.
- Inspect exact tag/GPS plans before applying them from cluster detail pages.
- Keep all configuration, reports, and cached data on the local computer.
- Use explicit typed data contracts for photos, clusters, repair plans, and
  runs.
- Start one local web application with no account or cloud service.

Optional Street Art Cities matching is implemented in a subsequent focused
commit. Every other core workflow remains fully offline.

## Install

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
Copy-Item config.example.json config.local.json
python -m street_art_photo_assistant
```

Open <http://127.0.0.1:8765/>.

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

The core workflow is local and has no telemetry. Network access is used only
when Street Art Cities matching is enabled. Photo metadata writes will require
an exact preview and confirmation, preserve unrelated metadata, and create a
JSON change log.

Do not commit `config.local.json`, photos, run output, reference-image caches,
or other local data.

## Documentation

- [Requirements](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [Customization](docs/customization.md)
- [Data formats](docs/data-formats.md)
- [Workflows](docs/workflows.md)
- [Development](docs/development.md)

## License

[MIT](LICENSE)
