# OCIO ACES Enricher - Quick Start Guide

## Installation

```bash
# 1. Install PyOpenColorIO
pip3 install PyOpenColorIO

# 2. Verify installation
python3 -c "import PyOpenColorIO as OCIO; print(OCIO.__version__)"
# Should print: 2.5.0
```

## Basic Usage

### Enrich a Config

```bash
# Navigate to project root
cd /path/to/OCIO_ACES_MERGER_AND_PARSER

# Enrich an OCIO config
python3 ocio_aces_enricher/scripts/enrich_ocio_config.py \
  --input my_config.ocio \
  --output enriched_config.ocio \
  --aces-version 2.0 \
  --config-type reference
```

### Parameters Explained

- `--input`: Your input OCIO config (can be v2.4 or v2.5)
- `--output`: Where to save the enriched config
- `--aces-version`: Target ACES version
  - `1.x` or `1.3` for ACES 1.x configs
  - `2.0` for ACES 2.0 configs
- `--config-type`: Config type
  - `reference` for reference configs
  - `studio` for studio configs
- `--transforms`: Optional path to ACES transforms.json (if omitted, downloaded from the official repo each run)
- `--transforms-url`: Override download URL (default: raw `transforms.json` on aces-aswf/aces `main`)

### What Happens

1. ✅ **Detects version**: Checks if config is OCIO v2.4 or v2.5
2. ✅ **Upgrades if needed**: Migrates v2.4 to v2.5 format
3. ✅ **Maps transforms**: Correlates color spaces with ACES transform IDs
4. ✅ **Enriches IDs**: Adds equivalent/inverse transform IDs
5. ✅ **Adds missing**: Merges in missing color spaces from repository

## Examples

### Example 1: ACES 2.0 Reference Config

```bash
python3 ocio_aces_enricher/scripts/enrich_ocio_config.py \
  -i INPUT_OCIO/REFERENCE/reference-config-v4.0.0_aces-v2.0_ocio-v2.5.ocio \
  -o OUTPUT/enriched_reference_v2.0.ocio \
  --aces-version 2.0 \
  --config-type reference
```

### Example 2: ACES 1.3 Studio Config (with upgrade)

```bash
python3 ocio_aces_enricher/scripts/enrich_ocio_config.py \
  -i INPUT_OCIO/STUDIO/studio-config-v2.2.0_aces-v1.3_ocio-v2.4.ocio \
  -o OUTPUT/enriched_studio_v1.3.ocio \
  --aces-version 1.3 \
  --config-type reference
```

### Example 3: Keep Intermediate Files

```bash
# Useful for debugging
python3 ocio_aces_enricher/scripts/enrich_ocio_config.py \
  -i my_config.ocio \
  -o enriched.ocio \
  --aces-version 2.0 \
  --config-type reference \
  --work-dir ./debug_output
```

### Example 4: Skip Upgrade (already v2.5)

```bash
python3 ocio_aces_enricher/scripts/enrich_ocio_config.py \
  -i my_v25_config.ocio \
  -o enriched.ocio \
  --aces-version 2.0 \
  --config-type reference \
  --skip-upgrade
```

## Verify Results

### Compare Before and After

```bash
python3 ocio_aces_enricher/scripts/compare_configs.py \
  --source enriched_config.ocio \
  --reference reference-config-aces-v2.0.ocio
```

### Check Config Stats

```python
python3 -c "
import PyOpenColorIO as OCIO
config = OCIO.Config.CreateFromFile('enriched_config.ocio')
print(f'OCIO Version: {config.getMajorVersion()}.{config.getMinorVersion()}')
print(f'Color Spaces: {len(list(config.getColorSpaces()))}')
"
```

## Advanced Usage

### Extract Custom Color Spaces to Repository

```bash
# Add your own color spaces to the repository
python3 ocio_aces_enricher/scripts/extract_colorspaces.py \
  -i my_custom_config.ocio \
  --aces-version aces_2.0 \
  --config-type studio \
  -o ocio_aces_enricher/colorspace_repository
```

### Analyze a Config

```bash
# Save analysis to file
python3 ocio_aces_enricher/scripts/compare_configs.py \
  --source my_config.ocio \
  --reference reference_config.ocio \
  --output analysis_report.txt
```

## Expected Results

### Typical Enrichment

**Before:**
- OCIO version: 2.4
- Color spaces: ~50
- Transform IDs: ~90 (in description field)

**After:**
- OCIO version: 2.5
- Color spaces: ~65 (+10-15 added)
- Transform IDs: ~170 (in interchange.amf_transform_ids)

### Color Spaces Typically Added

From the repository, you might gain:
- ACESproxy
- Additional camera IDTs (Canon, Sony variants)
- Additional display transforms
- Utility looks (ACES version emulation)
- Regional variants (BT2020, daylight/tungsten)

## Common Issues

### Issue: "Module 'PyOpenColorIO' not found"

**Solution:**
```bash
pip3 install PyOpenColorIO
```

### Issue: "Repository not found"

**Solution:** Make sure you're running from the project root:
```bash
cd /path/to/OCIO_ACES_MERGER_AND_PARSER
python3 ocio_aces_enricher/scripts/enrich_ocio_config.py ...
```

### Issue: "transforms.json not found"

**Solution:** By default the tool downloads the official file; this error only applies if you passed `--transforms` with a bad path. Use a valid path or omit `--transforms`:
```bash
--transforms /full/path/to/transforms.json
```

### Issue: Name conflicts

Some color spaces may have conflicting aliases. These will be skipped with a warning:
```
! Name conflict: ColorSpace (exists with different transforms)
```

This is expected behavior and protects your config integrity.

## Performance

- Small configs (<100 color spaces): ~10-20 seconds
- Medium configs (100-200 color spaces): ~20-40 seconds
- Large configs (>200 color spaces): ~40-60 seconds

Most time is spent in the ACES mapping phase.

## Output Files

When you run enrichment, you get:

1. **Main output**: `enriched_config.ocio` - Your enriched config
2. **Working directory** (if specified with `--work-dir`):
   - `upgraded_v2.5.ocio` - Intermediate upgraded config
   - `enriched/config_updated.ocio` - After ACES mapping
   - `enriched/ocio_transform_matches.csv` - Match report
   - `enriched/aces_ocio_mapping_report.csv` - Full mapping

## Help

```bash
# Get help on any script
python3 ocio_aces_enricher/scripts/enrich_ocio_config.py --help
python3 ocio_aces_enricher/scripts/extract_colorspaces.py --help
python3 ocio_aces_enricher/scripts/compare_configs.py --help
```

## Next Steps

1. ✅ Enrich your config
2. ✅ Verify results with compare_configs.py
3. ✅ Test in your application
4. ✅ Add custom color spaces to repository if needed
5. ✅ Share enriched configs with your team

## Full Documentation

See `README.md` for comprehensive documentation including:
- Detailed feature descriptions
- Technical details on filtering
- Coverage statistics
- Repository structure
- Transform enrichment logic

## Package Location

All files are in: `ocio_aces_enricher/`

The package is self-contained and can be:
- Used from project root
- Copied to another location
- Shared with others

Just ensure `transforms.json` is accessible.
