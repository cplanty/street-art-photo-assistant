# Development

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m unittest discover -s tests
```

For visual work:

```powershell
pip install -e ".[visual]"
```

## Conventions

- Keep modules focused on one documented boundary.
- Add no standalone script when a package command or function is sufficient.
- Use type hints at module boundaries.
- Fail explicitly; do not convert errors into empty successful results.
- Use `pathlib.Path` and avoid process-working-directory assumptions.
- Test observable requirements with temporary folders and synthetic images.
- Never add real photo paths, photos, credentials, caches, or private data.

## Commit structure

Prefer small to medium commits that each leave tests passing and documentation
accurate. Separate foundation, local core, metadata writes, UI/runs, and
optional provider integration.

