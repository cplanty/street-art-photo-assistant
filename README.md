# Street Art Photo Assistant

Cluster, geotag, tag, and compare street-art photos from a local browser
interface.

Street Art Photo Assistant is an independent community project. It is not
affiliated with or endorsed by Street Art Cities.

## Current capabilities

- Configure reusable local photo folders.
- Keep all configuration, reports, and cached data on the local computer.
- Use explicit typed data contracts for photos, clusters, repair plans, and
  runs.
- Start one local web application with no account or cloud service.

The selection, clustering, metadata editing, GPS repair, and optional Street
Art Cities matching workflows are implemented in subsequent focused commits.

## Install

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
Copy-Item config.example.json config.local.json
python -m street_art_photo_assistant
```

Open <http://127.0.0.1:8765/>.

Install local visual matching support when needed:

```powershell
pip install -e ".[visual]"
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
- [Development](docs/development.md)

## License

[MIT](LICENSE)

