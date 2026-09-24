# Street Art Cities integration

Street Art Photo Assistant is an independent community project. It is not
affiliated with or endorsed by Street Art Cities, and it never publishes or
modifies Street Art Cities content.

## Network behavior

Street Art Cities matching is disabled by default. When enabled for a city
slug, one request refreshes the complete public marker endpoint:

```text
https://streetartcities.com/data/cities/<slug>/markers.json
```

The normalized response is written atomically to
`paths.city_cache/<slug>.json`. All artwork statuses are retained. A refresh
failure fails the run explicitly rather than silently using stale data.
Matching-disabled runs do not import the adapter or make provider requests.

## Incremental behavior

Marker metadata is refreshed as one complete city snapshot on every run. The
application does not request only changed markers: it downloads the single
`markers.json` response, normalizes it, and atomically replaces the previous
city cache. This makes additions, updates, and removals visible immediately.

Reference-picture caching is incremental. A non-empty cached image for a marker
is reused without another request, so later runs download only pictures missing
from the local cache. The current cache is keyed by marker ID and does not store
the source image URL or a remote fingerprint. If Street Art Cities replaces the
picture for an existing marker without changing its ID, the cached picture is
therefore retained. Delete that marker's cached image, or clear the configured
`paths.reference_images` cache, to force it to be downloaded again.

Every request identifies itself as:

```text
StreetArtPhotoAssistant/<version> (local desktop application; public SAC adapter)
```

`matching.request_interval_seconds` in `config.local.json` sets the minimum
delay between provider requests. The default `0.5` permits at most two requests
per second; use `1.0` for one request per second or a larger value for a less
aggressive run. Requests remain sequential. The complete city-marker refresh
is still one request; throttling primarily affects uncached reference images.

Reference images are not requested for GPS-only matching. When visual matching
is enabled, the app downloads only the bounded nearby candidates selected by
the configured profile:

| Profile | Maximum candidates per cluster |
|---------|-------------------------------:|
| `quick` | 4 |
| `balanced` | 8 |
| `thorough` | 16 |

Reference URLs must use HTTPS. Responses require an image content type, are
limited to 20 MB, and must decode as an image before atomic caching under
`paths.reference_images`. A failed candidate image is recorded as evidence and
does not abort the complete city report.

**Cache all SAC city pictures** maps to `matching.download_images` and defaults
to `false`. When enabled, every marker with an image URL is processed
sequentially through the same incremental cache, validation, throttle,
progress, and error handling. Nearby cached images then appear in both Street
Art Cities evidence and GPS map marker popups. When disabled, metadata-only
matching downloads no city-wide images; visual matching caches only its bounded
nearby candidates because the comparison requires image bytes. Changing this
option never removes existing cached pictures.

The Generate page shows durable progress for city refresh, cluster candidate
gathering, and every cached/downloaded reference image. It warns when marker or
reference counts reach the configurable
`matching.large_city_warning_markers` or
`matching.large_reference_warning` thresholds. Defaults are 1,000 markers and
100 references; these settings intentionally remain JSON-only.

## Candidate evidence

Clusters without coordinates have no nearby candidates. For located clusters,
the adapter:

1. resolves the local tag through `data/artists.csv`;
2. gathers markers inside `matching.candidate_radius_m`;
3. ranks matching artist slugs before other markers, then by distance;
4. optionally compares the first primary photo with cached references using
   local OpenCV ORB features.

The report uses conservative labels:

- `likely-present`: at least one candidate has sufficient visual evidence;
- `review`: a nearby marker exists but needs human confirmation;
- `likely-new`: no marker is inside the configured radius.

These are review aids, not publication decisions. Removed marker status,
distance, artist agreement, visual score, and image errors remain visible to
the reviewer.

## Known limitations

The comparison produces review suggestions rather than definitive duplicate
detection. An existing Street Art Cities artwork may not be identified for
several reasons:

- **Visual matching:** The lightweight ORB algorithm compares features across
  the complete image; it does not isolate the artwork. Background details can
  dominate the result, while changes in viewpoint, framing, light, obstruction,
  deterioration, or repainting can reduce similarity. Similar surroundings can
  also produce a misleading match.
- **Search radius:** Only markers within `matching.candidate_radius_m` are
  considered. Photo or marker GPS drift can exceed the default radius and has
  been observed at roughly 200 metres. Increasing the radius can recover such
  candidates but may introduce many unrelated markers in dense locations.
- **City boundary:** Only the selected city's marker catalogue is loaded.
  Nearby artwork associated with a neighbouring or unexpected city is not
  considered.
- **Missing or inaccurate coordinates:** A cluster without coordinates has no
  candidates. Incorrect photo coordinates, marker coordinates, or a misleading
  cluster centroid can move the search away from the artwork.
- **Bounded candidates:** The selected profile limits visual comparison to the
  first 4, 8, or 16 ranked nearby candidates. In a dense area, the correct
  marker may fall outside that set.
- **Single local image:** Visual matching uses only the cluster's first primary
  photo. A context shot, poor angle, or obscured view can be less useful than
  another photo in the cluster.
- **Reference-image availability:** A marker may have no usable picture, or its
  picture may fail validation or download. Cached pictures are keyed by marker
  ID, so a picture replaced upstream remains stale until its cache entry is
  removed.
- **Artist mapping:** A missing or incorrect mapping between a local tag and
  `data/artists.csv` can prevent the correct marker from receiving same-artist
  priority.
- **Local clustering:** Photos of one artwork can be split between clusters, or
  unrelated photos can be grouped together, resulting in an unsuitable
  representative image or centroid.
- **Provider data:** The artwork may not yet have a Street Art Cities marker,
  may not appear as an artwork in the selected city response, or may have
  incomplete coordinates or image metadata.

A nearby marker can still appear for manual review when visual comparison
cannot confirm it. `likely-new` means only that no candidate was found within
the selected city and configured radius; it does not prove that the artwork is
absent from Street Art Cities.

## Caches and portability

Both cache roots are configurable and ignored by Git by default. Delete a city
JSON file to remove its suggestion from the city dropdown. Reference images
are reusable across runs and named from sanitized marker identifiers.
