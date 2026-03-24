# CLF Migration & Family Enrichment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace vendor display LUTs with pre-baked CLFs, convert FilmLight intermediates to analytical transforms, and add commonly useful intermediates to all families.

**Architecture:** One-time data update to the five vendor family packages under `ocio_vendor_extensions/families/`. No code changes to the `extend` tool itself. CLFs are pre-baked externally using `aces-clf-baker`. A baking guide and verification script are added for reproducibility.

**Tech Stack:** Python 3.9+, PyOpenColorIO, colour-science, YAML, shell scripting. External tool: `aces-clf-baker` (sibling repo).

**Prerequisites:** The workspace must be a git repo (`git init` if not already). The `colour` Python package must be installed (`pip install colour-science`).

**Spec:** `docs/superpowers/specs/2026-03-23-clf-migration-design.md`

---

## File Structure

### Files to Create

| File | Responsibility |
|------|---------------|
| `docs/clf-baking-guide.md` | Reproducibility guide: per-LUT → CLF mapping table with exact baking commands |
| `scripts/bake_vendor_clfs.sh` | Re-runnable shell script to bake all 91 CLFs |
| `scripts/verify_clf_migration.py` | Compares old chain vs new CLF processor output per display color space |

### Files to Modify (per family)

For each of `arri`, `davinci`, `filmlight`, `red_ipp2`, `sony`:

| File | Changes |
|------|---------|
| `ocio_vendor_extensions/families/{family}/colorspaces.ocio` | Rewrite display views to single `FileTransform` CLF; add new intermediates |
| `ocio_vendor_extensions/families/{family}/family.yaml` | Add new intermediate names to `intermediates:` list |
| `ocio_vendor_extensions/families/{family}/luts/` | Add `.clf` files, remove old `.cube`/`.cub`/`.spimtx` files |

### Files NOT Modified

- `ocio_vendor_extensions/extend_config.py`
- `ocio_vendor_extensions/config_merger.py`
- `ocio_vendor_extensions/display_wiring.py`
- `ocio_vendor_extensions/family_loader.py`
- `ocio_vendor_extensions/dependency_resolver.py`

---

## Task 1: Pre-Migration Backup & Baking Documentation

**Files:**
- Create: `docs/clf-baking-guide.md`
- Create: `scripts/bake_vendor_clfs.sh`
- Backup: `ocio_vendor_extensions/families/` → `ocio_vendor_extensions/families_pre_clf/`

- [ ] **Step 1: Create the pre-migration backup**

```bash
cp -r ocio_vendor_extensions/families ocio_vendor_extensions/families_pre_clf
```

Verify: `ls ocio_vendor_extensions/families_pre_clf/` shows `arri/`, `davinci/`, `filmlight/`, `red_ipp2/`, `sony/`.

- [ ] **Step 2: Write `docs/clf-baking-guide.md`**

This document records:
1. The tool used (`aces-clf-baker` from `IDT_Maker/ACES_CLF_BAKER_EXTENDED`)
2. The naming convention: `{Vendor}_ACES_to_{Display}_{details}.clf` (inverse: `_inv` suffix)
3. A complete table mapping every original LUT → CLF filename → exact baking command
4. Per-family baking parameters (`--in-tf`, `--in-gamut`)
5. Verification steps (how to re-verify after re-baking)

The table must cover all 91 CLFs. For each row:

```markdown
| Family | Original LUT | CLF Output | Command |
|--------|-------------|------------|---------|
| ARRI | ARRI_LogC2Video_709_davinci3d_33.cube | ARRI_ACES_to_Rec709_davinci3d_33.clf | `aces-clf-baker ARRI_LogC2Video_709_davinci3d_33.cube ARRI_ACES_to_Rec709_davinci3d_33.clf --in-tf LogC3 --in-gamut "ARRI Wide Gamut 3"` |
```

To build this table, read each family's current `colorspaces.ocio` and `luts/` directory to get the full list of original LUT files. Then apply the naming convention from spec §2.2 to derive CLF names.

**Important:** The `--in-tf` and `--in-gamut` values per family are:

| Family | `--in-tf` | `--in-gamut` |
|--------|-----------|--------------|
| ARRI | `LogC3` | `ARRI Wide Gamut 3` |
| DaVinci | `DaVinci Intermediate Log` | `DaVinci Wide Gamut` |
| FilmLight | `T-Log` | `E-Gamut 2` |
| RED IPP2 | `Log3G10` | `REDWideGamutRGB` |
| Sony | `SLog3` | `Venice S-Gamut3` |

For FilmLight inverse LUTs (files ending in `_inv.cub`), the baking command is the same but the output CLF name has `_inv` suffix.

- [ ] **Step 3: Write `scripts/bake_vendor_clfs.sh`**

A shell script that:
1. Sets `BAKER_CMD` to the path of `aces-clf-baker` (with a configurable variable at the top)
2. Sets `FAMILIES_DIR` to `ocio_vendor_extensions/families`
3. For each family, iterates through the baking table and runs the command
4. Reports success/failure count at the end

```bash
#!/usr/bin/env bash
set -euo pipefail

BAKER_CMD="${ACES_CLF_BAKER:-aces-clf-baker}"
FAMILIES_DIR="$(dirname "$0")/../ocio_vendor_extensions/families"

bake() {
    local family="$1" input="$2" output="$3" in_tf="$4" in_gamut="$5"
    local src="$FAMILIES_DIR/$family/luts/$input"
    local dst="$FAMILIES_DIR/$family/luts/$output"
    echo "  $input -> $output"
    $BAKER_CMD "$src" "$dst" --in-tf "$in_tf" --in-gamut "$in_gamut"
}

echo "=== ARRI (6 CLFs) ==="
bake arri "ARRI_LogC2Video_709_davinci3d_33.cube" "ARRI_ACES_to_Rec709_davinci3d_33.clf" "LogC3" "ARRI Wide Gamut 3"
# ... (all 6 ARRI entries)

echo "=== DaVinci (15 CLFs) ==="
# ... (all 15 DaVinci entries)

# ... etc for FilmLight (60), RED IPP2 (8), Sony (2)

echo "Done. Baked all CLFs."
```

Fill in every single baking call — one `bake` line per LUT file. Derive the CLF names from the naming convention. To build the complete list, read each family's `luts/` directory:

```bash
ls ocio_vendor_extensions/families/arri/luts/*.cube
ls ocio_vendor_extensions/families/davinci/luts/*.cube
ls ocio_vendor_extensions/families/filmlight/luts/*.cub
ls ocio_vendor_extensions/families/red_ipp2/luts/*.cube
ls ocio_vendor_extensions/families/sony/luts/*.cube
```

For each file, generate a `bake` line applying the §2.2 naming convention. The script must contain all 91 lines — no placeholders or ellipses.

- [ ] **Step 4: Commit**

```bash
git add docs/clf-baking-guide.md scripts/bake_vendor_clfs.sh ocio_vendor_extensions/families_pre_clf/
git commit -m "docs: add CLF baking guide, bake script, and pre-migration backup"
```

---

## Task 2: FilmLight T-Log Analytical Strategy Selection — COMPLETED

**Result: PASS.** `LogCameraTransform` analytically represents T-Log within tolerance.

- Encode error (code value space): 9.15e-07
- Decode error (re-encoded to code values): 3.12e-07
- OCIO round-trip error (scene-linear): 1.19e-04 (float32 precision, not formula error)

**Confirmed parameters** (used in Task 5):

```yaml
- !<LogCameraTransform> {base: 2.718281828459045, log_side_slope: 0.09232902596577353, log_side_offset: 0.5520126568606655, lin_side_slope: 1.0, lin_side_offset: 0.0057048244042473785, lin_side_break: 0.0, linear_slope: 16.184376489665897, direction: inverse}
```

Script: `scripts/test_tlog_fit.py` (already committed).

---

## Task 3: Update ARRI Family

**Files:**
- Modify: `ocio_vendor_extensions/families/arri/colorspaces.ocio`
- Modify: `ocio_vendor_extensions/families/arri/family.yaml`
- Add: `ocio_vendor_extensions/families/arri/luts/*.clf` (6 files)
- Remove: `ocio_vendor_extensions/families/arri/luts/*.cube` (6 files)

**Prerequisites:** CLFs must be pre-baked by the user using `scripts/bake_vendor_clfs.sh` or manually. **Do not use placeholder CLFs** — `config.validate()` may pass with empty files but color output will be wrong. The user must bake real CLFs before proceeding with family updates.

- [ ] **Step 1: Update `family.yaml` — add new intermediates**

Add to `intermediates:` list:

```yaml
intermediates:
- 'ARRI LogC4'
- 'Linear ARRI Wide Gamut 3'
- 'Linear ARRI Wide Gamut 4'
```

- [ ] **Step 2: Rewrite `colorspaces.ocio` — display views**

For each of the 6 display-referred color spaces, replace the `GroupTransform` with a single `FileTransform`:

Before:
```yaml
    from_scene_reference: !<GroupTransform>
      children:
        - !<ColorSpaceTransform> {src: ACES2065-1, dst: ARRI LogC3 (EI800)}
        - !<FileTransform> {src: ARRI_LogC2Video_709_davinci3d_33.cube, interpolation: best}
```

After:
```yaml
    from_scene_reference: !<FileTransform> {src: ARRI_ACES_to_Rec709_davinci3d_33.clf, interpolation: best}
```

Apply this pattern to all 6 display color spaces, using the CLF names from the baking guide.

The mapping of original LUT → CLF name for ARRI:

| Original | CLF |
|----------|-----|
| `ARRI_LogC2Video_709_davinci3d_33.cube` | `ARRI_ACES_to_Rec709_davinci3d_33.clf` |
| `ARRI_LogC2Video_Classic709_davinci3d_33.cube` | `ARRI_ACES_to_Rec709_Classic_davinci3d_33.clf` |
| `ARRI_LogC2Video_P3D65_davinci3d_33.cube` | `ARRI_ACES_to_P3D65_davinci3d_33.clf` |
| `ARRI_LogC2Video_2020_davinci3d_33.cube` | `ARRI_ACES_to_Rec2020_davinci3d_33.clf` |
| `ARRI_LogC2Video_2100HLG-PW-1k-DW100_davinci3d_33.cube` | `ARRI_ACES_to_Rec2100HLG_1000nits_davinci3d_33.clf` |
| `ARRI_LogC2Video_2100PQ-PW-1k-DW100_davinci3d_33.cube` | `ARRI_ACES_to_Rec2100PQ_1000nits_davinci3d_33.clf` |

- [ ] **Step 3: Add new intermediate color spaces to `colorspaces.ocio`**

Add these color space definitions (copied from the ACES v2.0 studio config `INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio`). Place them in the `colorspaces:` section alongside the existing `ARRI LogC3 (EI800)`:

1. **ARRI LogC4** — `LogCameraTransform` {log_side_slope: 0.0647954196341293, log_side_offset: -0.295908392682586, lin_side_slope: 2231.82630906769, lin_side_offset: 64, lin_side_break: -0.0180569961199113, direction: inverse} + `MatrixTransform` {matrix: [0.750957362824734, 0.144422786709757, 0.104619850465509, 0, 0.000821837079380207, 1.007397584885, -0.00821942196438358, 0, -0.000499952143533471, -0.000854177231436971, 1.00135412937497, 0, 0, 0, 0, 1]}

2. **Linear ARRI Wide Gamut 3** — `MatrixTransform` {matrix: [0.680205505106279, 0.236136601606481, 0.0836578932872398, 0, 0.0854149797421404, 1.01747087860704, -0.102885858349182, 0, 0.00205652166929683, -0.0625625003847921, 1.06050597871549, 0, 0, 0, 0, 1]}

3. **Linear ARRI Wide Gamut 4** — `MatrixTransform` {matrix: [0.750957362824734, 0.144422786709757, 0.104619850465509, 0, 0.000821837079380207, 1.007397584885, -0.00821942196438358, 0, -0.000499952143533471, -0.000854177231436971, 1.00135412937497, 0, 0, 0, 0, 1]}

Use the full color space definition format matching the existing snippet style (name, family, equalitygroup, bitdepth, description, isdata, allocation, to_scene_reference). Extract the complete YAML block from the studio config file `INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio` by searching for the color space name (e.g., `grep -A 20 "name: ARRI LogC4"`). Strip OCIO v2.5-specific fields (`aliases`, `interop_id`, `interchange`, `categories`, `encoding`) to keep the snippet compatible with v2.3+.

- [ ] **Step 4: Swap LUT files**

```bash
cd ocio_vendor_extensions/families/arri/luts/
# Remove old .cube files
rm -f *.cube
# Verify CLF files are present (baked by user or placeholder)
ls *.clf
```

Expected: 6 `.clf` files, 0 `.cube` files.

- [ ] **Step 5: Validate the snippet parses**

```python
import PyOpenColorIO as OCIO
config = OCIO.Config.CreateFromFile('ocio_vendor_extensions/families/arri/colorspaces.ocio')
config.validate()
print("ARRI snippet validates OK")
```

- [ ] **Step 6: Commit**

```bash
git add ocio_vendor_extensions/families/arri/
git commit -m "feat(arri): migrate display LUTs to CLFs, add LogC4/linear intermediates"
```

---

## Task 4: Update DaVinci Family

**Files:**
- Modify: `ocio_vendor_extensions/families/davinci/colorspaces.ocio`
- Modify: `ocio_vendor_extensions/families/davinci/family.yaml`
- Add: `ocio_vendor_extensions/families/davinci/luts/*.clf` (15 files)
- Remove: `ocio_vendor_extensions/families/davinci/luts/*.cube` (15 files)

- [ ] **Step 1: Update `family.yaml`**

```yaml
intermediates:
- 'Linear DaVinci WideGamut'
```

- [ ] **Step 2: Rewrite `colorspaces.ocio` — display views**

Same pattern as ARRI: replace each `GroupTransform` (ColorSpaceTransform + FileTransform) with a single `FileTransform` pointing to the CLF.

The mapping for DaVinci (15 LUTs → 15 CLFs). Derive CLF names using the convention: `DaVinci_ACES_to_{Display}_{details}.clf`. Examples:

| Original | CLF |
|----------|-----|
| `DVI-DVWG_to_Rec709-2_4y_x65.cube` | `DaVinci_ACES_to_Rec709_2_4y.clf` |
| `DVI-DVWG_to_P3D65-2_6y_x65.cube` | `DaVinci_ACES_to_P3D65_2_6y.clf` |
| `DVI-DVWG_to_sRGB_x65.cube` | `DaVinci_ACES_to_sRGB.clf` |
| `DVI-DVWG_to_HLG-Rec2100_x65.cube` | `DaVinci_ACES_to_HLG_Rec2100.clf` |
| `DVI-DVWG_to_Rec2020-2_4y_x65.cube` | `DaVinci_ACES_to_Rec2020_2_4y.clf` |
| ... | (apply same pattern to all 15) |

- [ ] **Step 3: Add new intermediate — Linear DaVinci WideGamut**

From studio config: `MatrixTransform` {matrix: [0.748270290272981, 0.167694659554328, 0.0840350501726906, 0, 0.0208421234689102, 1.11190474268894, -0.132746866157851, 0, -0.0915122574225729, -0.127746712807307, 1.21925897022988, 0, 0, 0, 0, 1]}

- [ ] **Step 4: Swap LUT files**

```bash
cd ocio_vendor_extensions/families/davinci/luts/
rm -f *.cube
ls *.clf  # Should show 15 files
```

- [ ] **Step 5: Validate snippet**

```python
import PyOpenColorIO as OCIO
config = OCIO.Config.CreateFromFile('ocio_vendor_extensions/families/davinci/colorspaces.ocio')
config.validate()
print("DaVinci snippet validates OK")
```

- [ ] **Step 6: Commit**

```bash
git add ocio_vendor_extensions/families/davinci/
git commit -m "feat(davinci): migrate display LUTs to CLFs, add Linear DaVinci WideGamut"
```

---

## Task 5: Update FilmLight Family

This is the most complex family — display CLFs + analytical intermediate conversion.

**Files:**
- Modify: `ocio_vendor_extensions/families/filmlight/colorspaces.ocio`
- Modify: `ocio_vendor_extensions/families/filmlight/family.yaml` (intermediates list unchanged, but verify)
- Add: `ocio_vendor_extensions/families/filmlight/luts/*.clf` (60 files: 30 forward + 30 inverse)
- Remove: `ocio_vendor_extensions/families/filmlight/luts/*.cub` (61 files)
- Remove: `ocio_vendor_extensions/families/filmlight/luts/*.spimtx` (2 files)

- [ ] **Step 1: Rewrite `colorspaces.ocio` — display views**

For each of the 30 display-referred color spaces, replace both `from_scene_reference` and `to_scene_reference` with single `FileTransform`s:

Before:
```yaml
    from_scene_reference: !<GroupTransform>
      children:
        - !<ColorSpaceTransform> {src: ACES2065-1, dst: "FilmLight : T-Log : E-Gamut 2"}
        - !<FileTransform> {src: FilmLight_TLog_EGamut2_2_ACES_709.cub, interpolation: best}
    to_scene_reference: !<GroupTransform>
      children:
        - !<FileTransform> {src: FilmLight_TLog_EGamut2_2_ACES_709_inv.cub, interpolation: best}
        - !<ColorSpaceTransform> {src: "FilmLight : T-Log : E-Gamut 2", dst: ACES2065-1}
```

After:
```yaml
    from_scene_reference: !<FileTransform> {src: FilmLight_ACES_to_Rec709.clf, interpolation: best}
    to_scene_reference: !<FileTransform> {src: FilmLight_ACES_to_Rec709_inv.clf, interpolation: best}
```

Apply to all 30 display color spaces. Derive CLF names from the naming convention.

- [ ] **Step 2: Rewrite `FilmLight : T-Log : E-Gamut 2` intermediate**

Use the verified `LogCameraTransform` parameters from Task 2:

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

The E-Gamut 2 → ACES2065-1 matrix was computed as the inverse of the ACES2065-1 → E-Gamut 2 matrix from the `.spimtx` file.

- [ ] **Step 3: Rewrite `FilmLight : Linear : E-Gamut 2` intermediate**

```yaml
  - !<ColorSpace>
    name: "FilmLight : Linear : E-Gamut 2"
    family: FilmLight/scene_referred
    equalitygroup: ""
    bitdepth: 32f
    description: "FilmLight : Linear : E-Gamut 2"
    isdata: false
    allocation: uniform
    allocationvars: [0, 1]
    from_scene_reference: !<MatrixTransform> {matrix: [1.25992, -0.180662, -0.0792596, 0, 0.00486135, 0.944082, 0.0510565, 0, 0.121236, 0.0466471, 0.832117, 0, 0, 0, 0, 1]}
```

This replaces the `FileTransform` to `ACES_lin_2_FilmLight_Linear_EGamut2.spimtx`.

- [ ] **Step 4: Swap LUT files**

```bash
cd ocio_vendor_extensions/families/filmlight/luts/
rm -f *.cub *.spimtx
ls *.clf  # Should show 60 files (30 forward + 30 inverse)
```

- [ ] **Step 5: Validate snippet**

```python
import PyOpenColorIO as OCIO
config = OCIO.Config.CreateFromFile('ocio_vendor_extensions/families/filmlight/colorspaces.ocio')
config.validate()
print("FilmLight snippet validates OK")
```

- [ ] **Step 6: Commit**

```bash
git add ocio_vendor_extensions/families/filmlight/
git commit -m "feat(filmlight): migrate display LUTs to CLFs, convert intermediates to analytical"
```

---

## Task 6: Update RED IPP2 Family

**Files:**
- Modify: `ocio_vendor_extensions/families/red_ipp2/colorspaces.ocio`
- Modify: `ocio_vendor_extensions/families/red_ipp2/family.yaml`
- Add: `ocio_vendor_extensions/families/red_ipp2/luts/*.clf` (8 files)
- Remove: `ocio_vendor_extensions/families/red_ipp2/luts/*.cube` (8 files)

- [ ] **Step 1: Update `family.yaml`**

```yaml
intermediates:
- 'Linear REDWideGamutRGB'
```

- [ ] **Step 2: Rewrite `colorspaces.ocio` — display views**

Same pattern. The mapping for RED IPP2 (8 LUTs → 8 CLFs):

| Original | CLF |
|----------|-----|
| `RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_1_Hard size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec709_MC_R1_Hard.clf` |
| `RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_2_Medium size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec709_MC_R2_Medium.clf` |
| `RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_3_Soft size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec709_MC_R3_Soft.clf` |
| `RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_4_VerySoft size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec709_MC_R4_VerySoft.clf` |
| `RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_1_Hard size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec2020_MC_R1_Hard.clf` |
| `RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_2_Medium size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec2020_MC_R2_Medium.clf` |
| `RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_3_Soft size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec2020_MC_R3_Soft.clf` |
| `RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_4_VerySoft size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec2020_MC_R4_VerySoft.clf` |

- [ ] **Step 3: Add new intermediate — Linear REDWideGamutRGB**

From studio config: `MatrixTransform` {matrix: [0.785058804068092, 0.0838587565440846, 0.131082439387823, 0, 0.0231738348454756, 1.08789754919233, -0.111071384037806, 0, -0.0737604353682082, -0.314590072290208, 1.38835050765842, 0, 0, 0, 0, 1]}

- [ ] **Step 4: Swap LUT files**

```bash
cd ocio_vendor_extensions/families/red_ipp2/luts/
rm -f *.cube
ls *.clf  # Should show 8 files
```

- [ ] **Step 5: Validate snippet**

```python
import PyOpenColorIO as OCIO
config = OCIO.Config.CreateFromFile('ocio_vendor_extensions/families/red_ipp2/colorspaces.ocio')
config.validate()
print("RED IPP2 snippet validates OK")
```

- [ ] **Step 6: Commit**

```bash
git add ocio_vendor_extensions/families/red_ipp2/
git commit -m "feat(red_ipp2): migrate display LUTs to CLFs, add Linear REDWideGamutRGB"
```

---

## Task 7: Update Sony Family

**Files:**
- Modify: `ocio_vendor_extensions/families/sony/colorspaces.ocio`
- Modify: `ocio_vendor_extensions/families/sony/family.yaml`
- Add: `ocio_vendor_extensions/families/sony/luts/*.clf` (2 files)
- Remove: `ocio_vendor_extensions/families/sony/luts/*.cube` (2 files)

- [ ] **Step 1: Update `family.yaml`**

```yaml
intermediates:
- 'S-Log3 S-Gamut3'
- 'S-Log3 S-Gamut3.Cine'
- 'S-Log3 Venice S-Gamut3.Cine'
- 'Linear S-Gamut3'
- 'Linear Venice S-Gamut3'
```

- [ ] **Step 2: Rewrite `colorspaces.ocio` — display views**

| Original | CLF |
|----------|-----|
| `SL3SG3tos709.cube` | `Sony_ACES_to_Rec709.clf` |
| `SL3SG3tosP3D65.cube` | `Sony_ACES_to_P3D65.clf` |

- [ ] **Step 3: Add new intermediates**

From studio config, add these 5 color spaces:

1. **S-Log3 S-Gamut3** — `LogCameraTransform` {base: 10, log_side_slope: 0.255620723362659, log_side_offset: 0.410557184750733, lin_side_slope: 5.26315789473684, lin_side_offset: 0.0526315789473684, lin_side_break: 0.01125, linear_slope: 6.62194371177582, direction: inverse} + `MatrixTransform` {matrix: [0.75298259539984, 0.143370216235557, 0.103647188364603, 0, 0.0217076974414429, 1.01531883550528, -0.0370265329467195, 0, -0.00941605274963355, 0.00337041785882367, 1.00604563489081, 0, 0, 0, 0, 1]}

2. **S-Log3 S-Gamut3.Cine** — Same `LogCameraTransform` + `MatrixTransform` {matrix: [0.638788667185978, 0.272351433711262, 0.0888598991027595, 0, -0.00391590602528224, 1.0880732308974, -0.0841573248721177, 0, -0.0299072021239151, -0.0264325799101947, 1.05633978203411, 0, 0, 0, 0, 1]}

3. **S-Log3 Venice S-Gamut3.Cine** — Same `LogCameraTransform` + `MatrixTransform` {matrix: [0.674257092126512, 0.220571735923397, 0.10517117195009, 0, -0.00931360607857167, 1.10595886142466, -0.0966452553460855, 0, -0.0382090673002312, -0.017938376600236, 1.05614744390047, 0, 0, 0, 0, 1]}

4. **Linear S-Gamut3** — `MatrixTransform` {matrix: [0.75298259539984, 0.143370216235557, 0.103647188364603, 0, 0.0217076974414429, 1.01531883550528, -0.0370265329467195, 0, -0.00941605274963355, 0.00337041785882367, 1.00604563489081, 0, 0, 0, 0, 1]}

5. **Linear Venice S-Gamut3** — `MatrixTransform` {matrix: [0.793329741146434, 0.089078625620677, 0.117591633232888, 0, 0.0155810585252582, 1.03271230692988, -0.0482933654551394, 0, -0.0188647477991488, 0.0127694120973433, 1.00609533570181, 0, 0, 0, 0, 1]}

- [ ] **Step 4: Swap LUT files**

```bash
cd ocio_vendor_extensions/families/sony/luts/
rm -f *.cube
ls *.clf  # Should show 2 files
```

- [ ] **Step 5: Validate snippet**

```python
import PyOpenColorIO as OCIO
config = OCIO.Config.CreateFromFile('ocio_vendor_extensions/families/sony/colorspaces.ocio')
config.validate()
print("Sony snippet validates OK")
```

- [ ] **Step 6: Commit**

```bash
git add ocio_vendor_extensions/families/sony/
git commit -m "feat(sony): migrate display LUTs to CLFs, add S-Gamut3 variants + linear intermediates"
```

---

## Task 8: Verification Script

**Files:**
- Create: `scripts/verify_clf_migration.py`

- [ ] **Step 1: Write the verification script**

```python
#!/usr/bin/env python3
"""Compare old (pre-CLF) vs new (CLF-based) vendor family transform chains.

Loads each display color space from both the old and new family snippets,
creates OCIO processors, and compares their output on test patches.

Usage:
    python scripts/verify_clf_migration.py [--family arri|davinci|filmlight|red_ipp2|sony]
"""
import argparse
import sys
import os
import numpy as np

try:
    import PyOpenColorIO as OCIO
except ImportError:
    print("ERROR: PyOpenColorIO required. pip install opencolorio")
    sys.exit(1)

FAMILIES_DIR = os.path.join(os.path.dirname(__file__), '..', 'ocio_vendor_extensions', 'families')
BACKUP_DIR = os.path.join(os.path.dirname(__file__), '..', 'ocio_vendor_extensions', 'families_pre_clf')

# 24-patch ColorChecker in ACES2065-1 (approximate)
TEST_PATCHES_ACES = np.array([
    [0.1150, 0.1000, 0.0500],  # dark skin
    [0.3900, 0.3500, 0.2400],  # light skin
    [0.1800, 0.1800, 0.3100],  # blue sky
    [0.1000, 0.1500, 0.0500],  # foliage
    [0.2700, 0.2400, 0.4200],  # blue flower
    [0.2700, 0.5800, 0.4000],  # bluish green
    [0.5600, 0.2900, 0.0200],  # orange
    [0.1100, 0.1000, 0.3800],  # purplish blue
    [0.4300, 0.1200, 0.0600],  # moderate red
    [0.0600, 0.0300, 0.1000],  # purple
    [0.3400, 0.4400, 0.0200],  # yellow green
    [0.5800, 0.4500, 0.0200],  # orange yellow
    [0.0500, 0.0400, 0.3100],  # blue
    [0.1400, 0.2700, 0.0600],  # green
    [0.3200, 0.0500, 0.0200],  # red
    [0.6600, 0.5900, 0.0100],  # yellow
    [0.3700, 0.1100, 0.2800],  # magenta
    [0.0800, 0.2400, 0.3900],  # cyan
    [0.9000, 0.8600, 0.7600],  # white
    [0.5900, 0.5700, 0.5100],  # neutral 8
    [0.3600, 0.3500, 0.3200],  # neutral 6.5
    [0.2000, 0.1900, 0.1900],  # neutral 5
    [0.0900, 0.0900, 0.0800],  # neutral 3.5
    [0.0300, 0.0300, 0.0300],  # black
], dtype=np.float32)


def load_config_permissive(path):
    """Load an OCIO config, ignoring validation errors."""
    with open(path, 'r') as f:
        text = f.read()
    config = OCIO.Config.CreateFromStream(text)
    return config


def get_display_colorspaces(config):
    """Get all non-utility color space names."""
    names = []
    for i in range(config.getNumColorSpaces()):
        name = config.getColorSpaceNameByIndex(i)
        cs = config.getColorSpace(name)
        if cs.getFamily().startswith(('ARRI/', 'DaVinci/', 'FilmLight/', 'RED-IPP2/', 'SONY/')):
            if 'display_referred' in cs.getFamily():
                names.append(name)
    return names


def compare_processors(old_config, new_config, cs_name, reference_cs='ACES2065-1'):
    """Compare processor output for a color space between old and new configs."""
    try:
        old_proc = old_config.getProcessor(reference_cs, cs_name)
        old_cpu = old_proc.getDefaultCPUProcessor()
    except Exception as e:
        return None, f"OLD config error: {e}"

    try:
        new_proc = new_config.getProcessor(reference_cs, cs_name)
        new_cpu = new_proc.getDefaultCPUProcessor()
    except Exception as e:
        return None, f"NEW config error: {e}"

    max_err = 0.0
    for patch in TEST_PATCHES_ACES:
        old_result = old_cpu.applyRGB(list(patch))
        new_result = new_cpu.applyRGB(list(patch))
        err = max(abs(old_result[i] - new_result[i]) for i in range(3))
        max_err = max(max_err, err)

    return max_err, None


def verify_family(family_name):
    """Verify one family's CLF migration."""
    old_path = os.path.join(BACKUP_DIR, family_name, 'colorspaces.ocio')
    new_path = os.path.join(FAMILIES_DIR, family_name, 'colorspaces.ocio')

    if not os.path.exists(old_path):
        print(f"  SKIP: No backup found at {old_path}")
        return True

    old_config = load_config_permissive(old_path)
    new_config = load_config_permissive(new_path)

    display_cs = get_display_colorspaces(new_config)
    if not display_cs:
        print(f"  WARN: No display color spaces found in {family_name}")
        return True

    all_pass = True
    for cs_name in display_cs:
        max_err, error = compare_processors(old_config, new_config, cs_name)
        if error:
            print(f"  ERROR {cs_name}: {error}")
            all_pass = False
        elif max_err > 0.001:
            print(f"  FAIL  {cs_name}: max error = {max_err:.6f}")
            all_pass = False
        else:
            print(f"  PASS  {cs_name}: max error = {max_err:.2e}")

    return all_pass


def main():
    parser = argparse.ArgumentParser(description='Verify CLF migration accuracy')
    parser.add_argument('--family', choices=['arri', 'davinci', 'filmlight', 'red_ipp2', 'sony'],
                        help='Verify a single family (default: all)')
    args = parser.parse_args()

    families = [args.family] if args.family else ['arri', 'davinci', 'filmlight', 'red_ipp2', 'sony']

    all_pass = True
    for family in families:
        print(f"\n=== {family.upper()} ===")
        if not verify_family(family):
            all_pass = False

    print(f"\n{'ALL PASSED' if all_pass else 'SOME FAILURES'}")
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Add FilmLight analytical intermediate verification (spec §6.2)**

Add a `verify_filmlight_analytical()` function to the script that:
1. Loads the **old** FilmLight snippet (from `families_pre_clf/filmlight/colorspaces.ocio`)
2. Loads the **new** FilmLight snippet
3. For the `FilmLight : T-Log : E-Gamut 2` color space, creates processors for `to_scene_reference` in both old and new configs
4. Compares output on 10,000 code values in [0, 1] (T-Log encoded)
5. Tolerance: max component error < 1e-4 (stricter than display CLF tolerance)

```python
def verify_filmlight_analytical():
    """Compare new analytical T-Log intermediate vs old LUT-based chain."""
    old_path = os.path.join(BACKUP_DIR, 'filmlight', 'colorspaces.ocio')
    new_path = os.path.join(FAMILIES_DIR, 'filmlight', 'colorspaces.ocio')

    if not os.path.exists(old_path):
        print("  SKIP: No FilmLight backup found")
        return True

    old_config = load_config_permissive(old_path)
    new_config = load_config_permissive(new_path)

    cs_name = 'FilmLight : T-Log : E-Gamut 2'
    ref_cs = 'ACES2065-1'

    try:
        old_proc = old_config.getProcessor(cs_name, ref_cs)
        new_proc = new_config.getProcessor(cs_name, ref_cs)
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

    old_cpu = old_proc.getDefaultCPUProcessor()
    new_cpu = new_proc.getDefaultCPUProcessor()

    max_err = 0.0
    for v in np.linspace(0.0, 1.0, 10000):
        old_result = old_cpu.applyRGB([float(v)] * 3)
        new_result = new_cpu.applyRGB([float(v)] * 3)
        err = max(abs(old_result[i] - new_result[i]) for i in range(3))
        max_err = max(max_err, err)

    TOLERANCE = 1e-4
    if max_err < TOLERANCE:
        print(f"  PASS  T-Log analytical: max error = {max_err:.2e} (< {TOLERANCE})")
        return True
    else:
        print(f"  FAIL  T-Log analytical: max error = {max_err:.2e} (>= {TOLERANCE})")
        return False
```

Call this from `main()` when processing the `filmlight` family.

- [ ] **Step 3: Run verification (after CLFs are baked)**

```bash
python3 scripts/verify_clf_migration.py
```

Expected: All display color spaces show `PASS` with max error < 0.001. FilmLight analytical shows `PASS` with max error < 1e-4.

- [ ] **Step 4: Commit**

```bash
git add scripts/verify_clf_migration.py
git commit -m "test: add CLF migration verification script with FilmLight analytical check"
```

---

## Task 9: End-to-End Integration Test

- [ ] **Step 1: Run `extend --dry-run` against studio config**

```bash
python3 -m ocio_aces_tools extend \
  INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio \
  --dry-run
```

Expected: Lists all families, shows color spaces that would be added, no errors.

- [ ] **Step 2: Run `extend` for real and validate output**

```bash
python3 -m ocio_aces_tools extend \
  INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio \
  -o /tmp/extended_clf_test.ocio \
  --skip-missing-displays
```

Then validate:

```python
import PyOpenColorIO as OCIO
config = OCIO.Config.CreateFromFile('/tmp/extended_clf_test.ocio')
config.validate()
print(f"Config validates OK. {config.getNumColorSpaces()} color spaces.")
```

- [ ] **Step 3: Spot-check a display view processor**

```python
import PyOpenColorIO as OCIO
config = OCIO.Config.CreateFromFile('/tmp/extended_clf_test.ocio')
proc = config.getProcessor('ACES2065-1', 'ARRI : Rec.1886: 2.4 Gamma : Rec.709')
cpu = proc.getDefaultCPUProcessor()
result = cpu.applyRGB([0.18, 0.18, 0.18])
print(f"18% grey through ARRI Rec709: {result}")
# Should produce a reasonable display value (roughly 0.4-0.5 range for SDR)
```

- [ ] **Step 4: OCIO 2.1 downgrade test (spec §6.4)**

Run the existing `lut-build` downgrade on the extended config to verify CLF `FileTransform`s survive the v2.3→v2.1 conversion:

```bash
python3 -m ocio_aces_tools lut-build \
  /tmp/extended_clf_test.ocio \
  -o /tmp/extended_clf_test_v21/ \
  --target-version 2.1
```

Then validate the downgraded config:

```python
import PyOpenColorIO as OCIO
import glob
v21_configs = glob.glob('/tmp/extended_clf_test_v21/*.ocio')
for path in v21_configs:
    config = OCIO.Config.CreateFromFile(path)
    config.validate()
    print(f"v2.1 config validates OK: {path}")
    # Spot-check a vendor display view still resolves
    try:
        proc = config.getProcessor('ACES2065-1', 'ARRI : Rec.1886: 2.4 Gamma : Rec.709')
        cpu = proc.getDefaultCPUProcessor()
        result = cpu.applyRGB([0.18, 0.18, 0.18])
        print(f"  ARRI Rec709 on 18% grey: {result}")
    except Exception as e:
        print(f"  Note: {e} (display may not exist in this config variant)")
```

If the `lut-build` subcommand interface differs, adapt the command. The key check is that the downgraded config validates and vendor display views still resolve.

- [ ] **Step 5: Update CLAUDE.md**

Add a note about the CLF migration to the "6. Vendor Display Extensions" section in `CLAUDE.md`:

- Mention that display views use pre-baked CLFs (ACES2065-1 → display in one file)
- Reference `docs/clf-baking-guide.md` for reproducibility
- Note that FilmLight intermediates are now analytical

- [ ] **Step 6: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with CLF migration notes"
```

---

## Task Summary

| Task | Description | Depends On |
|------|------------|------------|
| 1 | Backup + baking documentation | — |
| 2 | T-Log analytical strategy selection | — |
| 3 | Update ARRI family | 1 (backup), CLFs baked |
| 4 | Update DaVinci family | 1 (backup), CLFs baked |
| 5 | Update FilmLight family | 1 (backup), 2 (T-Log strategy), CLFs baked |
| 6 | Update RED IPP2 family | 1 (backup), CLFs baked |
| 7 | Update Sony family | 1 (backup), CLFs baked |
| 8 | Verification script (display CLFs + FilmLight analytical) | 1 (backup), 3-7 (families updated) |
| 9 | End-to-end integration + OCIO 2.1 downgrade + docs | 3-8 (all families + verification) |

**Parallelizable:** Tasks 1 and 2 are independent and can run in parallel. Tasks 3, 4, 6, 7 are independent and can run in parallel after Task 1. Task 5 depends on Tasks 1 and 2. Task 8 depends on all family tasks. Task 9 is the final gate.

**User action required:** Before Tasks 3-7, the user must bake all 91 CLFs using `scripts/bake_vendor_clfs.sh` (or manually with `aces-clf-baker`). The plan assumes real baked CLFs are available in each family's `luts/` directory — do not use placeholders.
