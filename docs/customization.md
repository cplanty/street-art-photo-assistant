# Customization

Copy `config.example.json` to `config.local.json`. Relative paths resolve from
the repository directory.

## Sources

Each source has a display name, local path, enabled flag, and optional GPS
target/reference roles. One source may have both GPS roles.

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

