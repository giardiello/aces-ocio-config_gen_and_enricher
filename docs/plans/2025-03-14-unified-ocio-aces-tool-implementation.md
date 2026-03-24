# Unified OCIO/ACES Tool — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** One CLI with subcommands and a shared library for OCIO/ACES logic; remove duplicated transform-ID and display/view code; keep existing scripts as thin wrappers.

**Architecture:** New package `ocio_aces_tools` with `ocio_utils`, `display_view`, `constants`; single CLI entry (`ocio_aces_tool` or `python -m ocio_aces_tools`) with subcommands; existing scripts invoke CLI for backward compatibility.

**Tech Stack:** Python 3.7+, PyOpenColorIO, argparse. See design: `docs/plans/2025-03-14-unified-ocio-aces-tool-design.md`.

---

## Task 1: Package skeleton and constants

**Files:**
- Create: `ocio_aces_tools/__init__.py`
- Create: `ocio_aces_tools/constants.py`
- Test: `tests/test_constants.py` (optional: smoke test that module imports and OUTPUT_TRANSFORM_TYPES is non-empty)

**Step 1: Create package and constants**

Create `ocio_aces_tools/__init__.py`:

```python
"""OCIO/ACES shared library and CLI."""
__version__ = "0.1.0"
```

Create `ocio_aces_tools/constants.py`:

```python
"""Shared constants for OCIO/ACES tools."""

OUTPUT_TRANSFORM_TYPES = [
    'ODT', 'InvODT',
    'RRTODT', 'InvRRTODT',
    'Output', 'InvOutput'
]
```

**Step 2: Commit**

```bash
git add ocio_aces_tools/__init__.py ocio_aces_tools/constants.py
git commit -m "chore: add ocio_aces_tools package and constants"
```

---

## Task 2: ocio_utils — get_transform_ids and config load

**Files:**
- Create: `ocio_aces_tools/ocio_utils.py`
- Create: `tests/test_ocio_utils.py`
- Reference: `ACES_json_to_OCIOmapping.py` lines 52–89 (`extract_transform_ids_from_item`)

**Step 1: Write failing test**

In `tests/test_ocio_utils.py`:

```python
import pytest

def test_get_transform_ids_returns_list():
    from ocio_aces_tools.ocio_utils import get_transform_ids
    # Minimal mock: object with getDescription returning "ACEStransformID: urn:ampas:aces:transformId:v1.0:ODT.Academy.Rec709_100nits_dim.a1.0.3"
    class MockItem:
        def getDescription(self):
            return "ACEStransformID: urn:ampas:aces:transformId:v1.0:ODT.test"
        def getInterchangeAttributes(self):
            return None
    result = get_transform_ids(MockItem())
    assert result == ["urn:ampas:aces:transformId:v1.0:ODT.test"]
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/fgiardiello/Dev_prj/OCIO_ACES_MERGER_AND_PARSER && python -m pytest tests/test_ocio_utils.py -v`  
Expected: FAIL (e.g. module or function not found).

**Step 3: Implement ocio_utils**

Create `ocio_aces_tools/ocio_utils.py`:

```python
"""Shared OCIO config and transform ID utilities."""
import re

def get_transform_ids(ocio_item):
    """
    Extract all transform IDs from an OCIO item (ColorSpace, Look, ViewTransform).
    Supports both OCIO v2.5+ interchange and v2.4 description formats.
    """
    found_ids = []
    try:
        if hasattr(ocio_item, 'getInterchangeAttributes'):
            attrs = ocio_item.getInterchangeAttributes()
            if attrs and attrs.get('amf_transform_ids'):
                amf_ids = attrs['amf_transform_ids']
                found_ids.extend([tid.strip() for tid in amf_ids.split('\n') if tid.strip()])
    except (AttributeError, Exception):
        pass
    try:
        desc = ocio_item.getDescription()
        if desc:
            found_ids.extend(re.findall(r'ACEStransformID:\s*(\S+)', desc))
    except (AttributeError, Exception):
        pass
    seen = set()
    return [tid for tid in found_ids if tid not in seen and not seen.add(tid)]
```

**Step 4: Run test**

Run: `python -m pytest tests/test_ocio_utils.py -v`  
Expected: PASS.

**Step 5: Commit**

```bash
git add ocio_aces_tools/ocio_utils.py tests/test_ocio_utils.py
git commit -m "feat(ocio_aces_tools): add get_transform_ids"
```

---

## Task 3: display_view — parse and output-URN helper

**Files:**
- Create: `ocio_aces_tools/display_view.py`
- Create: `tests/test_display_view.py`
- Reference: `ACES_json_to_OCIOmapping.py` `parse_ocio_display_view_structure`, `is_output_transform_urn`, `get_transform_type_from_urn`

**Step 1: Copy output-URN logic and parse structure**

In `ocio_aces_tools/display_view.py`:
- Import `get_transform_ids` from `ocio_utils` and `OUTPUT_TRANSFORM_TYPES` from `constants`.
- Implement `is_output_transform_urn(urn)` and `parse_display_view_structure(config)` (return structure: display -> view -> view transform URNs, display colorspace URNs). Logic from `ACES_json_to_OCIOmapping.py` lines 34–50 and 92–186.

**Step 2: Write a minimal test**

Use a small v2.4 or v2.5 fixture config (or create one in `tests/fixtures/`) and assert `parse_display_view_structure(config)` returns a dict with at least one display and expected keys.

**Step 3: Run test, fix until pass, commit**

```bash
git add ocio_aces_tools/display_view.py tests/test_display_view.py tests/fixtures/
git commit -m "feat(ocio_aces_tools): add display_view parse and output URN helpers"
```

---

## Task 4: Refactor ACES_json_to_OCIOmapping to use library

**Files:**
- Modify: `ACES_json_to_OCIOmapping.py`

**Steps:**
- Replace local `extract_transform_ids_from_item` with `from ocio_aces_tools.ocio_utils import get_transform_ids` and use `get_transform_ids(item)` everywhere.
- Replace local `is_output_transform_urn` / `get_transform_type_from_urn` and `OUTPUT_TRANSFORM_TYPES` with imports from `ocio_aces_tools.constants` and `ocio_aces_tools.display_view`.
- Replace local `parse_ocio_display_view_structure` with `from ocio_aces_tools.display_view import parse_display_view_structure` and adapt call sites (same return shape).
- Run existing mapping script once: `python ACES_json_to_OCIOmapping.py transforms.json <path_to_ocio> -o /tmp/out` and confirm outputs unchanged.
- Commit: `refactor: ACES_json_to_OCIOmapping use ocio_aces_tools`

---

## Task 5: Refactor validate_amf_output_transforms to use library

**Files:**
- Modify: `validate_amf_output_transforms.py`

**Steps:**
- Replace `extract_transform_ids` with `ocio_aces_tools.ocio_utils.get_transform_ids`.
- Replace display/view parsing and output-URN logic with `ocio_aces_tools.display_view` (and constants). Keep `validate_display_view_mappings` behavior by calling the shared parser and implementing validation in this script or moving one canonical `validate_display_view_mappings` into `display_view.py` and calling it from both mapping and validate_amf.
- Run: `python validate_amf_output_transforms.py <path_to_ocio> [transforms.json] -o /tmp/out` and confirm behavior unchanged.
- Commit: `refactor: validate_amf use ocio_aces_tools`

---

## Task 6: CLI entry and subcommands (upgrade, map, validate-amf, split)

**Files:**
- Create: `ocio_aces_tools/cli.py` (or `ocio_aces_tools/__main__.py`)
- Modify: `pyproject.toml` or `setup.py` if present to add entry point `ocio_aces_tool = ocio_aces_tools.cli:main`; otherwise document running as `python -m ocio_aces_tools`

**Steps:**
- Implement `main()` that parses subcommand: `upgrade`, `map`, `validate-amf`, `split`.
- Each subcommand parses its own args and calls the existing logic (from `upgrade_ocio_v24_to_v25`, `ACES_json_to_OCIOmapping.process_files`, `validate_amf_output_transforms.validate_display_view_mappings`, `split_config_by_aces_version`). Use import of existing modules and call their main functions with parsed args (or refactor those scripts to export a run(args) function).
- Ensure `python -m ocio_aces_tools upgrade --help` (and map, validate-amf, split) show correct usage.
- Commit: `feat: add unified CLI (upgrade, map, validate-amf, split)`

---

## Task 7: CLI subcommands enrich, lut-build, lut-verify, repo

**Files:**
- Modify: `ocio_aces_tools/cli.py`

**Steps:**
- Add subcommands: `enrich` (invoke enricher script or its main), `lut-build` (generate_lut_based_config), `lut-verify` (verify_lut_vs_builtin), `repo` with sub-subcommands `extract` and `compare` (extract_colorspaces, compare_configs). Pass-through argv or replicate argparse for each.
- Verify `python -m ocio_aces_tools enrich --help`, `lut-build --help`, `lut-verify --help`, `repo extract --help`, `repo compare --help`.
- Commit: `feat: CLI subcommands enrich, lut-build, lut-verify, repo`

---

## Task 8: Thin wrapper scripts

**Files:**
- Modify: `upgrade_ocio_v24_to_v25.py`, `ACES_json_to_OCIOmapping.py`, `validate_amf_output_transforms.py`, `split_config_by_aces_version.py` (and optionally `ocio_aces_enricher/scripts/enrich_ocio_config.py`, etc.)

**Steps:**
- At bottom of each script, keep argparse but after parsing call `ocio_aces_tools.cli.run_subcommand('upgrade', sys.argv[1:])` (or equivalent) so that running `python upgrade_ocio_v24_to_v25.py ...` behaves like `python -m ocio_aces_tools upgrade ...`. Ensure backward compatibility: same args, same exit codes.
- Commit: `chore: wrap legacy scripts to call unified CLI`

---

## Task 9: Tests and docs

**Files:**
- Add/update: `tests/test_ocio_utils.py`, `tests/test_display_view.py` (expand if needed)
- Modify: `CLAUDE.md` or root `README.md`

**Steps:**
- Add one smoke test per subcommand if feasible (e.g. `--help` exits 0).
- Update CLAUDE.md/README: describe unified CLI and list subcommands; point to `python -m ocio_aces_tools` and mention legacy script names as wrappers.
- Commit: `docs: document unified CLI and add smoke tests`

---

## Execution handoff

Plan complete and saved to `docs/plans/2025-03-14-unified-ocio-aces-tool-implementation.md`.

**Two execution options:**

1. **Subagent-driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Parallel session (separate)** — Open a new session with executing-plans and run through the plan with checkpoints.

Which approach do you prefer?
