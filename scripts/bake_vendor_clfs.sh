#!/usr/bin/env bash
set -euo pipefail

BAKER_CMD="${ACES_CLF_BAKER:-aces-clf-baker}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FAMILIES_DIR="$REPO_DIR/ocio_vendor_extensions/families"
BACKUP_DIR="$REPO_DIR/ocio_vendor_extensions/families_pre_clf"
SUCCESS=0
FAIL=0

bake() {
    local family="$1" input="$2" output="$3" in_tf="$4" in_gamut="$5"
    local src="$BACKUP_DIR/$family/luts/$input"
    local dst="$FAMILIES_DIR/$family/luts/$output"
    echo "  $input -> $output"
    if $BAKER_CMD "$src" "$dst" --in-tf "$in_tf" --in-gamut "$in_gamut"; then
        SUCCESS=$((SUCCESS + 1))
    else
        echo "  FAILED: $input" >&2
        FAIL=$((FAIL + 1))
    fi
}

bake_cat() {
    local family="$1" input="$2" output="$3" in_tf="$4" in_gamut="$5" cat="$6"
    local src="$BACKUP_DIR/$family/luts/$input"
    local dst="$FAMILIES_DIR/$family/luts/$output"
    echo "  $input -> $output"
    if $BAKER_CMD "$src" "$dst" --in-tf "$in_tf" --in-gamut "$in_gamut" --cat "$cat"; then
        SUCCESS=$((SUCCESS + 1))
    else
        echo "  FAILED: $input" >&2
        FAIL=$((FAIL + 1))
    fi
}

bake_matrix() {
    local family="$1" input="$2" output="$3" in_tf="$4" in_gamut="$5" matrix="$6"
    local src="$BACKUP_DIR/$family/luts/$input"
    local dst="$FAMILIES_DIR/$family/luts/$output"
    echo "  $input -> $output"
    if $BAKER_CMD "$src" "$dst" --in-tf "$in_tf" --in-gamut "$in_gamut" --in-matrix "$matrix"; then
        SUCCESS=$((SUCCESS + 1))
    else
        echo "  FAILED: $input" >&2
        FAIL=$((FAIL + 1))
    fi
}

# FilmLight E-Gamut 2: explicit matrices (CAT02, D60↔D65).
# E-Gamut 2 primaries: (0.83, 0.31), (0.15, 0.95), (0.065, -0.0805), D65 whitepoint.
# Vendor-defined RGB-to-XYZ matrix (6 dp precision), not derived from primaries.
# colour-science < 0.4.7 lacks E-Gamut 2, so explicit matrices are required.
FL_EGAMUT2_ACES_TO_GAMUT="1.259920633591235,-0.180662782264111,-0.079259355882615,0.004861246914694,0.944082819831840,0.051056395176724,0.121235969973557,0.046647078187213,0.832116647458241"
FL_EGAMUT2_GAMUT_TO_ACES="0.786790832021324,0.147306572413278,0.065903731351376,0.002154565536283,1.062853478210798,-0.065008551249527,-0.114752966624465,-0.081043763149851,1.195796958535971"

bake_inv_matrix() {
    local family="$1" input="$2" output="$3" out_tf="$4" out_gamut="$5" matrix="$6"
    local src="$BACKUP_DIR/$family/luts/$input"
    local dst="$FAMILIES_DIR/$family/luts/$output"
    echo "  $input -> $output"
    if $BAKER_CMD "$src" "$dst" --out-tf "$out_tf" --out-gamut "$out_gamut" --out-matrix "$matrix"; then
        SUCCESS=$((SUCCESS + 1))
    else
        echo "  FAILED: $input" >&2
        FAIL=$((FAIL + 1))
    fi
}

echo "=== ARRI (6 CLFs) ==="
bake arri "ARRI_LogC2Video_709_davinci3d_33.cube" "ARRI_ACES_to_Rec709_davinci3d_33.clf" "ARRI LogC3" "ARRI Wide Gamut 3"
bake arri "ARRI_LogC2Video_Classic709_davinci3d_33.cube" "ARRI_ACES_to_Rec709_Classic_davinci3d_33.clf" "ARRI LogC3" "ARRI Wide Gamut 3"
bake arri "ARRI_LogC2Video_P3D65_davinci3d_33.cube" "ARRI_ACES_to_P3D65_davinci3d_33.clf" "ARRI LogC3" "ARRI Wide Gamut 3"
bake arri "ARRI_LogC2Video_2020_davinci3d_33.cube" "ARRI_ACES_to_Rec2020_davinci3d_33.clf" "ARRI LogC3" "ARRI Wide Gamut 3"
bake arri "ARRI_LogC2Video_2100HLG-PW-1k-DW100_davinci3d_33.cube" "ARRI_ACES_to_Rec2100HLG_1000nits_davinci3d_33.clf" "ARRI LogC3" "ARRI Wide Gamut 3"
bake arri "ARRI_LogC2Video_2100PQ-PW-1k-DW100_davinci3d_33.cube" "ARRI_ACES_to_Rec2100PQ_1000nits_davinci3d_33.clf" "ARRI LogC3" "ARRI Wide Gamut 3"

echo ""
echo "=== DaVinci (15 CLFs) ==="
bake davinci "DVI-DVWG_to_Rec709-2_4y_x65.cube" "DaVinci_ACES_to_Rec709_2_4y.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_P3D65-2_6y_x65.cube" "DaVinci_ACES_to_P3D65_2_6y.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_sRGB_x65.cube" "DaVinci_ACES_to_sRGB.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_HLG-Rec2100_x65.cube" "DaVinci_ACES_to_HLG_Rec2100.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_Rec2020-2_4y_x65.cube" "DaVinci_ACES_to_Rec2020_2_4y.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_Rec2020-PQ108nits_x65.cube" "DaVinci_ACES_to_Rec2020_PQ108nits.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_Rec2020-PQ500nits_x65.cube" "DaVinci_ACES_to_Rec2020_PQ500nits.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_Rec2020-PQ1000nits_x65.cube" "DaVinci_ACES_to_Rec2020_PQ1000nits.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_Rec2020-PQ2000nits_x65.cube" "DaVinci_ACES_to_Rec2020_PQ2000nits.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_Rec2020-PQ4000nits_x65.cube" "DaVinci_ACES_to_Rec2020_PQ4000nits.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_P3D65-PQ108nits_x65.cube" "DaVinci_ACES_to_P3D65_PQ108nits.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_P3D65-PQ500nits_x65.cube" "DaVinci_ACES_to_P3D65_PQ500nits.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_P3D65-PQ1000nits_x65.cube" "DaVinci_ACES_to_P3D65_PQ1000nits.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_P3D65-PQ2000nits_x65.cube" "DaVinci_ACES_to_P3D65_PQ2000nits.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"
bake davinci "DVI-DVWG_to_P3D65-PQ4000nits_x65.cube" "DaVinci_ACES_to_P3D65_PQ4000nits.clf" "DaVinci Intermediate" "DaVinci Wide Gamut"

echo ""
echo "=== FilmLight forward (30 CLFs) ==="
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Video_Full.cub" "FilmLight_ACES_to_Rec709.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_UHDTV_Full.cub" "FilmLight_ACES_to_Rec2020.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_sRGB.cub" "FilmLight_ACES_to_sRGB.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_sRGB_Display.cub" "FilmLight_ACES_to_sRGB_Display.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_ACES_P3D60.cub" "FilmLight_ACES_to_P3D60.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DCI_P3D65.cub" "FilmLight_ACES_to_P3D65.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_P3.cub" "FilmLight_ACES_to_P3DCI.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DCI_XYZ.cub" "FilmLight_ACES_to_DCI_XYZ.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ.cub" "FilmLight_ACES_to_PQ_P3D65_4000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_108nits.cub" "FilmLight_ACES_to_PQ_P3D65_108nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_300nits.cub" "FilmLight_ACES_to_PQ_P3D65_300nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_600nits.cub" "FilmLight_ACES_to_PQ_P3D65_600nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1000nits.cub" "FilmLight_ACES_to_PQ_P3D65_1000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1600nits.cub" "FilmLight_ACES_to_PQ_P3D65_1600nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_2000nits.cub" "FilmLight_ACES_to_PQ_P3D65_2000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_5000nits.cub" "FilmLight_ACES_to_PQ_P3D65_5000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_10000nits.cub" "FilmLight_ACES_to_PQ_P3D65_10000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_XYZ_108nits.cub" "FilmLight_ACES_to_PQ_XYZ_108nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_DCI_PQ_XYZ_300nits.cub" "FilmLight_ACES_to_PQ_XYZ_300nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020.cub" "FilmLight_ACES_to_PQ_Rec2020_1000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_108nits.cub" "FilmLight_ACES_to_PQ_Rec2020_108nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_300nits.cub" "FilmLight_ACES_to_PQ_Rec2020_300nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_600nits.cub" "FilmLight_ACES_to_PQ_Rec2020_600nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_1600nits.cub" "FilmLight_ACES_to_PQ_Rec2020_1600nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_2000nits.cub" "FilmLight_ACES_to_PQ_Rec2020_2000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_4000nits.cub" "FilmLight_ACES_to_PQ_Rec2020_4000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_5000nits.cub" "FilmLight_ACES_to_PQ_Rec2020_5000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_10000nits.cub" "FilmLight_ACES_to_PQ_Rec2020_10000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000.cub" "FilmLight_ACES_to_HLG_Rec2020_1000nits.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"
bake_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000_PreviewSDR.cub" "FilmLight_ACES_to_HLG_Rec2020_PreviewSDR.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_ACES_TO_GAMUT"

echo ""
echo "=== FilmLight inverse (30 CLFs) ==="
# Inverse cubes go display → T-Log/E-Gamut 2, so the shaper goes on the OUTPUT side:
#   [inverse 3D LUT] → [T-Log decode] → [E-Gamut 2 → ACES matrix]
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Video_Full_inv.cub" "FilmLight_ACES_to_Rec709_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_UHDTV_Full_inv.cub" "FilmLight_ACES_to_Rec2020_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_sRGB_inv.cub" "FilmLight_ACES_to_sRGB_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_sRGB_Display_inv.cub" "FilmLight_ACES_to_sRGB_Display_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_ACES_P3D60_inv.cub" "FilmLight_ACES_to_P3D60_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DCI_P3D65_inv.cub" "FilmLight_ACES_to_P3D65_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_P3_inv.cub" "FilmLight_ACES_to_P3DCI_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DCI_XYZ_inv.cub" "FilmLight_ACES_to_DCI_XYZ_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_inv.cub" "FilmLight_ACES_to_PQ_P3D65_4000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_108nits_inv.cub" "FilmLight_ACES_to_PQ_P3D65_108nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_300nits_inv.cub" "FilmLight_ACES_to_PQ_P3D65_300nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_600nits_inv.cub" "FilmLight_ACES_to_PQ_P3D65_600nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1000nits_inv.cub" "FilmLight_ACES_to_PQ_P3D65_1000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_1600nits_inv.cub" "FilmLight_ACES_to_PQ_P3D65_1600nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_2000nits_inv.cub" "FilmLight_ACES_to_PQ_P3D65_2000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_5000nits_inv.cub" "FilmLight_ACES_to_PQ_P3D65_5000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_P3D65_10000nits_inv.cub" "FilmLight_ACES_to_PQ_P3D65_10000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DolbyPQ_XYZ_108nits_inv.cub" "FilmLight_ACES_to_PQ_XYZ_108nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_DCI_PQ_XYZ_300nits_inv.cub" "FilmLight_ACES_to_PQ_XYZ_300nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_inv.cub" "FilmLight_ACES_to_PQ_Rec2020_1000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_108nits_inv.cub" "FilmLight_ACES_to_PQ_Rec2020_108nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_300nits_inv.cub" "FilmLight_ACES_to_PQ_Rec2020_300nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_600nits_inv.cub" "FilmLight_ACES_to_PQ_Rec2020_600nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_1600nits_inv.cub" "FilmLight_ACES_to_PQ_Rec2020_1600nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_2000nits_inv.cub" "FilmLight_ACES_to_PQ_Rec2020_2000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_4000nits_inv.cub" "FilmLight_ACES_to_PQ_Rec2020_4000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_5000nits_inv.cub" "FilmLight_ACES_to_PQ_Rec2020_5000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2084_Rec2020_10000nits_inv.cub" "FilmLight_ACES_to_PQ_Rec2020_10000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000_inv.cub" "FilmLight_ACES_to_HLG_Rec2020_1000nits_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"
bake_inv_matrix filmlight "FilmLight_TLog_EGamut2_2_Rec2100_HLG_2020_1000_PreviewSDR_inv.cub" "FilmLight_ACES_to_HLG_Rec2020_PreviewSDR_inv.clf" "T-Log" "FilmLight E-Gamut" "$FL_EGAMUT2_GAMUT_TO_ACES"

echo ""
echo "=== RED IPP2 (8 CLFs) ==="
bake_cat red_ipp2 "RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_1_Hard size_33 v1.13.cube" "RED-IPP2_ACES_to_Rec709_MC_R1_Hard.clf" "Log3G10" "REDWideGamutRGB" "Bradford"
bake_cat red_ipp2 "RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_2_Medium size_33 v1.13.cube" "RED-IPP2_ACES_to_Rec709_MC_R2_Medium.clf" "Log3G10" "REDWideGamutRGB" "Bradford"
bake_cat red_ipp2 "RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_3_Soft size_33 v1.13.cube" "RED-IPP2_ACES_to_Rec709_MC_R3_Soft.clf" "Log3G10" "REDWideGamutRGB" "Bradford"
bake_cat red_ipp2 "RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_4_VerySoft size_33 v1.13.cube" "RED-IPP2_ACES_to_Rec709_MC_R4_VerySoft.clf" "Log3G10" "REDWideGamutRGB" "Bradford"
bake_cat red_ipp2 "RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_1_Hard size_33 v1.13.cube" "RED-IPP2_ACES_to_Rec2020_MC_R1_Hard.clf" "Log3G10" "REDWideGamutRGB" "Bradford"
bake_cat red_ipp2 "RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_2_Medium size_33 v1.13.cube" "RED-IPP2_ACES_to_Rec2020_MC_R2_Medium.clf" "Log3G10" "REDWideGamutRGB" "Bradford"
bake_cat red_ipp2 "RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_3_Soft size_33 v1.13.cube" "RED-IPP2_ACES_to_Rec2020_MC_R3_Soft.clf" "Log3G10" "REDWideGamutRGB" "Bradford"
bake_cat red_ipp2 "RWG_Log3G10 to REC2020_BT1886 with MEDIUM_CONTRAST and R_4_VerySoft size_33 v1.13.cube" "RED-IPP2_ACES_to_Rec2020_MC_R4_VerySoft.clf" "Log3G10" "REDWideGamutRGB" "Bradford"

echo ""
echo "=== Sony (2 CLFs) ==="
bake sony "SL3SG3tos709.cube" "Sony_ACES_to_Rec709.clf" "S-Log3" "Venice S-Gamut3"
bake sony "SL3SG3tosP3D65.cube" "Sony_ACES_to_P3D65.clf" "S-Log3" "Venice S-Gamut3"

echo ""
echo "=== Done ==="
echo "  Success: $SUCCESS"
echo "  Failed:  $FAIL"
