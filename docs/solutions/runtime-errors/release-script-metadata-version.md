---
title: Release script must support metadata-derived package versions
date: 2026-07-20
category: docs/solutions/runtime-errors/
module: release tooling
problem_type: runtime_error
component: tooling
symptoms:
  - "The release script updates pyproject.toml and then exits with `Error: Could not find __version__ in src/pltr/__init__.py`."
  - "A failed release attempt leaves a partial version edit in the working tree before any commit or tag is created."
root_cause: logic_error
resolution_type: code_fix
severity: medium
related_components:
  - development-workflow
tags:
  - release-script
  - package-versioning
  - importlib-metadata
  - semantic-versioning
---

# Release script must support metadata-derived package versions

## Problem

The v0.18.0 release attempt failed in the repository release script after it changed `pyproject.toml`. The script assumed that `src/pltr/__init__.py` contained a literal version assignment, but the package derives its version from installed package metadata.

## Symptoms

- `scripts/release.py --version 0.18.0 --yes --no-push` reported that it could not find a supported `__version__` definition.
- No release commit or tag was created by the failed attempt, but `pyproject.toml` was left partially modified and had to be restored before retrying.

## What Didn't Work

- The original `update_version_in_init_py()` implementation searched only for a pattern like `__version__ = "0.17.1"`. It treated the absence of that literal as fatal, even though the package's metadata-derived definition was intentional.
- Retrying without restoring the partial edit would have violated the release script's clean-working-tree precondition.

## Solution

Make the release helper recognize both supported version models:

```python
if re.search(pattern, content):
    updated_content = re.sub(pattern, replacement, content)
    init_py_path.write_text(updated_content)
    return

metadata_pattern = r'__version__ = version\("pltr-cli"\)'
if re.search(metadata_pattern, content):
    # pyproject.toml is the version source; do not duplicate it in __init__.py.
    return
```

The failed `pyproject.toml` edit was restored, the helper was fixed and formatted, and the release was rerun from fork `main` at version `0.17.1`. The release script then updated `pyproject.toml` and `uv.lock`, created the `v0.18.0` commit/tag, and the verified wheel was attached to the GitHub release. The local `pltr` tool was installed from that release wheel and reported `pltr 0.18.0`.

## Why This Works

`pyproject.toml` is the authoritative package-version source when `__version__` calls `importlib.metadata.version("pltr-cli")`. Rewriting `__init__.py` would duplicate version state and can be wrong when the source checkout is not installed. The release helper now updates only the authoritative metadata and treats the metadata-derived definition as valid, while retaining support for projects that use a literal assignment.

## Prevention

- Keep the release helper aligned with the package's actual version-source strategy.
- Add a release-script test for both literal and metadata-derived `__version__` definitions.
- Run the release script in dry-run mode first, then verify Ruff, tests, package build, tag target, and installed CLI version before publishing.
- On a failed release attempt, inspect and restore partial version edits before retrying; do not commit or tag a partially applied release.

## Related Issues

- The fork's PyPI publishing workflow was disabled, so the v0.18.0 GitHub release was created with locally verified wheel and source artifacts instead of claiming a PyPI publication.
