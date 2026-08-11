# Phase 0–1 Verification

## Required

```bash
python -m pytest -q
python -m compileall -q app tests
```

## Optional quality tools

```bash
ruff check .
mypy app
```

The ZIP generation process also verifies that every `.sh` file contains LF only.
