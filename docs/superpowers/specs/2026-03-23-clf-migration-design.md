# CLF Migration & Family Enrichment — Design Spec

**Date:** 2026-03-23
**Status:** Reviewed (2 review passes)
**Scope:** One-time update to all vendor family packages in `ocio_vendor_extensions/families/`

## 1. Objective

Replace vendor-provided display LUTs (`.cube`, `.cub`) with pre-baked CLF files that go directly from ACES2065-1 to display output, eliminating the runtime `ColorSpaceTransform` hop through an intermediate color space. Additionally, convert FilmLight's LUT-based intermediate color spaces to analytical transforms, and enrich all families with commonly useful intermediate color spaces.

### Motivations

- **Portability:** Each display view becomes a single `FileTransform` pointing to one self-contained `.clf`. No intermediate color space resolution needed at runtime.
- **FilmLight cleanup:** T-Log has a known analytical formula; E-Gamut 2 has known primaries. No reason to carry LUT files for the intermediate.
- **Intermediate enrichment:** Add commonly useful camera/linear intermediates (LogC4, linear gamut variants, etc.) that the `extend` tool will inject only if the base config doesn't already have them.

### Non-goals

- No changes to the `extend` tool code itself (orchestrator, merger, wiring, loader).
- No new display views or families.
- No changes to `family.yaml` display mappings (same views, same display targets).

## 2. CLF Pre-Baking (External)

CLFs are baked externally using `aces-clf-baker` from the sibling repo at `IDT_Maker/ACES_CLF_BAKER_EXTENDED`. This tool wraps a vendor LUT in an ACES2065-1-bounded CLF by prepending a gamut matrix + transfer function encode before the 3D LUT.

### 2.1 Baking Command Pattern

For a vendor LUT that expects `{VendorLog} {VendorGamut}` input:

```bash
aces-clf-baker <input.cube> <output.clf> \
  --in-tf "<VendorTransferFunction>" \
  --in-gamut "<VendorGamut>"
```

No `--out-tf` / `--out-gamut` needed — display-referred output stays as-is (no output shaper).

### 2.2 CLF Naming Convention

Pattern: `{Vendor}_ACES_to_{Display}_{details}.clf`

- Preserves vendor origin and distinguishing details from the original filename
- Clarifies the ACES-to-display direction
- For inverse CLFs (FilmLight only), append `_inv` suffix: `{Vendor}_ACES_to_{Display}_{details}_inv.clf`
- Examples:
  - `ARRI_LogC2Video_709_davinci3d_33.cube` → `ARRI_ACES_to_Rec709_davinci3d_33.clf`
  - `DVI-DVWG_to_Rec709-2_4y_x65.cube` → `DaVinci_ACES_to_Rec709_2_4y.clf`
  - `FilmLight_TLog_EGamut2_2_ACES_709.cub` → `FilmLight_ACES_to_Rec709.clf`
  - `SL3SG3tos709.cube` → `Sony_ACES_to_Rec709.clf`
  - `RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_2_Medium size_33 v1.13.cube` → `RED-IPP2_ACES_to_Rec709_MC_R2_Medium.clf`

### 2.3 Per-Family Baking Parameters

| Family | `--in-tf` | `--in-gamut` | LUT Count |
|--------|-----------|--------------|-----------|
| ARRI | `LogC3` (EI800) | `ARRI Wide Gamut 3` | 6 |
| DaVinci | `DaVinci Intermediate Log` | `DaVinci Wide Gamut` | 15 |
| FilmLight | `T-Log` | `E-Gamut 2` | 30 forward + 30 inverse = 60 |
| RED IPP2 | `Log3G10` | `REDWideGamutRGB` | 8 |
| Sony | `SLog3` | `Venice S-Gamut3` | 2 |

**Note on naming:** The `--in-tf` and `--in-gamut` values are `colour-science` / `aces-clf-baker` names, which may differ from the OCIO color space names in the config (e.g., baker `DaVinci Intermediate Log` + `DaVinci Wide Gamut` corresponds to OCIO's `DaVinci Intermediate WideGamut`). The baking guide (§2.4) will document the exact mapping.

**Total CLFs to bake:** 91 (6 ARRI + 15 DaVinci + 60 FilmLight [30 fwd + 30 inv] + 8 RED + 2 Sony). The 30 FilmLight inverse CLFs can be omitted if inverse display views are dropped.

### 2.4 Reproducibility

All baking commands are recorded in:
- **`docs/clf-baking-guide.md`** — Human-readable table mapping every original LUT → CLF with exact command
- **`scripts/bake_vendor_clfs.sh`** — Re-runnable shell script that bakes all CLFs in one go

## 3. Snippet Transform Changes

### 3.1 Display-Referred Color Spaces (All Families)

**Before** (current — GroupTransform with ColorSpaceTransform + FileTransform):

```yaml
from_scene_reference: !<GroupTransform>
  children:
    - !<ColorSpaceTransform> {src: ACES2065-1, dst: ARRI LogC3 (EI800)}
    - !<FileTransform> {src: ARRI_LogC2Video_709_davinci3d_33.cube, interpolation: best}
```

**After** (CLF — single FileTransform):

```yaml
from_scene_reference: !<FileTransform> {src: ARRI_ACES_to_Rec709_davinci3d_33.clf, interpolation: best}
```

For color spaces that also define `to_scene_reference` (inverse path, currently only FilmLight display spaces), the inverse CLF replaces the inverse chain. Inverse CLF names follow the same §2.2 convention with `_inv` suffix — one inverse CLF per forward display LUT:

```yaml
# FilmLight example (forward + inverse pair)
from_scene_reference: !<FileTransform> {src: FilmLight_ACES_to_Rec709.clf, interpolation: best}
to_scene_reference: !<FileTransform> {src: FilmLight_ACES_to_Rec709_inv.clf, interpolation: best}
```

### 3.2 FilmLight Intermediate: T-Log : E-Gamut 2 (Analytical)

**Before** (LUT-based):

```yaml
- !<ColorSpace>
    name: "FilmLight : T-Log : E-Gamut 2"
    family: FilmLight/scene_referred
    to_scene_reference: !<GroupTransform>
      children:
        - !<FileTransform> {src: FilmLight_TLog_EGamut2_2_FilmLight_Linear_EGamut2.cub, interpolation: linear}
        - !<FileTransform> {src: FilmLight_TLog_EGamut2_2_FilmLight_Linear_EGamut2.spimtx, interpolation: linear}
        - !<FileTransform> {src: ACES_lin_2_FilmLight_Linear_EGamut2.spimtx, interpolation: linear, direction: inverse}
```

**After** (analytical):

The T-Log transfer function is **piecewise**: `ln`-based for L >= 0, linear for L < 0. OCIO's `LogCameraTransform` maps exactly to this formula with the following parameter derivation:

- T-Log: `V = A + B * ln(L + C)` for L >= 0; `V = G * L + o` for L < 0
- LogCameraTransform: `V = log_side_slope * log_base(lin_side_slope * x + lin_side_offset) + log_side_offset` for x > lin_side_break; `V = linear_slope * x + linear_offset` for x <= lin_side_break

Mapping: `base=e, log_side_slope=B, log_side_offset=A, lin_side_slope=1.0, lin_side_offset=C, lin_side_break=0.0, linear_slope=G`. Continuity at L=0 is exact (A + B*ln(C) = o within floating-point noise ~1e-17).

**Verified** (`scripts/test_tlog_fit.py`): encode error 9.15e-07, decode error 3.12e-07 in code value space. OCIO round-trip error of ~1.2e-04 in scene-linear space is expected float32 precision at large values (T-Log decodes to ~128 at V=1.0), not a formula error.

```yaml
- !<ColorSpace>
    name: "FilmLight : T-Log : E-Gamut 2"
    family: FilmLight/scene_referred
    equalitygroup: ""
    bitdepth: 32f
    description: "FilmLight : T-Log : E-Gamut 2"
    isdata: false
    allocation: uniform
    allocationvars: [0, 1]
    to_scene_reference: !<GroupTransform>
      name: FilmLight T-Log E-Gamut 2 to ACES2065-1
      children:
        - !<LogCameraTransform> {base: 2.718281828459045, log_side_slope: 0.09232902596577353, log_side_offset: 0.5520126568606655, lin_side_slope: 1.0, lin_side_offset: 0.0057048244042473785, lin_side_break: 0.0, linear_slope: 16.184376489665897, direction: inverse}
        - !<MatrixTransform> {matrix: [0.786791192063810, 0.147306103551601, 0.065903978756014, 0, 0.002154493913007, 1.062854395534887, -0.065008720071672, 0, -0.114752994896219, -0.081043745103318, 1.195796424658541, 0, 0, 0, 0, 1]}
```

**T-Log decode step:** `to_scene_reference` needs T-Log **decode** (code value → scene-linear), then E-Gamut 2 linear → ACES2065-1 matrix. `from_scene_reference` needs the inverse: ACES2065-1 → E-Gamut 2 linear matrix, then T-Log **encode** (scene-linear → code value).

**T-Log formula** (from FilmLight specification, in `colour-science` since v0.3.12):

Constants derived from `w=128`, `g=16`, `o=0.075`:
- `b = 1 / (0.7107 + 1.2359 * log(w * g))`
- `gs = g / (1 - o)`
- `C = b / gs`
- `a = 1 - b * log(w + C)`
- `y0 = a + b * log(C)`
- `s = (1 - o) / (1 - y0)`
- `A = 1 + (a - 1) * s`
- `B = b * s`
- `G = gs * s`

Encoding (scene-linear L → code value V): `V = A + B * ln(L + C)` for L >= 0; `V = G * L + o` for L < 0.
Decoding (code value V → scene-linear L): `L = exp((V - A) / B) - C` for V >= o; `L = (V - o) / G` for V < o.

**Cross-tool consistency:** The `aces-clf-baker` tool uses `colour-science`'s T-Log implementation for the CLF input shaper. The `LogCameraTransform` parameters are derived from the same T-Log constants (w=128, g=16, o=0.075) and verified against `colour-science` to < 1e-6 in code value space.

### 3.3 FilmLight Intermediate: Linear : E-Gamut 2

**Before** (single spimtx file):

```yaml
from_scene_reference: !<FileTransform> {src: ACES_lin_2_FilmLight_Linear_EGamut2.spimtx, interpolation: linear}
```

**After** (analytical matrix):

```yaml
from_scene_reference: !<MatrixTransform> {matrix: [1.25992, -0.180662, -0.0792596, 0, 0.00486135, 0.944082, 0.0510565, 0, 0.121236, 0.0466471, 0.832117, 0, 0, 0, 0, 1]}
```

The matrix values are from the existing `ACES_lin_2_FilmLight_Linear_EGamut2.spimtx` file. This is the ACES2065-1 → E-Gamut 2 linear direction, used in `from_scene_reference`. The `to_scene_reference` (E-Gamut 2 linear → ACES2065-1) uses the same `MatrixTransform` with `direction: inverse`, or we provide the explicit inverse matrix from `colour-science` E-Gamut 2 primaries.

## 4. New Intermediates Per Family

These are added to each family's `colorspaces.ocio` snippet and `family.yaml` `intermediates` list. Definitions are copied verbatim from the ACES v2.0 studio config:

**Reference file:** `INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio` (ACES v2.0, OCIO v2.5, studio all-views v4.0.0).

The `extend` tool skips them if the base config already has them (exact name match).

### 4.1 ARRI

| New Intermediate | Transform | Reference (color space name in studio config) |
|-----------------|-----------|-----------------------------------------------|
| ARRI LogC4 | `LogCameraTransform` + `MatrixTransform` | `ARRI LogC4` |
| Linear ARRI Wide Gamut 3 | `MatrixTransform` | `Linear ARRI Wide Gamut 3` |
| Linear ARRI Wide Gamut 4 | `MatrixTransform` | `Linear ARRI Wide Gamut 4` |

Existing (unchanged): `ARRI LogC3 (EI800)`

### 4.2 RED IPP2

| New Intermediate | Transform | Reference |
|-----------------|-----------|-----------|
| Linear REDWideGamutRGB | `MatrixTransform` | `Linear REDWideGamutRGB` |

Existing (unchanged): `Log3G10 REDWideGamutRGB`

### 4.3 Sony

| New Intermediate | Transform | Reference |
|-----------------|-----------|-----------|
| S-Log3 S-Gamut3 | `LogCameraTransform` + `MatrixTransform` | `S-Log3 S-Gamut3` |
| S-Log3 S-Gamut3.Cine | `LogCameraTransform` + `MatrixTransform` | `S-Log3 S-Gamut3.Cine` |
| S-Log3 Venice S-Gamut3.Cine | `LogCameraTransform` + `MatrixTransform` | `S-Log3 Venice S-Gamut3.Cine` |
| Linear S-Gamut3 | `MatrixTransform` | `Linear S-Gamut3` |
| Linear Venice S-Gamut3 | `MatrixTransform` | `Linear Venice S-Gamut3` |

Existing (unchanged): `S-Log3 Venice S-Gamut3`

### 4.4 DaVinci

| New Intermediate | Transform | Reference |
|-----------------|-----------|-----------|
| Linear DaVinci WideGamut | `MatrixTransform` | `Linear DaVinci WideGamut` |

Existing (unchanged): `DaVinci Intermediate WideGamut`

### 4.5 FilmLight

No new intermediates. Existing intermediates (`T-Log : E-Gamut 2`, `Linear : E-Gamut 2`) are converted from LUT-based to analytical (see Section 3.2–3.3).

## 5. File Changes

### 5.1 Per Family

For each family (`arri`, `davinci`, `filmlight`, `red_ipp2`, `sony`):

| Action | Files |
|--------|-------|
| **Rewrite** | `colorspaces.ocio` — display views use single `FileTransform` to CLF; new intermediates added |
| **Update** | `family.yaml` — `intermediates` list updated with new intermediate names |
| **Add** | `luts/*.clf` — pre-baked CLF files |
| **Remove** | `luts/*.cube` / `luts/*.cub` — old vendor LUTs replaced by CLFs |

**FilmLight additionally removes:**
- `luts/FilmLight_TLog_EGamut2_2_FilmLight_Linear_EGamut2.cub` (intermediate now analytical)
- `luts/FilmLight_TLog_EGamut2_2_FilmLight_Linear_EGamut2.spimtx` (near-identity matrix — verify numerically during implementation; values are `1.0, -1.06e-16, 0` / `1.73e-17, 1.0, 0` / `0, 0, 1.0` which is identity within floating-point noise)
- `luts/ACES_lin_2_FilmLight_Linear_EGamut2.spimtx` (replaced by inline MatrixTransform)

### 5.2 LUT Inventory Summary

| Family | Old LUTs Removed | New CLFs Added |
|--------|-----------------|----------------|
| ARRI | 6 `.cube` | 6 `.clf` |
| DaVinci | 15 `.cube` | 15 `.clf` |
| FilmLight | 63 files (60 `.cub` display + 1 `.cub` + 2 `.spimtx` intermediate) | 60 `.clf` (30 forward + 30 inverse) |
| RED IPP2 | 8 `.cube` | 8 `.clf` |
| Sony | 2 `.cube` | 2 `.clf` |

### 5.3 New Documentation

| File | Purpose |
|------|---------|
| `docs/clf-baking-guide.md` | Reproducibility guide: per-LUT baking commands, naming convention, verification steps |
| `scripts/bake_vendor_clfs.sh` | Re-runnable shell script to bake all CLFs |
| `scripts/verify_clf_migration.py` | Verification script comparing old chain vs new CLF processor output |

### 5.4 Unchanged Files

- `ocio_vendor_extensions/extend_config.py`
- `ocio_vendor_extensions/config_merger.py`
- `ocio_vendor_extensions/display_wiring.py`
- `ocio_vendor_extensions/family_loader.py`
- `ocio_vendor_extensions/dependency_resolver.py`

## 6. Verification Strategy

### 6.1 Per-CLF Accuracy Test

For each original LUT, compare OCIO processor output of the old chain (ColorSpaceTransform + FileTransform) vs the new CLF (single FileTransform) on a set of test patches (24-patch ColorChecker in ACES2065-1).

**Tolerance:** Max per-channel error < 0.001 in normalized code values (0–1 range for SDR, 0–1 PQ-encoded for HDR). These should be mathematically near-identical since the CLF bakes the same math.

### 6.2 FilmLight Analytical Verification

Compare the chosen analytical T-Log representation (whichever of the three §3.2 strategies is selected) + `MatrixTransform` against the original `.cub` + `.spimtx` chain. The original 1D LUT was 1024 entries, so small interpolation differences are expected.

**Tolerance:** Max component error < 1e-4.

### 6.3 End-to-End Extend Test

Run `extend` with updated families against the ACES v2.0 studio config:
1. `config.validate()` passes
2. Display views resolve correctly (spot-check processor creation)
3. `--dry-run` output matches expectations

### 6.4 OCIO 2.1 Downgrade Test

Run the existing `lut-build` downgrade on the extended config. CLF `FileTransform`s are supported in OCIO 2.1, so no issues expected. Verify the downgraded config validates and display views still resolve.

### 6.5 Verification Script

`scripts/verify_clf_migration.py`:
- Loads old family snippets from a backup directory (`ocio_vendor_extensions/families_pre_clf/` — a snapshot taken before the migration)
- Loads new CLF-based snippets
- Compares processor outputs for each display color space
- Reports pass/fail per color space with max error
- Also serves as future re-verification tool after re-baking

**Pre-migration backup:** Before modifying any family, copy the entire `families/` directory to `families_pre_clf/`. This provides a stable reference for verification without depending on git history.

## 7. OCIO 2.1 Downgrade Compatibility

The CLF-based color spaces remain compatible with the OCIO 2.1 downgrade in `generate_lut_based_config.py`:

- Display color spaces use only `FileTransform` (CLF) — no `BuiltinTransform` or v2.2+ features
- Direct view wiring (no `view_transform` factoring)
- Intermediate color spaces use `LogCameraTransform` + `MatrixTransform` (ARRI, RED, Sony, DaVinci, and FilmLight if `LogCameraTransform` fit succeeds) or `FileTransform` (CLF) + `MatrixTransform` (FilmLight fallback) — all supported in OCIO 2.1. Re-run the downgrade after any changes to `generate_lut_based_config.py` that affect CLF handling.
- Linear intermediates use only `MatrixTransform` — universally supported

## 8. Known Limitations

- **CLF file size:** CLFs embedding a 33^3 3D LUT are larger than the equivalent `.cube` file due to XML overhead. Not a practical concern for config distribution.
- **FilmLight T-Log precision:** The analytical formula may differ from the original 1024-entry 1D LUT by up to ~1e-4 due to LUT interpolation. This is well below perceptual threshold.
- **No inverse CLFs for non-FilmLight families:** ARRI, DaVinci, RED, Sony display spaces don't currently define `to_scene_reference`. This is unchanged — inverse display transforms are not needed for normal viewing workflows.
