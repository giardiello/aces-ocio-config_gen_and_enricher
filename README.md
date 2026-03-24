# ACES OCIO Config Generator & Enricher

Tools for generating, enriching, and extending [OpenColorIO](https://opencolorio.org/) (OCIO) configurations for the [Academy Color Encoding System](https://acescentral.com/) (ACES).

## What This Project Does

This project is a collection of Python tools organized into modules that work together as a pipeline — or independently as standalone utilities:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        build_all_configs.py                        │
│                     (full pipeline orchestrator)                    │
└──────┬──────────────────┬──────────────────┬───────────────────────┘
       │                  │                  │
       ▼                  ▼                  ▼
  ┌──────────┐   ┌────────────────┐   ┌──────────────────┐
  │ Worktree │   │ CLF/LUT Baking │   │    Enrichment    │
  │Generators│   │  + Downgrade   │   │                  │
  │ (external│   │                │   │ ocio_aces_       │
  │  repos)  │   │ generate_lut_  │   │ enricher/        │
  └──────────┘   │ based_config.py│   └──────────────────┘
                 └────────────────┘
                                          ┌──────────────────┐
  Standalone tools:                       │ Vendor Display    │
  ┌──────────────────┐                    │ Extensions        │
  │ ocio_aces_tools/ │                    │                   │
  │ (unified CLI)    │                    │ ocio_vendor_      │
  └──────────────────┘                    │ extensions/       │
                                          └──────────────────┘
```

| Module | Purpose | Documentation |
|--------|---------|---------------|
| [`ocio_aces_tools/`](ocio_aces_tools/) | Unified CLI entry point and shared library | [README](ocio_aces_tools/README.md) |
| [`ocio_aces_enricher/`](ocio_aces_enricher/) | Enrich configs with ACES transform IDs and missing color spaces | [README](ocio_aces_enricher/README.md) |
| [`ocio_vendor_extensions/`](ocio_vendor_extensions/) | Add vendor display views (FilmLight, DaVinci, ARRI, RED, Sony) | [README](ocio_vendor_extensions/README.md) |
| [`scripts/`](scripts/) | CLF baking, verification, and build helpers | [README](scripts/README.md) |
| `build_all_configs.py` | Full pipeline orchestrator (generation → baking → enrichment → downgrade) | [Pipeline](#pipeline-architecture) section below |
| `generate_lut_based_config.py` | Bake ACES 2.0 BuiltinTransforms into CLF files; v2.1/v2.3 downgrade | [CLF Baking](#stage-1-generation) section below |

## Quick Start

### Prerequisites

- **Python 3.10+**
- **OpenColorIO >= 2.4** (Python bindings) — `pip install opencolorio`
- **NumPy** — `pip install numpy`

```bash
git clone https://github.com/giardiello/aces-ocio-config_gen_and_enricher.git
cd aces-ocio-config_gen_and_enricher
pip install -r requirements.txt
```

### Use Individual Tools (no external dependencies)

The unified CLI provides access to all tools:

```bash
python -m ocio_aces_tools <subcommand> [args...]
```

| Subcommand | What it does |
|------------|-------------|
| `upgrade` | Upgrade OCIO v2.4 config to v2.5 format |
| `map` | Correlate ACES Transform IDs with OCIO color space names |
| `enrich` | Enrich config with ACES IDs and missing color spaces |
| `extend` | Add vendor display views (FilmLight, DaVinci, ARRI, RED, Sony) |
| `split` | Split combined config into ACES 1.x and 2.0 configs |
| `validate-amf` | Validate AMF output transform URN → Display+View mappings |
| `lut-build` | Generate CLF-based OCIO 2.3/2.1 config from ACES 2.0 |
| `lut-verify` | Verify LUT-based config against BuiltIn reference |
| `repo extract` | Extract color spaces from config into repository |
| `repo compare` | Compare two configs to find missing color spaces |

Examples:

```bash
# Upgrade a v2.4 config to v2.5
python -m ocio_aces_tools upgrade input.ocio -o output.ocio

# Enrich a studio config with ACES transform IDs
python -m ocio_aces_tools enrich -i studio.ocio -o enriched.ocio \
    --aces-version 2.0 --config-type studio

# Add vendor display views
python -m ocio_aces_tools extend -i config.ocio -o extended.ocio \
    --families all --skip-missing-displays

# List available vendor families
python -m ocio_aces_tools extend --list-families
```

See [`ocio_aces_tools/README.md`](ocio_aces_tools/README.md) for full CLI reference.

### Generate Full Config Suite (requires external worktrees)

The full pipeline generates production-ready configs across multiple OCIO versions (2.1, 2.3, 2.5), ACES versions (1.3, 2.0, combined), and config types (reference, studio, cg).

This requires two clones of the [OpenColorIO-Config-ACES](https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES) repository as sibling directories:

```bash
cd ..

# v4.0.0 — generates OCIO v2.5 configs
# https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES/tree/v4.0.0
git clone https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES.git
cd OpenColorIO-Config-ACES && git checkout v4.0.0 && pip install -e ".[dev]" && cd ..

# v2.2.0 — generates OCIO v2.3 configs
# https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES/tree/v2.2.0
git clone https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES.git OpenColorIO-Config-ACES-v23
cd OpenColorIO-Config-ACES-v23 && git checkout v2.2.0 && pip install -e ".[dev]" && cd ..
```

Expected layout:

```
parent_dir/
├── aces-ocio-config_gen_and_enricher/   # This repository
├── OpenColorIO-Config-ACES/             # v4.0.0 worktree (OCIO 2.5)
└── OpenColorIO-Config-ACES-v23/         # v2.2.0 worktree (OCIO 2.3)
```

Then generate:

```bash
cd aces-ocio-config_gen_and_enricher

# Build everything:
python build_all_configs.py

# Build specific combinations:
python build_all_configs.py --ocio-version 2.5 --type studio
python build_all_configs.py --ocio-version 2.3 --aces-version 2.0
python build_all_configs.py --aces-version combined
```

## Pipeline Architecture

### What gets generated

| OCIO Version | ACES 1.3 | ACES 2.0 | Combined (1.3 + 2.0) |
|:---:|:---:|:---:|:---:|
| **2.5** | Worktree generator | Worktree generator | Worktree generator |
| **2.3** | Worktree generator | CLF/LUT baking | Worktree (1.3) + CLF merge (2.0) |
| **2.1** | Downgrade from 2.3 | Downgrade from 2.3 | Downgrade from 2.3 |

### Stage 1: Generation

Depending on the OCIO/ACES combination, one of three strategies is used:

1. **Worktree v2.5** — Runs `opencolorio_config_aces` generators from the v4.0.0 checkout. Produces native OCIO 2.5 configs with BuiltinTransforms.

2. **Worktree v2.3** — Runs generators from the v2.2.0 checkout. Produces OCIO 2.3 configs with ACES 1.x BuiltinTransforms.

3. **CLF/LUT baking** — For ACES 2.0 on OCIO 2.3, bakes each view transform into a self-contained CLF file:
   - Forward: `Matrix(AP0→AP1) + Log(ACEScct encode) + LUT3D(ACEScct→CIE-XYZ-D65)`
   - Inverse: `Matrix(XYZ→AP0) + Gamma + LUT3D + LogCamera + Matrix`
   - Display color spaces using v2.4+ builtins are converted to analytical transforms + 1D LUTs

For **combined** configs on OCIO 2.3, both strategies run: the worktree produces the ACES 1.3 base, then ACES 2.0 elements from the CLF path are merged in.

### Stage 2: v2.1 Downgrade

When OCIO 2.1 is requested, the pipeline generates v2.3 first, then:
- Strips v2.2+ features (named transforms, aliases, encoding, interchange)
- Replaces v2.3+ DISPLAY builtins with analytical Matrix + EOTF transforms
- Replaces v2.2+ CURVE/CSC builtins (Canon CLog2/3, etc.) with baked 1D LUTs

### Stage 3: Enrichment

The [enricher](ocio_aces_enricher/) processes each generated config:
1. Downloads the official ACES Transform Registry from GitHub
2. Matches OCIO color space names to ACES Transform IDs
3. Adds equivalent and inverse transform ID cross-references
4. Adds missing color spaces from the curated repository

### Stage 4: Organization

All configs are placed in self-contained folders — each `.ocio` config gets its own directory with any required `luts/` alongside it.

## Output Structure

```
OUTPUT_CONFIGS/
├── OCIO-v2.5/
│   ├── studio-config-v4.0.0_aces-v2.0_ocio-v2.5/
│   │   └── studio-config-v4.0.0_aces-v2.0_ocio-v2.5.ocio
│   └── ...                           (12 configs)
├── OCIO-v2.3/
│   ├── studio-config-v4.0.0_aces-v2.0_ocio-v2.3-clf/
│   │   ├── studio-config-v4.0.0_aces-v2.0_ocio-v2.3-clf.ocio
│   │   └── luts/                     ← CLF files + 1D LUTs
│   └── ...                           (13 configs)
└── OCIO-v2.1/
    ├── studio-config-v4.0.0_aces-v2.0_ocio-v2.1-clf/
    │   ├── studio-config-v4.0.0_aces-v2.0_ocio-v2.1-clf.ocio
    │   └── luts/                     ← baked EOTF + CURVE LUTs
    └── ...                           (13 configs)
```

## CLI Reference (`build_all_configs.py`)

```
python build_all_configs.py [OPTIONS]

Options:
  --ocio-version {2.1,2.3,2.5,all}      OCIO version(s) to generate [default: all]
  --aces-version {1.3,2.0,combined,all}  ACES version(s) [default: all]
  --type {reference,studio,cg,all}       Config type(s) [default: all]
  -o, --output PATH                      Output directory [default: OUTPUT_CONFIGS/]
  --lut-size N                           3D LUT cube size for CLF [default: 65]
  --skip-enrich                          Skip enrichment pass
  --transforms PATH                      Local transforms.json (otherwise downloaded)
  --v25-worktree PATH                    v4.0.0 worktree path
  --v23-worktree PATH                    v2.2.0 worktree path
```

## Key Files (root level)

| File | Role |
|------|------|
| `build_all_configs.py` | Full pipeline orchestrator |
| `generate_lut_based_config.py` | CLF baking + v2.1/v2.3 downgrade logic |
| `ACES_json_to_OCIOmapping.py` | ACES Transform ID ↔ OCIO color space correlation |
| `upgrade_ocio_v24_to_v25.py` | OCIO v2.4 → v2.5 format migration |
| `split_config_by_aces_version.py` | Split combined configs by ACES version |
| `validate_amf_output_transforms.py` | AMF output transform validation |
| `add_missing_cscs.py` | Add missing CSC color spaces to CLF-based configs |
| `inverse_pseudolog.py` | Pseudo-log encoding for inverse LUT baking |
| `verify_configs.py` | Numerical verification against reference configs |
| `transforms.json` | Local copy of the ACES Transform Registry |

## External Dependencies

The **individual tools** (`upgrade`, `map`, `enrich`, `extend`, `split`, etc.) work standalone with just `pip install -r requirements.txt`.

The **full pipeline** (`build_all_configs.py`) additionally requires:
- [OpenColorIO-Config-ACES](https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES) — two worktree clones (v4.0.0 and v2.2.0)

The **CLF baking script** (`scripts/bake_vendor_clfs.sh`) additionally requires:
- `aces-clf-baker` — from `IDT_Maker/ACES_CLF_BAKER_EXTENDED` (sibling repository)

## Troubleshooting

### "No v2.5 source found" for CLF path
The CLF path requires a v2.5 ACES 2.0 config as input. The pipeline auto-generates the v2.5 prerequisite. Make sure the v2.5 worktree is accessible.

### Enrichment fails with "transforms.json" errors
The enricher downloads the official registry from GitHub. If you're offline, provide a local copy: `--transforms transforms.json`

### Worktree generator fails
Ensure the worktree dependencies are installed:
```bash
cd ../OpenColorIO-Config-ACES && pip install -e ".[dev]"
cd ../OpenColorIO-Config-ACES-v23 && pip install -e ".[dev]"
```

The v2.3 worktree also needs `semver` and `requests`:
```bash
cd ../OpenColorIO-Config-ACES-v23 && pip install semver requests
```
