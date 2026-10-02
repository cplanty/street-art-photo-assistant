# Customization

Copy `config.example.json` to `config.local.json`. Relative paths resolve from
the repository directory.

The browser autosaves the complete form by default. Disable **Auto save config**
for a temporary experiment, use **Save configuration now** explicitly, or open
the JSON from the Configuration card and reload the page after editing.

## Sources

Each source has a display name, local path, enabled flag, and optional GPS
target/reference roles. One source may have both GPS roles.

`temporary_folder` controls review copies. `paths.runs` controls persistent
manifests, reports, logs, and edit plans. `read_only` disables all metadata
apply endpoints while keeping preview and reports available.

The cluster detail page's **Copy selected to temp folder** button copies the
currently checked photos into `temporary_folder` (creating it if needed,
overwriting same-named files, and leaving any other existing files alone).
**Open temp folder** opens that folder locally. Both actions are restricted to
photos inside the configured sources, like every other local file action.

## Tag policy

- `generic_tags` are categories and do not identify an artwork.
- `context_only_tags` keep wider/location photos available without making them
  primary visual references.
- `unknown_tag` defaults to `_unknown`.
- `wall_tag` defaults to `_Wall_`. The former exact default `_wall` is accepted
  when reading existing photos and configurations, but new clusters and
  proposals use `_Wall_`.
- `selection.exclude_tags` contains the user's own exclusion policy. The
  application has no hidden label-specific exclusions.

## Thresholds

- `clustering.radius_m` controls geographic grouping.
- `gps_repair.maximum_time_difference_seconds` limits reference transfer.
- `matching.candidate_radius_m` limits nearby Street Art Cities candidates.
- `matching.api_client_id` is the bundled, non-secret identifier for the
  optional local PKCE API test. Forks can override it for another registered
  app. OAuth tokens and verifiers are never persisted.
- `matching.marker_source` selects the established `public-city-endpoint` or
  the authenticated, paginated `oauth-markers-api`. The public source remains
  the default because its city snapshot contains richer artist/image fields.
- `matching.incremental_marker_refresh` (default `true`) applies only to
  `oauth-markers-api`. It requests only markers changed since the previous
  sync and merges them into the existing city cache. Set it to `false` to force
  a complete re-download on every run.
- `matching.profile` limits candidates per cluster to 4 (`quick`), 8
  (`balanced`), or 16 (`thorough`).
- `matching.request_interval_seconds` is the minimum delay between SAC
  requests. Increase it to reduce request throughput.
- `matching.download_images` is exposed as **Cache all SAC city pictures**.
  It defaults to `false`, which caches only bounded candidate pictures required
  by visual matching. Set it to `true` to incrementally cache all available
  city marker pictures for evidence and map thumbnails.
- `matching.compare_all_marker_images` is exposed as **Compare every SAC
  marker picture, not just the first**. It defaults to `true`: visual matching
  downloads and compares every picture of each bounded candidate marker and
  keeps the best-scoring one. Set it to `false` to only compare each
  candidate's first picture and reduce downloads.
- `matching.large_city_warning_markers` and
  `matching.large_reference_warning` control progress warnings for large work.
- `paths.city_cache` and `paths.reference_images` select local provider caches.
- Visual matching uses a fixed local ORB threshold; the profile changes only
  candidate effort, not GPS or clustering thresholds.

`paths.artists` is the committed public tag-to-provider mapping.
`paths.local_artists` is its gitignored per-user overlay. Reads combine both
files, with the public row winning when the same tag occurs in both. After a
tag plan adds a non-internal tag that is not already present in either file,
the reviewer offers a helper for confirming its Street Art Cities slug,
display name, and Instagram handle. Both provider fields are prefilled from
the nearby candidate whose artist string matches the tag. The destination
selector defaults to the committed `artists.csv`; choose
`artists.local.csv` for a user-only addition. Either destination is created
with the standard header when missing, and writes are atomic. The default
local path is excluded by `.gitignore`; `_`-prefixed workflow tags are never
offered for insertion.

## Provider boundary

Another comparison provider should consume normalized `PhotoCluster` records
and return evidence records. It must not change selection, clustering, or photo
metadata.
