# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This repository contains tools for working with ACES (Academy Color Encoding System) transforms and OpenColorIO (OCIO) configurations. The primary purpose is to correlate ACES transform IDs with OCIO color space names and merge multiple OCIO configurations.

## Core Components

### 1. ACES Transform Mapping Script (`ACES_json_to_OCIOmapping.py`)

The main Python script that correlates ACES transform IDs with OCIO color space names by:
- Parsing ACES transforms JSON data (with support for `transformsData` structure)
- Extracting ACEStransformID references from OCIO config (both v2.4 descriptions and v2.5+ interchange)
- Building comprehensive maps of primary IDs, equivalent IDs, and inverse transform IDs
- Generating reports and updated configuration files

### 2. OCIO Version Upgrade Script (`upgrade_ocio_v24_to_v25.py`)

Script that upgrades OCIO v2.4 configs to v2.5 format by:
- Migrating ACEStransformID entries from `description` to `interchange.amf_transform_ids`
- Updating the config version number to 2.5
- Cleaning up description fields (removing migrated IDs)
- Preserving all existing color spaces and transforms without modification

**What it does:**
- Schema upgrade only - no color space additions or transform modifications
- Moves transform IDs to the new v2.5 first-class attribute structure
- Validates the upgraded config before saving

**What it does NOT do:**
- Add new color spaces or transforms
- Modify existing color transforms or relationships
- Change color space hierarchies or groupings

**Key Functions (ACES Transform Mapping):**
- `build_aces_id_map()` - Maps all ACES transform IDs (primary + equivalents) to transform objects
- `parse_ocio_config()` - Extracts ACEStransformIDs from both v2.4 descriptions and v2.5+ interchange
- `process_files()` - Main orchestrator that correlates data and generates outputs
- `update_item_with_related_ids()` - Enriches OCIO with related transform IDs (version-aware)

**Key Functions (Version Upgrade/Downgrade):**
- `upgrade_config_to_v25()` - Main upgrade orchestrator (v2.4 → v2.5)
- `migrate_transform_ids_to_interchange()` - Moves IDs from description to interchange.amf_transform_ids
- `downgrade_v25_to_v24()` - Downgrades v2.5 → v2.4 (interchange → description, strip interop_id)
- `migrate_interchange_to_description()` - Moves URNs from interchange.amf_transform_ids to description

**Data Structure:**
The script expects ACES JSON with this structure:
```
{
  "transformsData": {
    "v1.3": { "transforms": [...] },
    "v2.0.0+2025.04.04": { "transforms": [...] }
  }
}
```

Each transform contains:
- `transformId` - Primary identifier
- `previousEquivalentTransformIds[]` - Array of equivalent IDs
- `inverseTransformId` - Inverse transform reference
- `transformType` - Category (e.g., ODT, LMT, CSC)

### 3. ACES Transforms Data (`transforms.json`)

The comprehensive ACES transforms database containing transform definitions across multiple ACES versions. This ~68,000 line JSON file includes:

**Available ACES Versions:**
- `v2.0.0+2025.04.04` (latest)
- `v1.3.1`
- `v1.3`
- `v1.2`
- `v1.1`
- `v1.0.3`, `v1.0.2`, `v1.0.1`, `v1.0`

Each version contains transforms with full metadata including transform IDs, user-friendly names, types (CSC, ODT, LMT, etc.), equivalent IDs, inverse transforms, and source URLs.

### 4. OCIO Configuration Files (`INPUT_OCIO/`)

Directory structure:
- `REFERENCE/` - Reference OCIO configs for ACES v1.3 (OCIO v2.4) and v2.0 (OCIO v2.5)
- `STUDIO/` - Studio OCIO configs including all-views variants

Naming convention: `{type}-config-v{version}_aces-v{aces_version}_ocio-v{ocio_version}.ocio`

**OCIO Version Differences:**
- **v2.4 and earlier**: Transform IDs stored in `description` attribute as text with `ACEStransformID:` prefix
- **v2.5+**: Transform IDs stored in `interchange.amf_transform_ids` as first-class attribute

The parser automatically detects and handles both formats.

### 5. Netflix Merge Configuration (`netflix-merge/`)

Contains:
- `merge-studios.ociom` - OCIOM (OpenColorIO Merge) configuration for merging ACES 1.3 and ACES 2.0 studio configs
- Pre-existing studio configs for different ACES versions
- Output of merge operations

### 6. Vendor Display Extensions (`ocio_vendor_extensions/`)

Adds non-ACES vendor-specific display views (FilmLight, DaVinci, ARRI, RED IPP2, Sony) to OCIO configs via the `extend` subcommand.

**Architecture:** Each vendor is a "family" package under `families/` containing:
- `family.yaml` — Pydantic-validated manifest with display mappings, intermediates, and dependencies
- `colorspaces.ocio` — OCIO config snippet with vendor color spaces
- `luts/` — Pre-baked CLF files (ACES2065-1 → display in one file). See `docs/clf-baking-guide.md` for reproducibility.

**CLF migration (2026-03):** Display views now use self-contained `.clf` files instead of `GroupTransform` chains (ColorSpaceTransform + vendor 3D LUT). Each CLF is baked from the original vendor LUT using `aces-clf-baker`, wrapping the LUT with a gamut matrix and transfer function decode shaper so input is ACES2065-1. FilmLight intermediates (`T-Log : E-Gamut 2`, `Linear : E-Gamut 2`) are now analytical OCIO transforms (`LogCameraTransform` + `MatrixTransform`). Pre-migration backup: `families_pre_clf/`. Baking script: `scripts/bake_vendor_clfs.sh`. Verification: `scripts/verify_clf_migration.py`.

**Key modules:**
- `family_loader.py` — YAML manifest loading + Pydantic validation + family discovery
- `dependency_resolver.py` — Topological sort via `graphlib.TopologicalSorter`
- `config_merger.py` — Color space extraction from snippets + LUT file copying
- `display_wiring.py` — View-to-display wiring + missing display handling + view reordering
- `extend_config.py` — Main orchestrator + argparse CLI

**Available families:** `arri`, `davinci`, `filmlight`, `red_ipp2`, `sony`

**CLI usage:**
```bash
python -m ocio_aces_tools extend -i config.ocio -o extended.ocio --families all --skip-missing-displays
python -m ocio_aces_tools extend -i config.ocio --families arri davinci --dry-run
python -m ocio_aces_tools extend --list-families
```

**Missing display policy resolution:** `--dry-run` (forces skip) → `--create-missing-displays` / `--skip-missing-displays` → `OCIO_ACES_EXTEND_MISSING_DISPLAYS` env var → interactive prompt

**Supported OCIO versions:** 2.3, 2.4, 2.5 (preserves declared version on output)

## Development Setup

**Required Dependencies:**
```bash
pip install OpenColorIO
```

The script uses `PyOpenColorIO` library for OCIO parsing and serialization.

**CMS / inverse benchmarks:** Forward display+view should use **built-in ACES 2.5** (`INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio`) so tests target highest-quality renders. See `benchmark_cms_inverse_shaders.py` (default) and `test_cms_display_acescct_lut.py` (`--builtin-config`).

## Unified CLI

All tools can be run through a single entry point:

```bash
python -m ocio_aces_tools <subcommand> [args...]
```

**Subcommands:** `upgrade` | `map` | `validate-amf` | `split` | `enrich` | `extend` | `lut-build` | `lut-verify` | `repo` (with `extract` | `compare`).

**Examples:**
```bash
python -m ocio_aces_tools upgrade input.ocio -o output.ocio
python -m ocio_aces_tools map transforms.json config.ocio -o out/
python -m ocio_aces_tools validate-amf config.ocio -o reports/
python -m ocio_aces_tools split merged.ocio v1.ocio v2.ocio
python -m ocio_aces_tools enrich -i studio.ocio -o out.ocio --aces-version 2.0 --config-type studio
# (Optional) `--transforms path/to/transforms.json` uses a local file; default is a fresh download from the official ACES registry (aces-aswf/aces `main`).
python -m ocio_aces_tools extend -i studio.ocio -o extended.ocio --families all --skip-missing-displays
python -m ocio_aces_tools extend --list-families
python -m ocio_aces_tools repo extract -i config.ocio -o repo/ --aces-version aces_2.0 --config-type reference
python -m ocio_aces_tools repo compare --source a.ocio --reference b.ocio
```

The legacy script names are **wrappers** that invoke the same CLI: `upgrade_ocio_v24_to_v25.py`, `ACES_json_to_OCIOmapping.py`, `validate_amf_output_transforms.py`, `split_config_by_aces_version.py`, and `extend_ocio_config.py` behave the same when run directly (e.g. `python upgrade_ocio_v24_to_v25.py input.ocio -o out.ocio`).

Shared library: `ocio_aces_tools` provides `ocio_utils.get_transform_ids()`, `display_view.parse_display_view_structure()`, and `constants.OUTPUT_TRANSFORM_TYPES` for use by scripts or other code.

## Common Commands

### Running the ACES Transform Mapping

Basic usage:
```bash
python3 ACES_json_to_OCIOmapping.py <transforms_json> <ocio_config>
```

With filtering by ACES version:
```bash
python3 ACES_json_to_OCIOmapping.py transforms.json config.ocio -v v1.3 v2.0.0+2025.04.04
```

With filtering by transform type:
```bash
python3 ACES_json_to_OCIOmapping.py transforms.json config.ocio -t ODT LMT CSC
```

With custom output folder:
```bash
python3 ACES_json_to_OCIOmapping.py transforms.json config.ocio -o output/
```

Combined filters:
```bash
python3 ACES_json_to_OCIOmapping.py transforms.json config.ocio -v v2.0.0+2025.04.04 -t ODT -o results/
```

### Upgrading OCIO v2.4 to v2.5

Basic upgrade:
```bash
python3 upgrade_ocio_v24_to_v25.py input_v24.ocio -o output_v25.ocio
```

Upgrade in-place (overwrites original):
```bash
python3 upgrade_ocio_v24_to_v25.py input.ocio
```

Batch upgrade all v2.4 configs:
```bash
for config in INPUT_OCIO/**/*_ocio-v2.4.ocio; do
  output="${config/_ocio-v2.4.ocio/_ocio-v2.5.ocio}"
  python3 upgrade_ocio_v24_to_v25.py "$config" -o "$output"
done
```

**What the upgrade does:**
- Sets config version to 2.5
- Migrates ACEStransformID entries from `description` to `interchange.amf_transform_ids`
- Cleans up description fields (removes migrated IDs and section headers)
- Validates the upgraded config
- Preserves all color spaces, transforms, and relationships

### Output Files Generated (Transform Mapping)

The script creates four output files in the specified output folder:

1. `transforms_updated.json` - ACES JSON with added `OCIOalias` fields for matched transforms
2. `ocio_transform_matches.csv` - Simple mapping of OCIO names to ACEStransformIDs (matches only)
3. `aces_ocio_mapping_report.csv` - Full report including MISSING entries and notes about related IDs
4. `config_updated.ocio` - OCIO config enriched with equivalent and inverse transform IDs
   - For OCIO v2.5+: IDs added to `interchange.amf_transform_ids`
   - For OCIO v2.4 and earlier: IDs added to `description` attribute

### Built-in display reference (tests & benchmarks)

Canonical **built-in** chains (see `ocio_builtins_display.py`):

- **Forward:** `ACEScct` → `ACES2065-1` → **Display+View** (forward).
- **Inverse:** **Display+View** (inverse) → `ACES2065-1` → `ACEScct`.

Do not equate “built-in inverse” with `getProcessor(display_cs, "ACEScct")` on a synthetic CS unless that matches the above.

Inverse CLF shapers (`generate_lut_based_config.py --inv-encoding`): **acescc** (pure log), **acescct** (ACEScct LogCamera + Range, aligned with forward CLF), extended-log, camera-log, jplog2.

### Inverse LUT / CLF pipeline (important)

Inverse cubes are baked **display linear → remapped log** (inverse VT on the same view’s forward output), not Un-tone-mapped XYZ + inverse VT (that chain does **not** recover AP0). Inverse CLFs are **LUT3D + decode** only; **input = same encoding as forward LUT output** for that view (not generic “CIE-XYZ via Un-tone-mapped” unless your view actually outputs that). Tune log domain with `optimize_inverse_log_encoding.py` (`--ap1-y-max` for SDR-relevant CMS scoring).

### OCIO v2.4 Downgrade (`generate_lut_based_config.py`)

The `downgrade_v25_to_v24()` function handles v2.5→v2.4 conversion:
- Sets `ocio_profile_version` to 2.4
- Migrates `interchange.amf_transform_ids` URNs into `description` as `ACEStransformID:` lines
- Strips per-item `interchange:` blocks and `interop_id:` lines
- Preserves `aces_interchange` / `cie_xyz_d65_interchange` role names (valid at v2.4)
- Replaces v2.5-only `MIRROR NEGS` DISPLAY builtins with analytical Matrix + EOTF equivalents
- Updates the config `name:` field

The `DISPLAY_BUILTIN_REPLACEMENTS_V25` dict handles the 5 MIRROR NEGS builtins introduced in OCIO 2.5 (sRGB, G2.2-REC.709, G2.6-P3-D65, REC.1886-REC.709, REC.1886-REC.2020).

The shared `migrate_interchange_to_description()` function (module-level) handles the URN migration and is also used by `generate_v23_config()`.

### OCIO v2.1 Downgrade (`generate_lut_based_config.py`)

The `downgrade_v23_to_v21()` function handles full v2.3→v2.1 conversion:
- Strips v2.2+ features (named_transforms, aliases, encoding, interchange)
- Replaces v2.3+ DISPLAY builtins with analytical Matrix + EOTF transforms
- Replaces v2.4+ DISPLAY builtins (DCDM-D65, ST2084-DCDM-D65) with Exponent/1D LUT
- Replaces v2.2+ CURVE builtins (Canon CLog2/3) with baked 1D LUTs
- Replaces v2.2+ CSC builtins (Canon CLog2/3 CGamut) with 1D LUT + Matrix
- Bakes PQ/HLG EOTF 1D LUTs on demand and ensures `search_path: luts` is set

The `DISPLAY_BUILTIN_REPLACEMENTS` dict handles v2.4+ builtins always (for v2.3 output).
The `DISPLAY_BUILTINS_NEEDING_1D_LUT` dict handles v2.4+ builtins needing baked LUTs.
The `DISPLAY_BUILTIN_REPLACEMENTS_V21` and `DISPLAY_BUILTINS_NEEDING_1D_LUT_V21` dicts handle v2.3+ builtins for v2.1 only.
The `CURVE_BUILTINS_V22` and `CSC_BUILTINS_V22` dicts handle v2.2+ builtins for v2.1 only.

### OCIO Configuration Merging

The repository uses OCIOM (OpenColorIO Merge) format for merging configurations. The `merge-studios.ociom` file defines how to merge ACES 1.3 and 2.0 studio configs with specific strategies:

- `PreferBase` - Default merge strategy
- `avoid_duplicates: true` - Prevents duplicate color spaces
- `error_on_conflict: false` - Allows conflicts to be resolved by strategy

To perform the merge, use the appropriate OCIO tooling that supports the OCIOM format.

## Architecture Notes

**OCIO Version Detection and Handling:**
The script automatically detects the OCIO profile version and adapts its behavior:
- **Parsing**: Checks both `interchange.amf_transform_ids` (v2.5+) and `description` field (v2.4) for transform IDs
- **Updating**: Adds related IDs to `interchange.amf_transform_ids` for v2.5+ or `description` for v2.4
- Uses `config.getMajorVersion()` and `config.getMinorVersion()` to determine version

**ID Resolution Strategy:**
The script handles multiple ID types by building a comprehensive map:
1. Primary transform IDs are directly mapped
2. Equivalent IDs (`previousEquivalentTransformIds`) are mapped to their parent transform
3. When enriching OCIO configs, the script adds:
   - "Previous Equivalent ACES Transform IDs" - All equivalent IDs not already present
   - "Inverse ACES Transform ID" - Inverse transform if available
4. For v2.5+, related IDs are appended to `interchange.amf_transform_ids` (newline-separated)
5. For v2.4, related IDs are formatted sections appended to `description`

**Filtering Logic:**
- Version filtering operates at the top level of `transformsData`
- Type filtering operates at the individual transform level using `transformType` field
- Both filters can be combined; if no transforms match criteria, processing stops with a warning

**Report Generation:**
The full CSV report includes a "Notes" column that indicates when a transform ID is:
- Missing from OCIO (shows "MISSING")
- Added to another OCIO item's description as a related ID (shows "Added to description of '{name}'")

**OCIO Config Updates:**
The script modifies OCIO configs in memory using PyOpenColorIO's object model:
- Iterates through ColorSpaces, Looks, and ViewTransforms
- Updates descriptions without affecting other config properties
- Serializes updated config preserving OCIO v2.x format
