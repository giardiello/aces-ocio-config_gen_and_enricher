# ocio_vendor_extensions — Vendor Display Views

Adds non-ACES vendor-specific display views to OCIO configs. Each vendor is packaged as a "family" containing a manifest, color space definitions, and pre-baked CLF look-up tables.

## Available Families

| Family | Vendor | Display Views |
|--------|--------|--------------|
| `arri` | ARRI | Rec.709, Rec.709 Classic, P3-D65, Rec.2020, Rec.2100 HLG, Rec.2100 PQ |
| `davinci` | Blackmagic DaVinci | Rec.709, sRGB, P3-D65, Rec.2020, HLG, PQ (multiple nit levels) |
| `filmlight` | FilmLight | Rec.709, sRGB, P3-D60, P3-D65, P3-DCI, DCI-XYZ, Rec.2020, PQ/HLG (multiple nit levels) |
| `red_ipp2` | RED IPP2 | Rec.709, Rec.2020 (4 contrast grades each) |
| `sony` | Sony | Rec.709, P3-D65 |

## Usage

Via the unified CLI:

```bash
# Add all vendor families
python -m ocio_aces_tools extend -i config.ocio -o extended.ocio \
    --families all --skip-missing-displays

# Add specific families
python -m ocio_aces_tools extend -i config.ocio -o extended.ocio \
    --families arri davinci

# Preview what would change (no output written)
python -m ocio_aces_tools extend -i config.ocio --families all --dry-run

# List available families
python -m ocio_aces_tools extend --list-families
```

Or directly:

```bash
python -m ocio_vendor_extensions.extend_config -i config.ocio -o extended.ocio --families all
```

### Missing Display Policy

When a family manifest references a display that doesn't exist in the target config (e.g., "Rec.2100 PQ" in a config that only has "sRGB" and "Rec.709"), the tool resolves the policy in this order:

1. `--dry-run` → always skips missing displays
2. `--create-missing-displays` or `--skip-missing-displays` → explicit flag
3. `OCIO_ACES_EXTEND_MISSING_DISPLAYS` environment variable (`create` or `skip`)
4. Interactive prompt

### Supported OCIO Versions

The tool preserves the declared OCIO version of the input config. Works with OCIO 2.3, 2.4, and 2.5.

## Family Package Structure

Each family lives under `families/<name>/` and contains:

```
families/arri/
├── family.yaml          # Pydantic-validated manifest
├── colorspaces.ocio     # OCIO config snippet with vendor color spaces
└── luts/                # Pre-baked CLF files (ACES2065-1 → display)
    ├── ARRI_ACES_to_Rec709_davinci3d_33.clf
    ├── ARRI_ACES_to_P3D65_davinci3d_33.clf
    └── ...
```

### `family.yaml` Manifest

Defines display mappings, intermediates, and dependencies. Validated with Pydantic.

```yaml
name: arri
label: "ARRI ALF-4"
description: "ARRI Look File 4 display transforms"

displays:
  sRGB:
    - view: "ARRI ALF-4 (Rec.709)"
      colorspace: "ARRI ALF-4 - Rec.709"
  Rec.1886 Rec.709:
    - view: "ARRI ALF-4 (Rec.709)"
      colorspace: "ARRI ALF-4 - Rec.709"

intermediates: []
dependencies: []
```

### `colorspaces.ocio` Snippet

A minimal OCIO config containing only the vendor color spaces. Each color space uses a `FileTransform` pointing to a CLF in the `luts/` directory.

### CLF Files

Self-contained Common LUT Format files. Each CLF wraps the original vendor LUT with a gamut matrix and transfer function decode shaper so the input is ACES2065-1. See [`docs/clf-baking-guide.md`](../docs/clf-baking-guide.md) for reproducibility.

CLF files are **not tracked in git** (they total ~564MB). Regenerate them with:

```bash
scripts/bake_vendor_clfs.sh
```

This requires the `aces-clf-baker` tool and the pre-migration vendor LUTs in `families_pre_clf/`.

## Architecture

```
extend_config.py          Main orchestrator + argparse CLI
family_loader.py          YAML manifest loading + Pydantic validation + family discovery
dependency_resolver.py    Topological sort via graphlib.TopologicalSorter
config_merger.py          Color space extraction from snippets + LUT file copying
display_wiring.py         View-to-display wiring + missing display handling + view reordering
```

### Processing Flow

1. **Discover** — Scan `families/` for directories containing `family.yaml`
2. **Load** — Parse manifests and validate with Pydantic
3. **Resolve** — Topological sort to handle inter-family dependencies
4. **Merge** — Extract color spaces from each family's `colorspaces.ocio` snippet into the target config
5. **Copy LUTs** — Copy referenced CLF files into the output config's search path
6. **Wire** — Connect vendor views to displays as defined in the manifest
7. **Reorder** — Place vendor views after ACES views in each display

## Module Structure

```
ocio_vendor_extensions/
├── __init__.py
├── extend_config.py         # CLI + orchestration
├── family_loader.py         # Manifest loading + validation
├── dependency_resolver.py   # Topological dependency sort
├── config_merger.py         # Color space merging + LUT copying
├── display_wiring.py        # Display/view wiring
├── families/                # Vendor family packages
│   ├── arri/
│   ├── davinci/
│   ├── filmlight/
│   ├── red_ipp2/
│   └── sony/
└── families_pre_clf/        # Pre-migration backup (gitignored)
```
