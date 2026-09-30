# Data formats

## Artist mapping

`data/artists.csv` is UTF-8 and semicolon-separated:

```text
tag;streetartcities_slug;streetartcities_name;instagram;status
```

The local tag controls photo metadata. Provider slug, provider name, and
Instagram values are optional for user-added rows.

`streetartcities_slug` and `streetartcities_name` are deliberately separate and
are never interchangeable:

- `streetartcities_slug` is **identity only**. It is the join key against
  Street Art Cities data and the sole input to the
  `https://streetartcities.com/artists/<slug>` deep link. It is never rendered.
- `streetartcities_name` is **display only**. It holds the provider display
  name shown in candidate evidence, and it can be compared case-insensitively
  with a marker's artist string when a response carries no slug. It is never
  used to build a link or to establish identity.

A row may carry a slug without a name; the review UI then falls back to the
marker's own artist string, and then to the local tag. A name without a slug is
rejected, because a display name alone establishes no provider identity.

Rows written before this column existed remain valid: the missing value is read
as empty, and the header is rewritten with the column the next time a row is
appended.

The artist catalogue refresh fills `streetartcities_name` only where a slug is
present and the name is blank. It never overwrites a curated name, never
invents a slug for a tag that has none, and reports unresolved slugs and
possible tag/slug matches for review instead of applying them.

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
time, source (`public-city-endpoint` or `oauth-markers-api`), and normalized
artwork markers. Marker status is preserved, including removed markers, so the
report can explain rather than silently discard nearby historical entries.
Each marker carries `artist_slug` and, when the source provides it,
`artist_name`. Both sources supply these, but the public snapshot nests
coordinates under `location` while the API returns flat `lat`/`lng`/`address`
fields; normalization accepts either shape.

## Street Art Cities artist cache

`data/cities/<slug>.artists.json` contains the cache format version, city slug,
refresh time, source (`oauth-artists-api`), and the normalized artist
catalogue. Each artist records `slug`, `name`, `alternative_names`, `country`,
`artworks_count`, `url`, and `updated_at`. The file sits beside the marker
caches but is not one; the city selector only lists `<slug>.json`.

## GPS repair plan

A repair plan records its ID/time and exact target/reference pairs. Every pair
contains both file fingerprints, proposed coordinates, and capture-time
difference. Manual plans may contain one shared destination or an independent
destination for every moved image.

## Run manifest and change log

Run manifests contain command, state, stage, label, selected count, cluster
count, and output paths. Change logs contain operation, plan ID, status, time,
file, before value, and after value. `status: applying` means earlier listed
writes completed before a later interruption; `status: complete` means the
entire plan finished.

Each run also owns `progress.json`: stage, percentage, detail message, optional
current/total item counts, accumulated warnings, and update time. The web page
polls this file rather than inferring progress from console text.

## Diagnostic bundle

Diagnostic ZIPs contain environment, configuration summary, run summaries,
bounded route logs, and a bundle manifest. Detailed bundles may add sanitized
run logs. See [Diagnostics and issue reports](diagnostics.md) for the strict
exclusion and redaction policy.
