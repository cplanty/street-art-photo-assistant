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

## Tag policy

- `generic_tags` are categories and do not identify an artwork.
- `context_only_tags` keep wider/location photos available without making them
  primary visual references.
- `unknown_tag` defaults to `_unknown`.
- `wall_tag` defaults to `_wall`.
- `selection.exclude_tags` contains the user's own exclusion policy. The
  application has no hidden label-specific exclusions.

## Thresholds

- `clustering.radius_m` controls geographic grouping.
- `gps_repair.maximum_time_difference_seconds` limits reference transfer.
- `matching.candidate_radius_m` limits nearby Street Art Cities candidates.
- `matching.profile` limits candidates per cluster to 4 (`quick`), 8
  (`balanced`), or 16 (`thorough`).
- `matching.request_interval_seconds` is the minimum delay between SAC
  requests. Increase it to reduce request throughput.
- `matching.download_images` is exposed as **Cache all SAC city pictures**.
  It defaults to `false`, which caches only bounded candidate pictures required
  by visual matching. Set it to `true` to incrementally cache all available
  city marker pictures for evidence and map thumbnails.
- `matching.large_city_warning_markers` and
  `matching.large_reference_warning` control progress warnings for large work.
- `paths.city_cache` and `paths.reference_images` select local provider caches.
- Visual matching uses a fixed local ORB threshold; the profile changes only
  candidate effort, not GPS or clustering thresholds.

## Provider boundary

Another comparison provider should consume normalized `PhotoCluster` records
and return evidence records. It must not change selection, clustering, or photo
metadata.
