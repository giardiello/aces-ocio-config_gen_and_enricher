# CLF Baking Guide — Vendor Display LUT Migration

This guide documents the exact commands to reproduce all vendor CLF files from their original LUT sources using `aces-clf-baker`.

## Tool

- **Binary:** `aces-clf-baker`
- **Source:** `IDT_Maker/ACES_CLF_BAKER_EXTENDED` (sibling repository to this project)

The tool wraps vendor LUTs in ACES2065-1–bounded CLFs by prepending a gamut matrix and transfer-function decode shaper.

## Naming convention

- **Pattern:** `{Vendor}_ACES_to_{Display}_{details}.clf`
- **Inverse CLFs (FilmLight only):** append the `_inv` suffix before `.clf`
- **Examples:** `ARRI_ACES_to_Rec709_davinci3d_33.clf`, `FilmLight_ACES_to_Rec709_inv.clf`

## Per-family baking parameters

| Family    | `--in-tf`              | `--in-gamut`         | CAT        | Whitepoint | Notes |
| --------- | ---------------------- | -------------------- | ---------- | ---------- | ----- |
| ARRI      | `ARRI LogC3`           | `ARRI Wide Gamut 3`  | CAT02 (default) | D65 | Standard `colour-science` gamut |
| DaVinci   | `DaVinci Intermediate` | `DaVinci Wide Gamut` | CAT02 (default) | D65 | Standard `colour-science` gamut |
| FilmLight | `T-Log`                | _E-Gamut 2_ via `--in-matrix` | CAT02 | D65 | E-Gamut 2 ≠ E-Gamut (different primaries); requires `--in-matrix` until `colour-science` ≥ 0.4.7 |
| RED IPP2  | `Log3G10`              | `REDWideGamutRGB`    | **Bradford** | D65 | Must pass `--cat Bradford` explicitly |
| Sony      | `S-Log3`               | `Venice S-Gamut3`    | CAT02 (default) | D65 | Standard `colour-science` gamut |

### Gamut matrix details

All vendor gamuts use a D65 whitepoint. ACES2065-1 uses D60 (ACES). The chromatic adaptation
transform (CAT) bridges D65 → D60. The default in `aces-clf-baker` is CAT02.

**E-Gamut vs E-Gamut 2:** FilmLight E-Gamut 2 (Baselight 6) has different primaries from E-Gamut:

| | Red | Green | Blue |
|---|---|---|---|
| E-Gamut | 0.8000, 0.3177 | 0.1800, 0.9000 | 0.0650, -0.0805 |
| E-Gamut 2 | 0.8300, 0.3100 | 0.1500, 0.9500 | 0.0650, -0.0805 |

E-Gamut 2 uses a vendor-defined RGB-to-XYZ matrix (6 decimal places) rather than one derived from
primaries. The ACES-to-E-Gamut-2 matrix (CAT02, D60→D65) is:

```
1.259920633591235, -0.180662782264111, -0.079259355882615
0.004861246914694,  0.944082819831840,  0.051056395176724
0.121235969973557,  0.046647078187213,  0.832116647458241
```

**RED IPP2:** Uses Bradford CAT (not CAT02). The computed ACES-to-RWG matrix matches the vendor
config at 4.7e-7 precision using `--in-gamut REDWideGamutRGB --cat Bradford`.

### Verification of CAT choices

Each family's matrix was verified by computing `colour.matrix_RGB_to_RGB(gamut, aces, cat)` and
comparing against the vendor-supplied matrix from the original OCIO config:

| Family | CAT | Max error vs vendor |
|--------|-----|---------------------|
| ARRI | CAT02 | 4.9e-7 |
| DaVinci | CAT02 | 5.3e-11 |
| FilmLight | CAT02 + E-Gamut 2 matrix | 8.2e-7 |
| RED | Bradford | 4.7e-7 |
| Sony | CAT02 | 4.2e-11 |

## Path convention (this repository)

Unless noted, paths are relative to the repository root:

- Input LUTs: `ocio_vendor_extensions/families_pre_clf/<family>/luts/<filename>` (backup of originals)
- Output CLFs: `ocio_vendor_extensions/families/<family>/luts/<filename>`

Command template:

```text
# Standard (ARRI, DaVinci, Sony — CAT02 is default):
aces-clf-baker <input_lut> <output_clf> --in-tf <tf> --in-gamut <gamut>

# RED IPP2 (Bradford CAT):
aces-clf-baker <input_lut> <output_clf> --in-tf Log3G10 --in-gamut REDWideGamutRGB --cat Bradford

# FilmLight (E-Gamut 2 via explicit matrix):
aces-clf-baker <input_lut> <output_clf> --in-tf T-Log --in-gamut "FilmLight E-Gamut" \
  --in-matrix "1.259920633591235,-0.180662782264111,-0.079259355882615,0.004861246914694,0.944082819831840,0.051056395176724,0.121235969973557,0.046647078187213,0.832116647458241"
```

---

## ARRI (6 forward-only)

Base directory: `ocio_vendor_extensions/families/arri/luts/`

| Family | Original LUT | CLF Output | Command |
| ------ | ------------- | ---------- | ------- |
| ARRI | `ARRI_LogC2Video_709_davinci3d_33.cube` | `ARRI_ACES_to_Rec709_davinci3d_33.clf` | `aces-clf-baker ocio_vendor_extensions/families/arri/luts/ARRI_LogC2Video_709_davinci3d_33.cube ocio_vendor_extensions/families/arri/luts/ARRI_ACES_to_Rec709_davinci3d_33.clf --in-tf "ARRI LogC3" --in-gamut "ARRI Wide Gamut 3"` |
| ARRI | `ARRI_LogC2Video_Classic709_davinci3d_33.cube` | `ARRI_ACES_to_Rec709_Classic_davinci3d_33.clf` | `aces-clf-baker ocio_vendor_extensions/families/arri/luts/ARRI_LogC2Video_Classic709_davinci3d_33.cube ocio_vendor_extensions/families/arri/luts/ARRI_ACES_to_Rec709_Classic_davinci3d_33.clf --in-tf "ARRI LogC3" --in-gamut "ARRI Wide Gamut 3"` |
| ARRI | `ARRI_LogC2Video_P3D65_davinci3d_33.cube` | `ARRI_ACES_to_P3D65_davinci3d_33.clf` | `aces-clf-baker ocio_vendor_extensions/families/arri/luts/ARRI_LogC2Video_P3D65_davinci3d_33.cube ocio_vendor_extensions/families/arri/luts/ARRI_ACES_to_P3D65_davinci3d_33.clf --in-tf "ARRI LogC3" --in-gamut "ARRI Wide Gamut 3"` |
| ARRI | `ARRI_LogC2Video_2020_davinci3d_33.cube` | `ARRI_ACES_to_Rec2020_davinci3d_33.clf` | `aces-clf-baker ocio_vendor_extensions/families/arri/luts/ARRI_LogC2Video_2020_davinci3d_33.cube ocio_vendor_extensions/families/arri/luts/ARRI_ACES_to_Rec2020_davinci3d_33.clf --in-tf "ARRI LogC3" --in-gamut "ARRI Wide Gamut 3"` |
| ARRI | `ARRI_LogC2Video_2100HLG-PW-1k-DW100_davinci3d_33.cube` | `ARRI_ACES_to_Rec2100HLG_1000nits_davinci3d_33.clf` | `aces-clf-baker ocio_vendor_extensions/families/arri/luts/ARRI_LogC2Video_2100HLG-PW-1k-DW100_davinci3d_33.cube ocio_vendor_extensions/families/arri/luts/ARRI_ACES_to_Rec2100HLG_1000nits_davinci3d_33.clf --in-tf "ARRI LogC3" --in-gamut "ARRI Wide Gamut 3"` |
| ARRI | `ARRI_LogC2Video_2100PQ-PW-1k-DW100_davinci3d_33.cube` | `ARRI_ACES_to_Rec2100PQ_1000nits_davinci3d_33.clf` | `aces-clf-baker ocio_vendor_extensions/families/arri/luts/ARRI_LogC2Video_2100PQ-PW-1k-DW100_davinci3d_33.cube ocio_vendor_extensions/families/arri/luts/ARRI_ACES_to_Rec2100PQ_1000nits_davinci3d_33.clf --in-tf "ARRI LogC3" --in-gamut "ARRI Wide Gamut 3"` |

---

## DaVinci (15 forward-only)

Base directory: `ocio_vendor_extensions/families/davinci/luts/`

| Family | Original LUT | CLF Output | Command |
| ------ | ------------- | ---------- | ------- |
| DaVinci | `DVI-DVWG_to_Rec709-2_4y_x65.cube` | `DaVinci_ACES_to_Rec709_2_4y.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_Rec709-2_4y_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_Rec709_2_4y.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_P3D65-2_6y_x65.cube` | `DaVinci_ACES_to_P3D65_2_6y.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_P3D65-2_6y_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_P3D65_2_6y.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_sRGB_x65.cube` | `DaVinci_ACES_to_sRGB.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_sRGB_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_sRGB.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_HLG-Rec2100_x65.cube` | `DaVinci_ACES_to_HLG_Rec2100.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_HLG-Rec2100_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_HLG_Rec2100.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_Rec2020-2_4y_x65.cube` | `DaVinci_ACES_to_Rec2020_2_4y.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_Rec2020-2_4y_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_Rec2020_2_4y.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_Rec2020-PQ108nits_x65.cube` | `DaVinci_ACES_to_Rec2020_PQ108nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_Rec2020-PQ108nits_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_Rec2020_PQ108nits.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_Rec2020-PQ500nits_x65.cube` | `DaVinci_ACES_to_Rec2020_PQ500nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_Rec2020-PQ500nits_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_Rec2020_PQ500nits.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_Rec2020-PQ1000nits_x65.cube` | `DaVinci_ACES_to_Rec2020_PQ1000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_Rec2020-PQ1000nits_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_Rec2020_PQ1000nits.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_Rec2020-PQ2000nits_x65.cube` | `DaVinci_ACES_to_Rec2020_PQ2000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_Rec2020-PQ2000nits_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_Rec2020_PQ2000nits.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_Rec2020-PQ4000nits_x65.cube` | `DaVinci_ACES_to_Rec2020_PQ4000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_Rec2020-PQ4000nits_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_Rec2020_PQ4000nits.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_P3D65-PQ108nits_x65.cube` | `DaVinci_ACES_to_P3D65_PQ108nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_P3D65-PQ108nits_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_P3D65_PQ108nits.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_P3D65-PQ500nits_x65.cube` | `DaVinci_ACES_to_P3D65_PQ500nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_P3D65-PQ500nits_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_P3D65_PQ500nits.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_P3D65-PQ1000nits_x65.cube` | `DaVinci_ACES_to_P3D65_PQ1000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_P3D65-PQ1000nits_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_P3D65_PQ1000nits.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_P3D65-PQ2000nits_x65.cube` | `DaVinci_ACES_to_P3D65_PQ2000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_P3D65-PQ2000nits_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_P3D65_PQ2000nits.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |
| DaVinci | `DVI-DVWG_to_P3D65-PQ4000nits_x65.cube` | `DaVinci_ACES_to_P3D65_PQ4000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/davinci/luts/DVI-DVWG_to_P3D65-PQ4000nits_x65.cube ocio_vendor_extensions/families/davinci/luts/DaVinci_ACES_to_P3D65_PQ4000nits.clf --in-tf "DaVinci Intermediate" --in-gamut "DaVinci Wide Gamut"` |

---

## FilmLight (30 forward + 30 inverse = 60 CLFs)

Base directory: `ocio_vendor_extensions/families/filmlight/luts/`

**Important:** All FilmLight commands below additionally require `--in-matrix "<FL_EGAMUT2_MATRIX>"` (see the E-Gamut 2 matrix in the "Per-family baking parameters" section above). This is because the LUTs use **E-Gamut 2** (not E-Gamut), which has different primaries and is not yet available in `colour-science` < 0.4.7. The `--in-gamut "FilmLight E-Gamut"` flag is still passed for the T-Log transfer function lookup.

Inverse LUTs use the `_inv` suffix on the `.cub` filename; inverse CLFs use the `_inv` suffix before `.clf`, paired with the forward table in the same order.

### Forward

| Family | Original LUT | CLF Output | Command |
| ------ | ------------- | ---------- | ------- |
| FilmLight | `FilmLight_TLog_EGamut2_2_Video_Full.cub` | `FilmLight_ACES_to_Rec709.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Video_Full.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_Rec709.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_UHDTV_Full.cub` | `FilmLight_ACES_to_Rec2020.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_UHDTV_Full.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_Rec2020.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_sRGB.cub` | `FilmLight_ACES_to_sRGB.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_sRGB.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_sRGB.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_sRGB_Display.cub` | `FilmLight_ACES_to_sRGB_Display.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_sRGB_Display.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_sRGB_Display.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_ACES_P3D60.cub` | `FilmLight_ACES_to_P3D60.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_ACES_P3D60.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_P3D60.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DCI_P3D65.cub` | `FilmLight_ACES_to_P3D65.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DCI_P3D65.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_P3D65.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_P3.cub` | `FilmLight_ACES_to_P3DCI.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_P3.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_P3DCI.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DCI_XYZ.cub` | `FilmLight_ACES_to_DCI_XYZ.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DCI_XYZ.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_DCI_XYZ.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ.cub` | `FilmLight_ACES_to_PQ_P3D65_4000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_4000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_108nits.cub` | `FilmLight_ACES_to_PQ_P3D65_108nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_108nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_108nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_300nits.cub` | `FilmLight_ACES_to_PQ_P3D65_300nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_300nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_300nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_600nits.cub` | `FilmLight_ACES_to_PQ_P3D65_600nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_600nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_600nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1000nits.cub` | `FilmLight_ACES_to_PQ_P3D65_1000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1000nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_1000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1600nits.cub` | `FilmLight_ACES_to_PQ_P3D65_1600nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1600nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_1600nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_2000nits.cub` | `FilmLight_ACES_to_PQ_P3D65_2000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_2000nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_2000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_5000nits.cub` | `FilmLight_ACES_to_PQ_P3D65_5000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_5000nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_5000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_10000nits.cub` | `FilmLight_ACES_to_PQ_P3D65_10000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_10000nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_10000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_XYZ_108nits.cub` | `FilmLight_ACES_to_PQ_XYZ_108nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_XYZ_108nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_XYZ_108nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DCI_PQ_XYZ_300nits.cub` | `FilmLight_ACES_to_PQ_XYZ_300nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DCI_PQ_XYZ_300nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_XYZ_300nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020.cub` | `FilmLight_ACES_to_PQ_Rec2020_1000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_1000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_108nits.cub` | `FilmLight_ACES_to_PQ_Rec2020_108nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_108nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_108nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_300nits.cub` | `FilmLight_ACES_to_PQ_Rec2020_300nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_300nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_300nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_600nits.cub` | `FilmLight_ACES_to_PQ_Rec2020_600nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_600nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_600nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_1600nits.cub` | `FilmLight_ACES_to_PQ_Rec2020_1600nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_1600nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_1600nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_2000nits.cub` | `FilmLight_ACES_to_PQ_Rec2020_2000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_2000nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_2000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_4000nits.cub` | `FilmLight_ACES_to_PQ_Rec2020_4000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_4000nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_4000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_5000nits.cub` | `FilmLight_ACES_to_PQ_Rec2020_5000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_5000nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_5000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_10000nits.cub` | `FilmLight_ACES_to_PQ_Rec2020_10000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_10000nits.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_10000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000.cub` | `FilmLight_ACES_to_HLG_Rec2020_1000nits.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_HLG_Rec2020_1000nits.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000_PreviewSDR.cub` | `FilmLight_ACES_to_HLG_Rec2020_PreviewSDR.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000_PreviewSDR.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_HLG_Rec2020_PreviewSDR.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |

### Inverse

| Family | Original LUT | CLF Output | Command |
| ------ | ------------- | ---------- | ------- |
| FilmLight | `FilmLight_TLog_EGamut2_2_Video_Full_inv.cub` | `FilmLight_ACES_to_Rec709_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Video_Full_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_Rec709_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_UHDTV_Full_inv.cub` | `FilmLight_ACES_to_Rec2020_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_UHDTV_Full_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_Rec2020_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_sRGB_inv.cub` | `FilmLight_ACES_to_sRGB_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_sRGB_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_sRGB_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_sRGB_Display_inv.cub` | `FilmLight_ACES_to_sRGB_Display_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_sRGB_Display_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_sRGB_Display_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_ACES_P3D60_inv.cub` | `FilmLight_ACES_to_P3D60_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_ACES_P3D60_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_P3D60_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DCI_P3D65_inv.cub` | `FilmLight_ACES_to_P3D65_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DCI_P3D65_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_P3D65_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_P3_inv.cub` | `FilmLight_ACES_to_P3DCI_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_P3_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_P3DCI_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DCI_XYZ_inv.cub` | `FilmLight_ACES_to_DCI_XYZ_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DCI_XYZ_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_DCI_XYZ_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_inv.cub` | `FilmLight_ACES_to_PQ_P3D65_4000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_4000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_108nits_inv.cub` | `FilmLight_ACES_to_PQ_P3D65_108nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_108nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_108nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_300nits_inv.cub` | `FilmLight_ACES_to_PQ_P3D65_300nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_300nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_300nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_600nits_inv.cub` | `FilmLight_ACES_to_PQ_P3D65_600nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_600nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_600nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1000nits_inv.cub` | `FilmLight_ACES_to_PQ_P3D65_1000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1000nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_1000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1600nits_inv.cub` | `FilmLight_ACES_to_PQ_P3D65_1600nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1600nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_1600nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_2000nits_inv.cub` | `FilmLight_ACES_to_PQ_P3D65_2000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_2000nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_2000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_5000nits_inv.cub` | `FilmLight_ACES_to_PQ_P3D65_5000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_5000nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_5000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_10000nits_inv.cub` | `FilmLight_ACES_to_PQ_P3D65_10000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_10000nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_P3D65_10000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DolbyPQ_XYZ_108nits_inv.cub` | `FilmLight_ACES_to_PQ_XYZ_108nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DolbyPQ_XYZ_108nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_XYZ_108nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_DCI_PQ_XYZ_300nits_inv.cub` | `FilmLight_ACES_to_PQ_XYZ_300nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_DCI_PQ_XYZ_300nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_XYZ_300nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_inv.cub` | `FilmLight_ACES_to_PQ_Rec2020_1000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_1000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_108nits_inv.cub` | `FilmLight_ACES_to_PQ_Rec2020_108nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_108nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_108nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_300nits_inv.cub` | `FilmLight_ACES_to_PQ_Rec2020_300nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_300nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_300nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_600nits_inv.cub` | `FilmLight_ACES_to_PQ_Rec2020_600nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_600nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_600nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_1600nits_inv.cub` | `FilmLight_ACES_to_PQ_Rec2020_1600nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_1600nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_1600nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_2000nits_inv.cub` | `FilmLight_ACES_to_PQ_Rec2020_2000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_2000nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_2000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_4000nits_inv.cub` | `FilmLight_ACES_to_PQ_Rec2020_4000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_4000nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_4000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_5000nits_inv.cub` | `FilmLight_ACES_to_PQ_Rec2020_5000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_5000nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_5000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_10000nits_inv.cub` | `FilmLight_ACES_to_PQ_Rec2020_10000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_10000nits_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_PQ_Rec2020_10000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000_inv.cub` | `FilmLight_ACES_to_HLG_Rec2020_1000nits_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_HLG_Rec2020_1000nits_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |
| FilmLight | `FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000_PreviewSDR_inv.cub` | `FilmLight_ACES_to_HLG_Rec2020_PreviewSDR_inv.clf` | `aces-clf-baker ocio_vendor_extensions/families/filmlight/luts/FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000_PreviewSDR_inv.cub ocio_vendor_extensions/families/filmlight/luts/FilmLight_ACES_to_HLG_Rec2020_PreviewSDR_inv.clf --in-tf T-Log --in-gamut "FilmLight E-Gamut"` |

---

## RED IPP2 (8 forward-only)

Base directory: `ocio_vendor_extensions/families/red_ipp2/luts/`

Filenames contain spaces; quote paths when running in a shell.

| Family | Original LUT | CLF Output | Command |
| ------ | ------------- | ---------- | ------- |
| RED IPP2 | `RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_1_Hard size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec709_MC_R1_Hard.clf` | `aces-clf-baker 'ocio_vendor_extensions/families/red_ipp2/luts/RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_1_Hard size_33 v1.13.cube' ocio_vendor_extensions/families/red_ipp2/luts/RED-IPP2_ACES_to_Rec709_MC_R1_Hard.clf --in-tf Log3G10 --in-gamut REDWideGamutRGB --cat Bradford` |
| RED IPP2 | `RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_2_Medium size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec709_MC_R2_Medium.clf` | `aces-clf-baker 'ocio_vendor_extensions/families/red_ipp2/luts/RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_2_Medium size_33 v1.13.cube' ocio_vendor_extensions/families/red_ipp2/luts/RED-IPP2_ACES_to_Rec709_MC_R2_Medium.clf --in-tf Log3G10 --in-gamut REDWideGamutRGB --cat Bradford` |
| RED IPP2 | `RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_3_Soft size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec709_MC_R3_Soft.clf` | `aces-clf-baker 'ocio_vendor_extensions/families/red_ipp2/luts/RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_3_Soft size_33 v1.13.cube' ocio_vendor_extensions/families/red_ipp2/luts/RED-IPP2_ACES_to_Rec709_MC_R3_Soft.clf --in-tf Log3G10 --in-gamut REDWideGamutRGB --cat Bradford` |
| RED IPP2 | `RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_4_VerySoft size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec709_MC_R4_VerySoft.clf` | `aces-clf-baker 'ocio_vendor_extensions/families/red_ipp2/luts/RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_4_VerySoft size_33 v1.13.cube' ocio_vendor_extensions/families/red_ipp2/luts/RED-IPP2_ACES_to_Rec709_MC_R4_VerySoft.clf --in-tf Log3G10 --in-gamut REDWideGamutRGB --cat Bradford` |
| RED IPP2 | `RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_1_Hard size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec2020_MC_R1_Hard.clf` | `aces-clf-baker 'ocio_vendor_extensions/families/red_ipp2/luts/RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_1_Hard size_33 v1.13.cube' ocio_vendor_extensions/families/red_ipp2/luts/RED-IPP2_ACES_to_Rec2020_MC_R1_Hard.clf --in-tf Log3G10 --in-gamut REDWideGamutRGB --cat Bradford` |
| RED IPP2 | `RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_2_Medium size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec2020_MC_R2_Medium.clf` | `aces-clf-baker 'ocio_vendor_extensions/families/red_ipp2/luts/RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_2_Medium size_33 v1.13.cube' ocio_vendor_extensions/families/red_ipp2/luts/RED-IPP2_ACES_to_Rec2020_MC_R2_Medium.clf --in-tf Log3G10 --in-gamut REDWideGamutRGB --cat Bradford` |
| RED IPP2 | `RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_3_Soft size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec2020_MC_R3_Soft.clf` | `aces-clf-baker 'ocio_vendor_extensions/families/red_ipp2/luts/RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_3_Soft size_33 v1.13.cube' ocio_vendor_extensions/families/red_ipp2/luts/RED-IPP2_ACES_to_Rec2020_MC_R3_Soft.clf --in-tf Log3G10 --in-gamut REDWideGamutRGB --cat Bradford` |
| RED IPP2 | `RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_4_VerySoft size_33 v1.13.cube` | `RED-IPP2_ACES_to_Rec2020_MC_R4_VerySoft.clf` | `aces-clf-baker 'ocio_vendor_extensions/families/red_ipp2/luts/RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_4_VerySoft size_33 v1.13.cube' ocio_vendor_extensions/families/red_ipp2/luts/RED-IPP2_ACES_to_Rec2020_MC_R4_VerySoft.clf --in-tf Log3G10 --in-gamut REDWideGamutRGB --cat Bradford` |

---

## Sony (2 forward-only)

Base directory: `ocio_vendor_extensions/families/sony/luts/`

| Family | Original LUT | CLF Output | Command |
| ------ | ------------- | ---------- | ------- |
| Sony | `SL3SG3tos709.cube` | `Sony_ACES_to_Rec709.clf` | `aces-clf-baker ocio_vendor_extensions/families/sony/luts/SL3SG3tos709.cube ocio_vendor_extensions/families/sony/luts/Sony_ACES_to_Rec709.clf --in-tf "S-Log3" --in-gamut "Venice S-Gamut3"` |
| Sony | `SL3SG3tosP3D65.cube` | `Sony_ACES_to_P3D65.clf` | `aces-clf-baker ocio_vendor_extensions/families/sony/luts/SL3SG3tosP3D65.cube ocio_vendor_extensions/families/sony/luts/Sony_ACES_to_P3D65.clf --in-tf "S-Log3" --in-gamut "Venice S-Gamut3"` |

---

## Verification

After baking, run:

```bash
python scripts/verify_clf_migration.py
```

This compares old versus new transform chains. Expected tolerance: max error **< 0.001** per display color space.

## Notes

- FilmLight intermediate assets (`FilmLight_TLog_EGamut2_2_FilmLight_Linear_EGamut2.cub`, `*.spimtx`) are **not** baked to CLF; they are replaced by analytical OCIO transforms.
- **Total CLF count:** 91 (6 ARRI + 15 DaVinci + 60 FilmLight + 8 RED + 2 Sony).
