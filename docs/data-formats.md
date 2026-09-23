# Data formats

## Artist mapping

`data/artists.csv` is UTF-8 and semicolon-separated:

```text
tag;streetartcities_slug;instagram;status
```

The local tag controls photo metadata. Provider slug and Instagram values are
optional for user-added rows.

## Normalized photo

```json
{
  "path": "C:\\Photos\\photo.jpg",
  "source": "Camera",
  "captured_at": "2026-01-02T12:34:56",
  "latitude": 48.0,
  "longitude": 2.0,
  "tags": ["Artist"],
  "width": 4000,
  "height": 3000
}
```

## Cluster report

A cluster records a stable ID, normalized tag, primary photos, context photos,
centroid, and optional local visual subgroup.

## GPS repair plan

A repair plan records its ID/time and exact target/reference pairs. Every pair
contains both file fingerprints, proposed coordinates, and capture-time
difference.

## Run manifest and change log

Run manifests contain request, state, selected count, cluster count, and output
paths. Change logs contain operation, time, file, before value, and after value.

