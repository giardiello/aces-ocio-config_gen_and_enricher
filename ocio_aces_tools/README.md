# ocio_aces_tools — Unified CLI & Shared Library

This module provides two things:

1. **A unified CLI** (`python -m ocio_aces_tools`) that dispatches to all tools in the project
2. **A shared Python library** with utilities used across multiple scripts

## Unified CLI

```bash
python -m ocio_aces_tools <subcommand> [args...]
```

Each subcommand delegates to the underlying script, passing through all arguments. Use `--help` on any subcommand for its full options.

### Subcommands

| Subcommand | Delegates to | Description |
|------------|-------------|-------------|
| `upgrade` | `upgrade_ocio_v24_to_v25.py` | Upgrade OCIO v2.4 config to v2.5 format |
| `map` | `ACES_json_to_OCIOmapping.py` | Correlate ACES Transform IDs with OCIO color space names |
| `validate-amf` | `validate_amf_output_transforms.py` | Validate AMF output transform URN → Display+View mappings |
| `split` | `split_config_by_aces_version.py` | Split combined config into ACES 1.x and 2.0 configs |
| `enrich` | `ocio_aces_enricher/scripts/enrich_ocio_config.py` | Enrich config with ACES IDs and missing color spaces |
| `extend` | `ocio_vendor_extensions/extend_config.py` | Add vendor display views to config |
| `lut-build` | `generate_lut_based_config.py` | Bake ACES 2.0 BuiltinTransforms into CLF files |
| `lut-verify` | `verify_lut_vs_builtin.py` | Verify LUT-based config against BuiltIn reference |
| `repo extract` | `ocio_aces_enricher/scripts/extract_colorspaces.py` | Extract color spaces into repository |
| `repo compare` | `ocio_aces_enricher/scripts/compare_configs.py` | Compare two configs for missing color spaces |

### Examples

```bash
# Upgrade v2.4 → v2.5
python -m ocio_aces_tools upgrade input.ocio -o output.ocio

# Map ACES IDs to OCIO names, filter by version and type
python -m ocio_aces_tools map transforms.json config.ocio -v v2.0.0+2025.04.04 -t ODT -o results/

# Validate AMF output transforms
python -m ocio_aces_tools validate-amf config.ocio -o reports/

# Split combined config
python -m ocio_aces_tools split merged.ocio v1.ocio v2.ocio

# Enrich with ACES IDs (downloads transforms.json automatically)
python -m ocio_aces_tools enrich -i studio.ocio -o enriched.ocio \
    --aces-version 2.0 --config-type studio

# Enrich with local transforms.json
python -m ocio_aces_tools enrich -i studio.ocio -o enriched.ocio \
    --aces-version 2.0 --config-type studio --transforms transforms.json

# Add vendor display views
python -m ocio_aces_tools extend -i config.ocio -o extended.ocio --families all

# Bake CLF-based config
python -m ocio_aces_tools lut-build reference.ocio -o output_dir/

# Compare two configs
python -m ocio_aces_tools repo compare --source a.ocio --reference b.ocio
```

## Shared Library

Other scripts import from this module for common OCIO operations.

### `ocio_utils.get_transform_ids(ocio_item)`

Extract all ACES Transform IDs from an OCIO item (ColorSpace, Look, or ViewTransform). Handles both v2.5+ `interchange.amf_transform_ids` and v2.4 `description` field formats.

```python
from ocio_aces_tools.ocio_utils import get_transform_ids

ids = get_transform_ids(color_space)
# ['urn:ampas:aces:transformId:v2.0:CSC.Academy.ACEScct_to_ACES.a2.v1', ...]
```

### `display_view.parse_display_view_structure(config)`

Parse an OCIO config to extract all Display+View combinations and their associated output transform URNs.

```python
from ocio_aces_tools.display_view import parse_display_view_structure

structure = parse_display_view_structure(config)
# OrderedDict of display → [(view_name, view_transform, [urns]), ...]
```

### `constants.OUTPUT_TRANSFORM_TYPES`

List of ACES output transform type prefixes: `ODT`, `InvODT`, `RRTODT`, `InvRRTODT`, `Output`, `InvOutput`.

## Module Structure

```
ocio_aces_tools/
├── __init__.py        # Package init, exports __version__
├── __main__.py        # Entry point for python -m ocio_aces_tools
├── cli.py             # Subcommand dispatch logic
├── constants.py       # Shared constants (OUTPUT_TRANSFORM_TYPES)
├── display_view.py    # Display+View parsing and URN helpers
└── ocio_utils.py      # Transform ID extraction utilities
```
