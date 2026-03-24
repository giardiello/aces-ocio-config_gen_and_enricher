# scripts/ — Build & Verification Helpers

Utility scripts for CLF baking, vendor family construction, and migration verification.

## Scripts

### `bake_vendor_clfs.sh`

Bakes vendor LUTs into self-contained CLF files using `aces-clf-baker`. Each CLF wraps the original vendor 3D LUT with a gamut matrix and transfer function decode shaper so the input is ACES2065-1.

```bash
# Bake all families (requires aces-clf-baker on PATH)
./scripts/bake_vendor_clfs.sh

# Or set a custom path
ACES_CLF_BAKER=/path/to/aces-clf-baker ./scripts/bake_vendor_clfs.sh
```

**Inputs:** `ocio_vendor_extensions/families_pre_clf/<family>/luts/` (original vendor LUTs)
**Outputs:** `ocio_vendor_extensions/families/<family>/luts/*.clf`

See [`docs/clf-baking-guide.md`](../docs/clf-baking-guide.md) for the exact commands and parameters used for each vendor.

### `verify_clf_migration.py`

Verifies that the CLF migration produced correct results by comparing the pre-CLF and post-CLF transform chains numerically.

```bash
python scripts/verify_clf_migration.py
```

### `build_vendor_display_families.py`

Development script used to initially construct the vendor family packages from source OCIO configs and LUT files. Not needed for normal operation.

### `test_tlog_fit.py`

Tests the T-Log transfer function fitting used for FilmLight intermediate color spaces.

## External Tool: `aces-clf-baker`

The CLF baking script requires `aces-clf-baker`, a CLI tool from the `IDT_Maker/ACES_CLF_BAKER_EXTENDED` sibling repository. It is not included in this project.

The baker wraps a vendor 3D LUT with:
- A gamut matrix (vendor gamut → ACES AP0, with chromatic adaptation)
- A transfer function decode shaper (vendor log → linear)

So the resulting CLF accepts ACES2065-1 input directly.
