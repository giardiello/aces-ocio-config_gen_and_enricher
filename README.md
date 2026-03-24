# ACES OCIO Config Generator

Unified pipeline for generating OpenColorIO (OCIO) configurations for the Academy Color Encoding System (ACES). Produces production-ready configs across multiple OCIO versions (2.1, 2.3, 2.5), ACES versions (1.3, 2.0, combined), and config types (reference, studio, cg).

## What It Does

| OCIO Version | ACES 1.3 | ACES 2.0 | Combined (1.3 + 2.0) |
|:---:|:---:|:---:|:---:|
| **2.5** | Worktree generator | Worktree generator | Worktree generator |
| **2.3** | Worktree generator | CLF/LUT baking | Worktree (1.3) + CLF merge (2.0) |
| **2.1** | Downgrade from 2.3 | Downgrade from 2.3 | Downgrade from 2.3 |

ACES 2.0 output transforms require OCIO 2.4+ BuiltinTransforms. For OCIO 2.3, the pipeline bakes these into self-contained CLF files (Matrix + Log + LUT3D) that are compatible with any OCIO >= 2.0 runtime. Display color spaces using v2.4+ builtins (DCDM-D65, ST2084-DCDM-D65, DisplayP3-HDR, etc.) are replaced with analytical Matrix + EOTF transforms or 1D LUTs.

OCIO 2.1 configs are produced by downgrading the v2.3 outputs — stripping `named_transforms`, `aliases`, `encoding` attributes, and `interchange` roles, and replacing all v2.2+ and v2.3+ BuiltinTransforms (DISPLAY, CURVE, CSC) with analytical equivalents or baked 1D LUTs. When you request `--ocio-version 2.1`, the pipeline automatically generates v2.3 first, then downgrades.

Each generated config is then **enriched** with:
- ACES Transform IDs (from the official [ACES Transform Registry](https://github.com/aces-aswf/aces/blob/main/transforms.json))
- Equivalent and inverse transform ID cross-references
- Missing color spaces from a curated repository (S-Log, Canon Log, legacy displays, etc.)

## Quick Start

### Prerequisites

- **Python 3.10+**
- **OpenColorIO >= 2.4** (Python bindings) — `pip install opencolorio`
- **NumPy** — `pip install numpy`
- **Two worktree clones** of the OpenColorIO-Config-ACES repository (see [Setup](#setup))

### Setup

```bash
# 1. Clone this repository
git clone <this-repo-url> OCIO_ACES_CONFIG_GEN
cd OCIO_ACES_CONFIG_GEN

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Clone the OpenColorIO-Config-ACES worktrees (sibling directories)
cd ..

# v4.0.0 worktree (generates OCIO v2.5 configs)
git clone https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES.git
cd OpenColorIO-Config-ACES && git checkout v4.0.0 && pip install -e ".[dev]" && cd ..

# v2.2.0 worktree (generates OCIO v2.3 configs)
git clone https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES.git OpenColorIO-Config-ACES-v23
cd OpenColorIO-Config-ACES-v23 && git checkout v2.2.0 && pip install -e ".[dev]" && cd ..
```

The expected directory layout:

```
Dev_prj/
├── OCIO_ACES_CONFIG_GEN/          # This repository
├── OpenColorIO-Config-ACES/       # v4.0.0 worktree (OCIO 2.5)
└── OpenColorIO-Config-ACES-v23/   # v2.2.0 worktree (OCIO 2.3)
```

### Generate All Configs

```bash
cd OCIO_ACES_CONFIG_GEN

# Build everything (all OCIO versions × all ACES versions × all types):
python build_all_configs.py

# Fast preview (smaller LUTs, lower quality):
python build_all_configs.py --lut-size 33

# Output goes to OUTPUT_CONFIGS/
#   OUTPUT_CONFIGS/OCIO-v2.5/   — 12 configs (self-contained folders)
#   OUTPUT_CONFIGS/OCIO-v2.3/   — 13 configs (self-contained folders)
#   OUTPUT_CONFIGS/OCIO-v2.1/   — 13 configs (self-contained folders)
```

### Build Specific Combinations

```bash
# Only OCIO 2.5, studio configs:
python build_all_configs.py --ocio-version 2.5 --type studio

# Only ACES 2.0 for OCIO 2.3 (CLF/LUT path):
python build_all_configs.py --ocio-version 2.3 --aces-version 2.0

# Combined ACES 1.3+2.0 for all OCIO versions:
python build_all_configs.py --aces-version combined

# Generation only (skip enrichment):
python build_all_configs.py --skip-enrich
```

### Verify Generated Configs

```bash
# Quick validation with ociocheck:
for f in OUTPUT_CONFIGS/OCIO-v*/*/*.ocio; do
  OCIO="$f" ociocheck 2>&1 | grep -q "Tests complete" && echo "OK: $(basename $f)" || echo "FAIL: $(basename $f)"
done

# Numerical comparison against reference/built-in configs:
python verify_configs.py
```

## Pipeline Architecture

### Stage 1: Generation

Depending on the OCIO/ACES combination, one of three strategies is used:

1. **Worktree v2.5** — Runs `opencolorio_config_aces` generators from the v4.0.0 checkout. Produces native OCIO 2.5 configs with BuiltinTransforms.

2. **Worktree v2.3** — Runs generators from the v2.2.0 checkout. Produces OCIO 2.3 configs with ACES 1.x BuiltinTransforms (which are natively supported at v2.3).

3. **CLF/LUT baking** — For ACES 2.0 on OCIO 2.3, bakes each ACES 2.0 view transform into a self-contained CLF file:
   - Forward: `Matrix(AP0→AP1) + Log(ACEScct encode) + LUT3D(ACEScct→CIE-XYZ-D65)`
   - Inverse: `Matrix(XYZ→AP0) + Gamma + LUT3D + LogCamera + Matrix`
   - Display color spaces using v2.4+ builtins are converted to analytical transforms + 1D LUTs

For **combined** configs on OCIO 2.3, both strategies run: the worktree produces the ACES 1.3 base, then ACES 2.0 elements from the CLF path are merged in (color spaces, view transforms, shared views, display views, viewing rules).

### Stage 2: v2.1 Downgrade

When OCIO 2.1 is requested, the pipeline:
1. Generates all v2.3 configs first
2. Copies each v2.3 config folder to `OCIO-v2.1/`
3. Strips v2.2+ features (named transforms, aliases, encoding, interchange)
4. Replaces v2.3+ DISPLAY builtins with analytical Matrix + EOTF transforms
5. Replaces v2.2+ CURVE/CSC builtins (Canon CLog2/3, etc.) with baked 1D LUTs
6. Bakes PQ/HLG EOTF 1D LUTs for display transforms that need them

### Stage 3: Enrichment

The enricher (`ocio_aces_enricher/`) processes each generated config:

1. Downloads the official ACES Transform Registry from GitHub
2. Matches OCIO color space names to ACES Transform IDs
3. Adds equivalent and inverse transform ID cross-references
4. Adds missing color spaces from the curated repository (analytical transforms where possible — no external LUT dependencies for camera log curves)
5. For single-ACES-version configs, prunes URNs from the other version

### Stage 4: Organization

All configs are reorganized into self-contained folders:
- Each `.ocio` config gets its own folder named after the config
- Any required `luts/` directory is placed inside the config's folder
- Configs are fully portable — copy any folder to use it standalone

## CLI Reference

```
python build_all_configs.py [OPTIONS]

Options:
  --ocio-version {2.1,2.3,2.5,all}   OCIO version(s) to generate [default: all]
  --aces-version {1.3,2.0,combined,all}  ACES version(s) [default: all]
  --type {reference,studio,cg,all}    Config type(s) [default: all]
  -o, --output PATH                   Output directory [default: OUTPUT_CONFIGS/]
  --lut-size N                        3D LUT cube size for CLF [default: 65]
  --skip-enrich                       Skip enrichment pass
  --transforms PATH                   Local transforms.json (otherwise downloaded)
  --v25-worktree PATH                 v4.0.0 worktree path
  --v23-worktree PATH                 v2.2.0 worktree path
```

## Output Structure

Each OCIO version directory contains self-contained config folders:

```
OUTPUT_CONFIGS/
├── OCIO-v2.5/
│   ├── cg-config-v4.0.0_aces-v1.3_ocio-v2.5/
│   │   └── cg-config-v4.0.0_aces-v1.3_ocio-v2.5.ocio
│   ├── cg-config-v4.0.0_aces-v2.0_ocio-v2.5/
│   │   └── cg-config-v4.0.0_aces-v2.0_ocio-v2.5.ocio
│   ├── cg-config-v4.0.0_aces-v1.3-v2.0_ocio-v2.5/
│   │   └── cg-config-v4.0.0_aces-v1.3-v2.0_ocio-v2.5.ocio
│   ├── studio-config-v4.0.0_aces-v1.3_ocio-v2.5/
│   │   ├── studio-config-v4.0.0_aces-v1.3_ocio-v2.5.ocio
│   │   └── luts/                     ← enricher-added LUTs
│   └── ...                           (12 configs total)
├── OCIO-v2.3/
│   ├── cg-config-v2.2.0_aces-v1.3_ocio-v2.3/
│   │   └── cg-config-v2.2.0_aces-v1.3_ocio-v2.3.ocio
│   ├── cg-config-v4.0.0_aces-v2.0_ocio-v2.3-clf/
│   │   ├── cg-config-v4.0.0_aces-v2.0_ocio-v2.3-clf.ocio
│   │   └── luts/                     ← CLF files + 1D LUTs
│   ├── studio-config-v2.2.0_aces-v1.3-v2.0_ocio-v2.3/
│   │   ├── studio-config-v2.2.0_aces-v1.3-v2.0_ocio-v2.3.ocio
│   │   └── luts/                     ← merged CLFs + enricher LUTs
│   └── ...                           (13 configs total)
└── OCIO-v2.1/
    ├── cg-config-v2.2.0_aces-v1.3_ocio-v2.1/
    │   ├── cg-config-v2.2.0_aces-v1.3_ocio-v2.1.ocio
    │   └── luts/                     ← baked EOTF + CURVE LUTs
    ├── cg-config-v4.0.0_aces-v2.0_ocio-v2.1-clf/
    │   ├── cg-config-v4.0.0_aces-v2.0_ocio-v2.1-clf.ocio
    │   └── luts/
    └── ...                           (13 configs total)
```

## Key Files

| File | Purpose |
|------|---------|
| `build_all_configs.py` | Main orchestrator — generation, CLF baking, merging, enrichment, downgrade |
| `generate_lut_based_config.py` | Bakes ACES 2.0 BuiltinTransforms into CLF files; v2.1 downgrade logic |
| `inverse_pseudolog.py` | Pseudo-log encoding for inverse LUT baking |
| `verify_configs.py` | Numerical verification against reference/built-in configs |
| `ACES_json_to_OCIOmapping.py` | Correlates ACES Transform IDs with OCIO color space names |
| `upgrade_ocio_v24_to_v25.py` | Upgrades OCIO v2.4 configs to v2.5 format |
| `split_config_by_aces_version.py` | Splits combined configs into single-ACES-version configs |
| `ocio_aces_enricher/` | Enrichment subsystem (adds IDs, missing color spaces) |
| `ocio_aces_enricher/colorspace_repository/` | Curated missing color spaces (analytical transforms) |
| `transforms.json` | Local copy of the ACES Transform Registry |

## BuiltinTransform Compatibility

The pipeline handles BuiltinTransform version requirements automatically:

| BuiltinTransform | Min OCIO | Replacement for lower versions |
|---|---|---|
| ACES 2.0 view transforms | 2.4 | CLF files (Matrix + Log + LUT3D) |
| `DISPLAY - CIE-XYZ-D65_to_DCDM-D65` | 2.4 | ExponentTransform (gamma 2.6) |
| `DISPLAY - CIE-XYZ-D65_to_ST2084-DCDM-D65` | 2.4 | 1D LUT (PQ EOTF) |
| `DISPLAY - CIE-XYZ-D65_to_DisplayP3-HDR` | 2.4 | Matrix + ExponentWithLinear |
| `DISPLAY - CIE-XYZ-D65_to_*-MIRROR NEGS` | 2.4 | Matrix + Exponent |
| `DISPLAY - CIE-XYZ-D65_to_sRGB` | 2.3 | Matrix + ExponentWithLinear (v2.1 only) |
| `DISPLAY - CIE-XYZ-D65_to_DisplayP3` | 2.3 | Matrix + ExponentWithLinear (v2.1 only) |
| `DISPLAY - CIE-XYZ-D65_to_REC.2100-PQ` | 2.3 | Matrix + 1D LUT (v2.1 only) |
| `DISPLAY - CIE-XYZ-D65_to_REC.2100-HLG-1000nit` | 2.3 | Matrix + 1D LUT (v2.1 only) |
| `CURVE - CANON_CLOG2_to_LINEAR` | 2.2 | 1D LUT (v2.1 only) |
| `CURVE - CANON_CLOG3_to_LINEAR` | 2.2 | 1D LUT (v2.1 only) |
| `CANON_CLOG2-CGAMUT_to_ACES2065-1` | 2.2 | 1D LUT + Matrix (v2.1 only) |
| `CANON_CLOG3-CGAMUT_to_ACES2065-1` | 2.2 | 1D LUT + Matrix (v2.1 only) |
| `APPLE_LOG_to_ACES2065-1` | 2.4 | 1D LUT + Matrix |
| `CURVE - APPLE_LOG_to_LINEAR` | 2.4 | 1D LUT |

## Troubleshooting

### "No v2.5 source found" for CLF path
The CLF path requires a v2.5 ACES 2.0 config as input. If you're building OCIO 2.3 ACES 2.0 configs, the pipeline will auto-generate the v2.5 prerequisite. Make sure the v2.5 worktree is accessible.

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
