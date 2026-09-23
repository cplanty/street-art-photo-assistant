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

## Caches and portability

Both cache roots are configurable and ignored by Git by default. Delete a city
JSON file to remove its suggestion from the city dropdown. Reference images
are reusable across runs and named from sanitized marker identifiers.
