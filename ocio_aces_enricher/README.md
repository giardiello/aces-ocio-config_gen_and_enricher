# ocio_aces_enricher — ACES Transform ID Enrichment

Enriches OpenColorIO configs with ACES transform IDs and missing color spaces. Works with both OCIO v2.4 and v2.5 configs, ACES 1.x and 2.0.

## What It Does

1. **Upgrades** OCIO v2.4 configs to v2.5 (migrates `ACEStransformID:` from `description` to `interchange.amf_transform_ids`)
2. **Maps** OCIO color space names to ACES Transform IDs using the official [ACES Transform Registry](https://github.com/aces-aswf/aces/blob/main/transforms.json)
3. **Enriches** each color space with equivalent and inverse transform ID cross-references
4. **Adds missing color spaces** from a curated repository (camera IDTs, legacy displays, utility looks)
5. **Prunes** (optional) URNs that don't belong to the target ACES version

## Usage

Via the unified CLI:

```bash
# Enrich an ACES 2.0 studio config
python -m ocio_aces_tools enrich -i studio.ocio -o enriched.ocio \
    --aces-version 2.0 --config-type studio

# Enrich an ACES 1.3 reference config
python -m ocio_aces_tools enrich -i reference.ocio -o enriched.ocio \
    --aces-version 1.3 --config-type reference

# Preview what would change (no output written)
python -m ocio_aces_tools enrich -i studio.ocio --aces-version 2.0 --report-only

# Prune non-matching URNs then enrich
python -m ocio_aces_tools enrich -i studio.ocio -o clean.ocio \
    --aces-version 2.0 --config-type studio --prune

# Use a local transforms.json instead of downloading
python -m ocio_aces_tools enrich -i studio.ocio -o enriched.ocio \
    --aces-version 2.0 --config-type studio --transforms transforms.json
```

Or directly:

```bash
python ocio_aces_enricher/scripts/enrich_ocio_config.py \
    -i studio.ocio -o enriched.ocio \
    --aces-version 2.0 --config-type studio
```

### Options

| Flag | Description |
|------|-------------|
| `-i, --input` | Input OCIO config file |
| `-o, --output` | Output enriched config (auto-named with timestamp if omitted) |
| `--aces-version` | Target ACES version: `1.x`, `1.3`, `2.0`, or `all` |
| `--config-type` | Config type: `studio`, `reference`, or `cg` |
| `--transforms` | Path to local `transforms.json` (default: download from GitHub) |
| `--transforms-url` | Override download URL |
| `--prune` | Remove URNs from other ACES versions before enriching |
| `--report-only` | Generate audit report without modifying the config |
| `--skip-upgrade` | Skip the v2.4 → v2.5 upgrade step |
| `--work-dir` | Directory for intermediate files (useful for debugging) |

## Additional Scripts

### `extract_colorspaces.py` — Populate the Repository

Extracts individual color spaces from an OCIO config into the repository as standalone `.ocio` files.

```bash
python -m ocio_aces_tools repo extract \
    -i reference-config-v2.0.ocio \
    -o ocio_aces_enricher/colorspace_repository \
    --aces-version aces_2.0 --config-type reference
```

### `compare_configs.py` — Diff Two Configs

Compares two configs to identify missing color spaces and transform IDs.

```bash
python -m ocio_aces_tools repo compare \
    --source my_config.ocio --reference official_config.ocio
```

## Color Space Repository

The `colorspace_repository/` directory (gitignored — regenerable via `extract_colorspaces.py`) contains individual color space files organized by ACES version and config type:

```
colorspace_repository/
├── aces_1.x/
│   ├── reference/     # 33 color spaces
│   └── studio/        # studio-specific spaces
└── aces_2.0/
    ├── reference/     # 36 color spaces
    └── studio/        # studio-specific spaces
```

Each file is a minimal OCIO config containing one color space with its transforms and ACES IDs. When enriching, the tool scans the appropriate repository directory and adds any color spaces whose transform IDs are not already present in the target config.

CG configs intentionally skip repository addition (their scope is limited by design).

## Transform Filtering

The enrichment process filters out noise from the ACES registry:

- **Utility transforms** (ACESutil, ACESlib, Lib) — ~142 transforms
- **ARRI raw variants** (v2-raw, v3-raw IDTs) — ~5,300 transforms
- **ARRI EI/ISO/CCT variants** — except 14 standard v3-logC EI values (160–3200)

All other transform types are kept: IDT, ODT, CSC, ACEScsc, LMT, Look, RRT, RRTODT, Output, InvOutput.

## Module Structure

```
ocio_aces_enricher/
├── __init__.py
├── README.md
├── colorspace_repository/     # Curated color spaces (gitignored)
│   ├── aces_1.x/
│   └── aces_2.0/
└── scripts/
    ├── __init__.py
    ├── enrich_ocio_config.py  # Main enrichment tool
    ├── extract_colorspaces.py # Repository population
    └── compare_configs.py     # Config comparison
```
