# Agent guidance

## Goal

Maintain a small, local-first application for clustering, geotagging, tagging,
and optionally comparing street-art photos with Street Art Cities.

## Commands

```powershell
pip install -e .
python -m unittest discover -s tests
python -m street_art_photo_assistant
```

Optional visual support:

```powershell
pip install -e ".[visual]"
```

## Repository rules

- Keep core workflows usable without network access.
- Put provider-specific behavior behind a narrow adapter.
- Never add personal photo paths, private datasets, credentials, or generated
  caches.
- Synthetic fixtures only.
- `_unknown` identifies an untagged artwork; `_wall` identifies a wall grouping.
- Do not hardcode user-specific labels or exclusion policies.
- Preview every metadata write, replay the exact approved target list, preserve
  unrelated metadata, and write a JSON change log.
- Prefer a focused module and test over a new standalone script.
- Update the relevant documentation with behavior changes.

