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
centroid, and optional local visual subgroup. When Street Art Cities matching
is enabled, `street_art_cities` records the city, classification,
recommendation, resolved artist slug, and nearby candidates. Candidate evidence
includes marker metadata, distance, artist agreement, optional cached-image
path and similarity, and any explicit reference-image error.

## Street Art Cities city cache

`data/cities/<slug>.json` contains the cache format version, city slug, refresh
time, and normalized artwork markers. Marker status is preserved, including
removed markers, so the report can explain rather than silently discard nearby
historical entries.

## GPS repair plan

A repair plan records its ID/time and exact target/reference pairs. Every pair
contains both file fingerprints, proposed coordinates, and capture-time
difference.

## Run manifest and change log

Run manifests contain command, state, stage, label, selected count, cluster
count, and output paths. Change logs contain operation, plan ID, status, time,
file, before value, and after value. `status: applying` means earlier listed
writes completed before a later interruption; `status: complete` means the
entire plan finished.
