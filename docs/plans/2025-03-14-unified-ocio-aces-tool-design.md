# Unified OCIO/ACES Tool — Design

**Date:** 2025-03-14  
**Status:** Approved  
**Approach:** Option A — Shared library + single CLI

## Goal

Turn the repo’s multiple scripts into one coherent tool: a single CLI with subcommands and a shared library for OCIO/ACES logic (transform ID extraction, display/view parsing). Remove duplicated code and keep existing behavior and backward compatibility via thin script wrappers.

## Scope

- **In scope:** Consolidate Python entry points; extract shared OCIO/AMF logic into a library; add a single CLI with subcommands; preserve current behavior.
- **Out of scope:** No changes to OCIOM/merge workflow, transforms.json schema, or LUT/repo behavior beyond wiring them into the CLI.

## Architecture

### Layout

```
OCIO_ACES_MERGER_AND_PARSER/
├── ocio_aces_tools/           # New package
│   ├── __init__.py
│   ├── ocio_utils.py          # Config load, version, transform ID extraction (v2.4 + v2.5)
│   ├── display_view.py        # Parse Display+View structure; URN → (display, view); validation
│   ├── constants.py           # OUTPUT_TRANSFORM_TYPES, etc.
│   └── cli.py                 # argparse subcommands (or __main__.py)
├── docs/plans/
├── (existing scripts become thin wrappers or remain as alternate entry points)
├── ocio_aces_enricher/
└── ...
```

### Shared library

- **ocio_utils:** Load OCIO config from path; detect major/minor version; `get_transform_ids(ocio_item)` for any item (ColorSpace, Look, ViewTransform) supporting both v2.4 description and v2.5+ `interchange.amf_transform_ids`.
- **display_view:** Parse config → structure of displays, views, view transforms, display colorspaces and their URNs; optional validation: each output transform URN maps to exactly one (display, view).
- **constants:** Centralize `OUTPUT_TRANSFORM_TYPES` and any “is output URN?” helper used by mapping and validate_amf.

### CLI (single entry point)

- **Entry:** `ocio_aces_tool` (or `python -m ocio_aces_tools`) with subcommands.
- **Subcommands:** `enrich` | `map` | `upgrade` | `validate-amf` | `split` | `lut-build` | `lut-verify` | `repo extract` | `repo compare`.
- **Behavior:** Each subcommand delegates to existing logic (refactored to call the shared library where applicable). No change to transform JSON schema or OCIOM.

### Backward compatibility

- Keep existing script filenames (e.g. `upgrade_ocio_v24_to_v25.py`, `ACES_json_to_OCIOmapping.py`) as thin wrappers that invoke the CLI with the appropriate subcommand and pass-through args, so existing docs and callers keep working.

## Data flow

- Any subcommand that reads OCIO configs uses `ocio_utils` to load config and, where needed, `ocio_utils.get_transform_ids(item)`.
- Mapping, validate_amf, and any display/view logic use `display_view.parse(config)` and, for validation, `display_view.validate(...)`.
- Mapping, upgrade, validate_amf, split, enricher, LUT, and repo operations remain conceptually unchanged; they call shared helpers instead of reimplementing them.

## Error handling

- Library: raise clear exceptions; no sys.exit in library code.
- CLI: catch, print user-friendly message, exit with non-zero code.
- Existing behavior of each script (e.g. validation failure = non-zero) preserved.

## Testing

- Add tests for `ocio_utils.get_transform_ids` and `display_view` parsing/validation using small fixture configs (v2.4 and v2.5).
- Optional: smoke tests that each subcommand runs without error for one representative input.

## Documentation

- Update root README (or CLAUDE.md) to describe the unified CLI and subcommands; keep per-script docs where wrappers remain.
- Design doc: this file in `docs/plans/`.

## Implementation order (high level)

1. Add package `ocio_aces_tools` and `constants.py`, `ocio_utils.py`, `display_view.py`; implement shared functions by extracting from existing scripts.
2. Refactor `ACES_json_to_OCIOmapping.py` and `validate_amf_output_transforms.py` to use the library; remove duplicated code.
3. Add CLI with subcommands; wire `upgrade`, `map`, `validate-amf`, `split`, `enrich`, `lut-build`, `lut-verify`, `repo extract`, `repo compare`.
4. Introduce thin wrapper scripts that call the CLI; preserve existing filenames and args.
5. Optionally refactor enricher, extract_colorspaces, compare_configs, split_config to use the library and call CLI for nested steps, or keep them calling scripts via subprocess (current behavior) until a later pass.
6. Add tests and update docs.
