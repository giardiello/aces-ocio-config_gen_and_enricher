# OCIO ACES Config Enricher

Automatically upgrade and enrich OpenColorIO configs with ACES transform IDs and missing color spaces.

## Features

- ✅ **Automatic OCIO Upgrade**: Upgrades v2.4 configs to v2.5 format
- ✅ **ACES Transform ID Mapping**: Adds ACES transform IDs to color spaces using transforms.json
- ✅ **Transform Enrichment**: Enriches with equivalent/inverse transform IDs for version compatibility
- ✅ **Missing Color Space Detection**: Identifies what's missing from your config
- ✅ **Repository-Based Addition**: Adds missing color spaces from curated repository
- ✅ **Multi-Version Support**: Handles both ACES 1.x and 2.0
- ✅ **Config Type Support**: Works with both Studio and Reference configs
- ✅ **Smart Filtering**: Automatically filters ARRI raw variants and utility transforms

## Quick Start

### Basic Usage

```bash
# Enrich an ACES 2.0 reference config (official transforms.json is downloaded each run)
python3 scripts/enrich_ocio_config.py \
  --input my_config.ocio \
  --output enriched_config.ocio \
  --aces-version 2.0 \
  --config-type reference

# Enrich an ACES 1.x studio config
python3 scripts/enrich_ocio_config.py \
  --input studio.ocio \
  --output enriched_studio.ocio \
  --aces-version 1.x \
  --config-type studio

# Optional: use a local transforms.json instead of downloading
#   --transforms /path/to/transforms.json
# Optional: custom download URL
#   --transforms-url https://raw.githubusercontent.com/aces-aswf/aces/main/transforms.json
```

### What It Does

1. **Detects OCIO version** - Checks if your config is v2.4 or v2.5
2. **Upgrades if needed** - Migrates v2.4 configs to v2.5 format
3. **Maps ACES transforms** - Correlates color spaces with ACES transform IDs
4. **Enriches transforms** - Adds equivalent and inverse transform IDs
5. **Adds missing color spaces** - Merges in color spaces from repository

## Directory Structure

```
ocio_aces_enricher/
├── colorspace_repository/     # Repository of 69 reference color spaces
│   ├── aces_1.x/
│   │   └── reference/        # 33 ACES 1.x reference color spaces
│   └── aces_2.0/
│       └── reference/        # 36 ACES 2.0 reference color spaces
├── scripts/
│   ├── enrich_ocio_config.py # Main enrichment tool (all-in-one)
│   ├── extract_colorspaces.py # Extract color spaces to repository
│   └── compare_configs.py    # Compare configs to find missing spaces
└── README.md
```

## Components

### 1. enrich_ocio_config.py (Main Tool)

The primary tool for enriching OCIO configs.

**What it does:**
- Detects OCIO version (v2.4 or v2.5)
- Upgrades to v2.5 if necessary
- Maps ACES transform IDs from transforms.json
- Enriches with equivalent/inverse transform IDs
- Adds missing color spaces from repository

**Arguments:**
- `-i, --input`: Input OCIO config file (.ocio)
- `-o, --output`: Output enriched OCIO config file (.ocio)
- `--aces-version`: Target ACES version (1.x, 1.3, or 2.0)
- `--config-type`: Config type (studio or reference)
- `--transforms`: Optional path to ACES transforms.json (default: download from [aces-aswf/aces](https://github.com/aces-aswf/aces) `main` on each run)
- `--transforms-url`: URL for that download when `--transforms` is omitted
- `--skip-upgrade`: Skip OCIO v2.4 to v2.5 upgrade (optional)
- `--work-dir`: Working directory for intermediate files (optional)

**Example:**
```bash
python3 scripts/enrich_ocio_config.py \
  -i INPUT_OCIO/studio-config-v2.4.ocio \
  -o OUTPUT/enriched_studio.ocio \
  --aces-version 2.0 \
  --config-type studio
```

### 2. extract_colorspaces.py

Utility to extract individual color spaces from existing configs into the repository.

**What it does:**
- Reads an OCIO config
- Extracts each color space into individual .ocio files
- Organizes by ACES version and config type
- Skips color spaces without ACES transform IDs

**Arguments:**
- `-i, --input`: Input OCIO config file (.ocio)
- `-o, --output`: Output directory for repository
- `--aces-version`: ACES version category (aces_1.x or aces_2.0)
- `--config-type`: Config type (studio or reference)

**Example:**
```bash
python3 scripts/extract_colorspaces.py \
  -i reference-config-aces-v2.0.ocio \
  --aces-version aces_2.0 \
  --config-type reference \
  -o colorspace_repository
```

### 3. compare_configs.py

Analyzes two configs to identify missing color spaces and transform IDs.

**What it does:**
- Compares source config against reference
- Lists all missing transform IDs
- Shows which color spaces contain missing transforms
- Can save analysis to file

**Arguments:**
- `-s, --source`: Source OCIO config to analyze
- `-r, --reference`: Reference OCIO config to compare against
- `-o, --output`: Output file for analysis (optional)

**Example:**
```bash
python3 scripts/compare_configs.py \
  --source my_config.ocio \
  --reference reference_config.ocio \
  --output analysis.txt
```

## Color Space Repository

The repository contains **69 individual color space files** organized by ACES version and config type.

### ACES 1.x Reference (33 color spaces)
Includes:
- Display transforms (Rec.1886 Rec.2020, P3-D60, P3-DCI)
- ACES working spaces (ACEScc, ACEScct, ACESproxy, ACEScg)
- Camera IDTs (ARRI LogC3/4, Sony S-Log, Canon C-Log, RED, BMD, etc.)
- Utility looks (ACES 1.0 to 0.1/0.2/0.7 emulation)

### ACES 2.0 Reference (36 color spaces)
Includes all ACES 1.x spaces plus:
- Additional display transforms (sRGB, Rec.2100-HLG, Rec.2100-PQ, ST2084)
- ACES2065-1 color space
- D-Log D-Gamut (DJI)
- Updated versions of all camera IDTs

### How It Works

Each color space is stored as a minimal OCIO config file containing:
- The color space definition
- All associated transforms
- ACES transform IDs in `interchange.amf_transform_ids`
- Original description and metadata

When enriching a config, the tool:
1. Scans the repository for the appropriate ACES version and config type
2. Compares transform IDs between your config and repository
3. Adds any missing color spaces to your config
4. Avoids duplicates and name conflicts

## Transform Filtering

The enrichment process includes intelligent filtering:

### Filtered Out:
- **Utility transforms**: ACESutil, ACESlib, Lib (142 transforms)
- **ARRI raw variants**: All v2-raw and v3-raw IDTs (5,304 transforms)
- **ARRI EI/ISO/CCT variants**: Except 14 specific v3-logC EI values
  - Kept: EI 160, 200, 250, 320, 400, 500, 640, 800, 1000, 1280, 1600, 2000, 2560, 3200

### Kept:
- All transform types: IDT, ODT, CSC, ACEScsc, LMT, Look, RRT, RRTODT, Output, InvOutput, etc.
- All non-ARRI camera IDTs (Sony, Canon, RED, Panasonic, BMD, DJI, Apple)
- Transform IDs with `previousEquivalentTransformIds` and `inverseTransformId`

## Requirements

- Python 3.7+
- PyOpenColorIO (installed via pip)
- Network access on first enrichment run (to download the official `transforms.json`), unless you pass `--transforms` with a local file

## Installation

```bash
# Install PyOpenColorIO
pip3 install PyOpenColorIO

# Verify installation
python3 -c "import PyOpenColorIO as OCIO; print(OCIO.__version__)"
```

## Workflow Example

### Step 1: Generate a base OCIO config
```bash
# Use ocioarchive or programmatically generate a config
```

### Step 2: Enrich the config
```bash
python3 scripts/enrich_ocio_config.py \
  -i base_config.ocio \
  -o enriched_config.ocio \
  --aces-version 2.0 \
  --config-type reference
```

### Step 3: Verify results
```bash
python3 scripts/compare_configs.py \
  --source enriched_config.ocio \
  --reference reference-config-aces-v2.0.ocio
```

## Advanced Usage

### Skip OCIO Upgrade
If your config is already v2.5:
```bash
python3 scripts/enrich_ocio_config.py \
  -i config.ocio -o enriched.ocio \
  --aces-version 2.0 --config-type reference \
  --skip-upgrade
```

### Specify Working Directory
Keep intermediate files for debugging:
```bash
python3 scripts/enrich_ocio_config.py \
  -i config.ocio -o enriched.ocio \
  --aces-version 2.0 --config-type reference \
  --work-dir ./work
```

### Populate Your Own Repository
Extract color spaces from your own configs:
```bash
python3 scripts/extract_colorspaces.py \
  -i my_custom_config.ocio \
  --aces-version aces_2.0 \
  --config-type studio \
  -o colorspace_repository
```

## Technical Details

### OCIO v2.4 to v2.5 Migration

The upgrade process:
1. Parses description field for `ACEStransformID: <id>`
2. Extracts all transform IDs
3. Sets `interchange.amf_transform_ids` attribute (newline-separated)
4. Cleans up description field
5. Updates OCIO version to 2.5

### Transform ID Enrichment

For each color space:
1. Find all existing transform IDs
2. Look up each ID in transforms.json
3. Extract `previousEquivalentTransformIds` array
4. Extract `inverseTransformId` if available
5. Add all related IDs to `interchange.amf_transform_ids`

This ensures maximum compatibility across ACES versions.

## Coverage Statistics

Based on the reference configs:

**ACES 2.0**:
- 240 unique transform IDs
- 154 of 159 matches (96.9% coverage)

**ACES 1.x**:
- 261 unique transform IDs
- 326 of 584 matches (55.8% coverage)

**Combined Uber Config**:
- 352 unique transform IDs
- 554 of 801 matches (69.2% coverage)

## License

This tool is built on top of OpenColorIO and works with ACES transforms.
Consult the ACES and OpenColorIO licenses for usage restrictions.

## Credits

Built to solve the problem of enriching programmatically-generated OCIO configs with complete ACES transform coverage.
