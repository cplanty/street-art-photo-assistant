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
- The visual profile controls local candidate effort without changing GPS or
  clustering thresholds.

## Provider boundary

Another comparison provider should consume normalized `PhotoCluster` records
and return evidence records. It must not change selection, clustering, or photo
metadata.
