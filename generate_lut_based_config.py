#!/usr/bin/env python3
"""
Generate a CLF-based OCIO 2.3 config from an official ACES 2.0 OCIO v2.4 or v2.5 config.

Each ACES 2.0 view transform is written as a self-contained CLF file with the
structure:  Matrix (AP0->AP1) + Log (ACEScct encode) + LUT3D (ACEScct->CIE-XYZ-D65)

The Matrix and Log operators are analytical (extracted from the ACEScct BuiltIn),
so only the nonlinear tone-mapping core is baked into the 3D LUT.  The CLF takes
ACES2065-1 in and produces CIE-XYZ-D65 out -- fully self-contained, no external
BuiltinTransform dependency.

Inverse CLFs (--inv-encoding, all use native OCIO/CLF Log where possible):
  The XYZ-D65 -> AP0 matrix is extracted from the LUT and applied analytically,
  so the 3D LUT operates in AP0 display-linear space (better interpolation).
  A gamma shaper spreads shadows before the LUT for better resolution.

  acescc (default): Matrix(XYZ->AP0) + Gamma + LUT3D + Range + Log + Matrix(AP1->AP0).
  acescct:           Matrix(XYZ->AP0) + Gamma + LUT3D + Range + LogCamera + Matrix.
  extended-log:      Matrix(XYZ->AP0) + Gamma + LUT3D + Log + Matrix.
  camera-log:        Matrix(XYZ->AP0) + Gamma + LUT3D + Range + LogCamera + Matrix.
  jplog2:            Matrix(XYZ->AP0) + Gamma + LUT3D + LUT1D + Matrix.

Compatible with any OCIO >= 2.0 runtime (CLF v3 standard operators only).

BuiltIns requiring OCIO > 2.3 are replaced:
  - ACES 2.0 view transforms -> CLF files (Matrix + Log + LUT3D)
  - DisplayP3-HDR display -> analytical Matrix + EOTF
  - Apple Log curve and CSC -> baked 1D LUTs
All other BuiltIns (DisplayP3, Canon CLog, ARRI LogC, etc.) are native at v2.3.

Usage:
    python3 generate_lut_based_config.py <reference_v24_or_v25_config> [-o DIR] [--inv-encoding acescct|acescc|...] ...

Requires: PyOpenColorIO >= 2.4, numpy.
"""

import argparse
import math
import os
import re
import shutil
import sys
import textwrap
from dataclasses import replace
import xml.etree.ElementTree as ET

import numpy as np
import PyOpenColorIO as ocio

from inverse_pseudolog import (
    PseudoLogParams,
    build_decode_lut1d,
    build_encode_lut1d,
    make_range_lin_to_unit,
)


BUILTIN_BAKE_CONFIG = "studio-config-v4.0.0_aces-v2.0_ocio-v2.5"

CURVE_BUILTINS_TO_BAKE = {
    "CURVE - APPLE_LOG_to_LINEAR": "CURVE_AppleLog_to_Linear",
}

CSC_BUILTINS_TO_BAKE = {
    "APPLE_LOG_to_ACES2065-1": "CSC_AppleLog_to_ACES2065-1",
}

# v2.2+ builtins that need baking for v2.1 downgrade (Canon, etc.)
CURVE_BUILTINS_V22 = {
    "CURVE - CANON_CLOG2_to_LINEAR": "CURVE_CanonCLog2_to_Linear",
    "CURVE - CANON_CLOG3_to_LINEAR": "CURVE_CanonCLog3_to_Linear",
}

CSC_BUILTINS_V22 = {
    "CANON_CLOG2-CGAMUT_to_ACES2065-1": "CSC_CanonCLog2CGamut_to_ACES2065-1",
    "CANON_CLOG3-CGAMUT_to_ACES2065-1": "CSC_CanonCLog3CGamut_to_ACES2065-1",
    "ARRI_LOGC4_to_ACES2065-1": "CSC_ArriLogC4_to_ACES2065-1",
}

# BT.2020 (Linear Rec.2020) to ACES2065-1 (AP0) matrix — from the official
# ACES v2.0 config.  Used inline to replace ColorSpaceTransform references to
# "Linear Rec.2020" which doesn't exist in reference configs.
BT2020_TO_AP0_MATRIX_YAML = (
    "0.679085634706913, 0.157700914643159, 0.163213450649929, 0, "
    "0.0460020030800595, 0.859054673002905, 0.0949433239170316, 0, "
    "-0.000573943187616201, 0.0284677684080262, 0.972106174779585, 0, "
    "0, 0, 0, 1"
)

XYZ_D65_TO_REC709_MATRIX = (
    "3.2409699419045, -1.5373831775701, -0.4986107602930, 0, "
    "-0.9692436362809, 1.8759675015077, 0.0415550574072, 0, "
    "0.0556300796970, -0.2039769588890, 1.0569715142429, 0, "
    "0, 0, 0, 1"
)
XYZ_D65_TO_P3D65_MATRIX = (
    "2.4934969119414, -0.9313836179191, -0.4027107844507, 0, "
    "-0.8294889695616, 1.7626640603183, 0.0236246858419, 0, "
    "0.0358458302438, -0.076172389268, 0.9568845240077, 0, "
    "0, 0, 0, 1"
)
XYZ_D65_TO_REC2020_MATRIX = (
    "1.7166511879713, -0.3556707837764, -0.2533662813737, 0, "
    "-0.6666843518325, 1.6164812366349, 0.0157685458139, 0, "
    "0.0176398574453, -0.0427706132578, 0.9421031212355, 0, "
    "0, 0, 0, 1"
)

# v2.5-only DISPLAY builtins (MIRROR NEGS variants, not available in OCIO 2.4).
# These are replaced with analytical Matrix + EOTF when downgrading to v2.4.
DISPLAY_BUILTIN_REPLACEMENTS_V25 = {
    "DISPLAY - CIE-XYZ-D65_to_sRGB - MIRROR NEGS": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to sRGB (mirror negs)\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_REC709_MATRIX}]}}\n"
        "        - !<ExponentWithLinearTransform> {gamma: 2.4, offset: 0.055, direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_G2.2-REC.709 - MIRROR NEGS": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Gamma 2.2 Rec.709 (mirror negs)\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_REC709_MATRIX}]}}\n"
        "        - !<ExponentTransform> {value: [2.2, 2.2, 2.2, 1], direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_G2.6-P3-D65 - MIRROR NEGS": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Gamma 2.6 P3-D65 (mirror negs)\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_P3D65_MATRIX}]}}\n"
        "        - !<ExponentTransform> {value: [2.6, 2.6, 2.6, 1], direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_REC.1886-REC.709 - MIRROR NEGS": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Rec.1886 Rec.709 (mirror negs)\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_REC709_MATRIX}]}}\n"
        "        - !<ExponentTransform> {value: [2.4, 2.4, 2.4, 1], direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_REC.1886-REC.2020 - MIRROR NEGS": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Rec.1886 Rec.2020 (mirror negs)\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_REC2020_MATRIX}]}}\n"
        "        - !<ExponentTransform> {value: [2.4, 2.4, 2.4, 1], direction: inverse}"
    ),
}

# Replacements always applied (v2.4+ builtins not in v2.3).
# Note: the MIRROR NEGS entries here overlap with DISPLAY_BUILTIN_REPLACEMENTS_V25
# above; both are needed because the v2.3 path applies them from this dict while
# the v2.4 path uses the dedicated V25 dict.
DISPLAY_BUILTIN_REPLACEMENTS = {
    "DISPLAY - CIE-XYZ-D65_to_DisplayP3-HDR": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Display P3 HDR\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_P3D65_MATRIX}]}}\n"
        "        - !<ExponentWithLinearTransform> {gamma: 2.4, offset: 0.055, direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_sRGB - MIRROR NEGS": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to sRGB (mirror negs)\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_REC709_MATRIX}]}}\n"
        "        - !<ExponentWithLinearTransform> {gamma: 2.4, offset: 0.055, direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_G2.2-REC.709 - MIRROR NEGS": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Gamma 2.2 Rec.709 (mirror negs)\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_REC709_MATRIX}]}}\n"
        "        - !<ExponentTransform> {value: [2.2, 2.2, 2.2, 1], direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_G2.6-P3-D65 - MIRROR NEGS": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Gamma 2.6 P3-D65 (mirror negs)\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_P3D65_MATRIX}]}}\n"
        "        - !<ExponentTransform> {value: [2.6, 2.6, 2.6, 1], direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_REC.1886-REC.709 - MIRROR NEGS": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Rec.1886 Rec.709 (mirror negs)\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_REC709_MATRIX}]}}\n"
        "        - !<ExponentTransform> {value: [2.4, 2.4, 2.4, 1], direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_DCDM-D65": (
        "!<ExponentTransform> {value: [2.6, 2.6, 2.6, 1], direction: inverse}"
    ),
}

# Additional replacements for v2.1 (these DISPLAY builtins require v2.3+).
DISPLAY_BUILTIN_REPLACEMENTS_V21 = {
    "DISPLAY - CIE-XYZ-D65_to_sRGB": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to sRGB\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_REC709_MATRIX}]}}\n"
        "        - !<ExponentWithLinearTransform> {gamma: 2.4, offset: 0.055, direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_DisplayP3": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Display P3\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_P3D65_MATRIX}]}}\n"
        "        - !<ExponentWithLinearTransform> {gamma: 2.4, offset: 0.055, direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_G2.6-P3-D65": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Gamma 2.6 P3-D65\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_P3D65_MATRIX}]}}\n"
        "        - !<ExponentTransform> {value: [2.6, 2.6, 2.6, 1], direction: inverse}"
    ),
    "DISPLAY - CIE-XYZ-D65_to_REC.1886-REC.709": (
        "!<GroupTransform>\n"
        "      name: CIE XYZ-D65 to Rec.1886 Rec.709\n"
        "      children:\n"
        f"        - !<MatrixTransform> {{matrix: [{XYZ_D65_TO_REC709_MATRIX}]}}\n"
        "        - !<ExponentTransform> {value: [2.4, 2.4, 2.4, 1], direction: inverse}"
    ),
}

# v2.4+ DISPLAY builtins needing 1D LUTs (always replaced, even for v2.3).
DISPLAY_BUILTINS_NEEDING_1D_LUT = {
    "DISPLAY - CIE-XYZ-D65_to_ST2084-DCDM-D65": {
        "name": "CIE XYZ-D65 to ST2084 DCDM-D65",
        "matrix": None,
        "lut_name": "EOTF_PQ_inv",
    },
}

# PQ/HLG DISPLAY builtins that need baked 1D LUTs for v2.1 (EOTF is not a simple power).
DISPLAY_BUILTINS_NEEDING_1D_LUT_V21 = {
    "DISPLAY - CIE-XYZ-D65_to_REC.2100-PQ": {
        "name": "CIE XYZ-D65 to Rec.2100 PQ",
        "matrix": XYZ_D65_TO_REC2020_MATRIX,
        "lut_name": "EOTF_PQ_inv",
    },
    "DISPLAY - CIE-XYZ-D65_to_ST2084-P3-D65": {
        "name": "CIE XYZ-D65 to ST2084 P3-D65",
        "matrix": XYZ_D65_TO_P3D65_MATRIX,
        "lut_name": "EOTF_PQ_inv",
    },
    "DISPLAY - CIE-XYZ-D65_to_REC.2100-HLG-1000nit": {
        "name": "CIE XYZ-D65 to Rec.2100 HLG 1000 nit",
        "matrix": XYZ_D65_TO_REC2020_MATRIX,
        "lut_name": "EOTF_HLG1000_inv",
    },
}

TEMP_DISPLAY = '__VT_Bake__'
TEMP_PASSTHROUGH_CS = '__CIE-XYZ-D65-Passthrough__'
TEMP_INVERSE_CS = '__inverse_temp__'
# Display-referred bake source: inverse VT maps this space -> AP0 (to_reference).
INVERSE_LUT_DISPLAY_SRC = '__inverse_lut_display_src__'
# ACEScct-domain bake: temp scene-referred CS for forward/inverse LUT baking.
TEMP_ACESCCT_FWD_CS = '__acescct_fwd_bake__'
TEMP_ACESCCT_INV_CS = '__acescct_inv_bake__'
TEMP_DISPSHAPER_FWD_CS = '__dispshaper_fwd_bake__'
TEMP_DISPSHAPER_INV_CS = '__dispshaper_inv_bake__'

# Inverse LUT input shaper: a power curve applied to AP0 display-linear
# values before they enter the 3D LUT.  Without this, the entire shadow region
# (AP1 Y < 0.05 → display-linear < 0.0002) collapses into a fraction of one
# LUT cell, giving zero interpolation resolution.  A gamma-2 encode spreads
# shadows across ~1.4% of the domain (√0.0002 ≈ 0.014) instead of 0.02%,
# gaining roughly 70× more LUT samples in the critical shadow region.
# Set to 1.0 to disable the shaper (classic mode).
INV_SHAPER_GAMMA = 2.0

ACESCC_MIN = -0.3584
ACESCC_MAX = 0.78
ACESCC_REMAP_CS = '__acescc_remap__'


def _make_remap_to01_from01(cmin: float, cmax: float):
    """Map log/camera code [cmin,cmax] <-> [0,1] via OCIO Range (CLF-safe)."""
    if cmax <= cmin:
        raise ValueError("remap requires cmin < cmax")
    r1 = ocio.RangeTransform()
    r1.setMinInValue(cmin)
    r1.setMaxInValue(cmax)
    r1.setMinOutValue(0.0)
    r1.setMaxOutValue(1.0)
    r2 = ocio.RangeTransform()
    r2.setMinInValue(0.0)
    r2.setMaxInValue(1.0)
    r2.setMinOutValue(cmin)
    r2.setMaxOutValue(cmax)
    return r1, r2

# Full ACEScc (with linear toe): break at 2^-15, then (log2(x)+9.72)/17.52
# Linear segment slope = 1/(2^-15 * ln(2) * 17.52) for continuity.
ACESCC_LIN_BREAK = 2.0 ** -15  # 3.05176e-05
ACESCC_LOG_SLOPE = 1.0 / 17.52
ACESCC_LOG_OFFSET = 9.72 / 17.52
# At break: log_val = (log2(2^-15)+9.72)/17.52 = -5.28/17.52
ACESCC_LINEAR_SLOPE = ACESCC_LOG_SLOPE / (ACESCC_LIN_BREAK * math.log(2))  # ~0.0570776

# ACEScct: explicit LogCamera (CLF cameraLinToLog) matching OCIO BuiltIn ACEScct_to_ACES2065-1 — no LUT.
ACESCT_LIN_BREAK = 0.0078125
ACESCT_LOG_SLOPE = 0.05707762557077626
ACESCT_LOG_OFFSET = 0.554794520547945
# AP0<->AP1 matrices from same BuiltIn (scene-referred neutral path)
ACESCT_M_AP0_AP1 = [
    1.451439316145665,
    -0.2365107468937401,
    -0.2149285692519253,
    0.0,
    -0.07655377339602056,
    1.176229699833573,
    -0.09967592643755221,
    0.0,
    0.008316148425697719,
    -0.006032449791021027,
    0.9977163013653234,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
]
ACESCT_M_AP1_AP0 = [
    0.6954522413574519,
    0.1406786964702942,
    0.1638690621722541,
    0.0,
    0.04479456337203772,
    0.8596711184564217,
    0.0955343181715404,
    0.0,
    -0.005525882558113544,
    0.004025210305978659,
    1.001500672252135,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
]


def sanitize_lut_filename(name):
    """Create a clean, filesystem-safe filename from a view transform name.

    'ACES 2.0 - SDR 100 nits (Rec.709)' -> 'ACES2.0-SDR-100nit-Rec709'
    """
    name = name.replace(' nits ', 'nit-')
    name = name.replace('ACES 2.0 - ', 'ACES2.0-')
    name = re.sub(r'\(([^)]+)\)', r'\1', name)  # remove parens, keep content
    name = name.replace('.', '')
    name = re.sub(r'\s+', '-', name.strip())
    name = re.sub(r'-+', '-', name)
    return name


FWD_OP_DESCRIPTIONS = [
    "ACES AP0 to AP1 matrix",
    "Linear to ACEScct log",
    "3D LUT - ACEScct to CIE-XYZ-D65",
]

# Inverse: XYZ->AP0 matrix + shaper + LUT3D (in AP0 display-linear) + decode ops.
# The analytical XYZ->AP0 matrix is extracted from the baked LUT, reducing
# cross-channel interpolation error by letting the LUT operate in AP0 space.
INV_OP_DESCRIPTIONS = [
    "CIE-XYZ-D65 to ACES AP0 matrix (analytical, extracted from LUT)",
    f"Gamma {INV_SHAPER_GAMMA} shaper (AP0 display-linear to perceptual for LUT)",
    "3D LUT - shaped AP0 display to remapped ACEScc domain",
    "Normalized [0,1] to ACEScc code range",
    "Log (ACEScc cameraLogToLin, linear toe + log)",
    "ACES AP1 to AP0 matrix",
]

INV_OP_DESCRIPTIONS_ACESCT = [
    "CIE-XYZ-D65 to ACES AP0 matrix (analytical, extracted from LUT)",
    f"Gamma {INV_SHAPER_GAMMA} shaper (AP0 display-linear to perceptual for LUT)",
    "3D LUT - shaped AP0 display to remapped ACEScct code domain",
    "Range normalized [0,1] to ACEScct log code",
    "Log (ACEScct cameraLogToLin)",
    "ACES AP1 to AP0 matrix",
]

INV_OP_DESCRIPTIONS_CAMERA_LOG = [
    "CIE-XYZ-D65 to ACES AP0 matrix (analytical, extracted from LUT)",
    f"Gamma {INV_SHAPER_GAMMA} shaper (AP0 display-linear to perceptual for LUT)",
    "3D LUT - shaped AP0 display to remapped camera-log domain",
    "Range [0,1] to camera log code",
    "Log (camera log to linear AP1)",
    "ACES AP1 to AP0 matrix",
]

INV_OP_DESCRIPTIONS_EXTENDED_LOG = [
    "CIE-XYZ-D65 to ACES AP0 matrix (analytical, extracted from LUT)",
    f"Gamma {INV_SHAPER_GAMMA} shaper (AP0 display-linear to perceptual for LUT)",
    "3D LUT - shaped AP0 display to extended-log domain",
    "Log (normalized [0,1] to linear AP1)",
    "ACES AP1 to AP0 matrix",
]

INV_OP_DESCRIPTIONS_JPLOG = [
    "CIE-XYZ-D65 to ACES AP0 matrix (analytical, extracted from LUT)",
    f"Gamma {INV_SHAPER_GAMMA} shaper (AP0 display-linear to perceptual for LUT)",
    "3D LUT - shaped AP0 display to pseudo-log domain",
    "LUT1D - JPlog2-style decode (norm to AP1 linear)",
    "ACES AP1 to AP0 matrix",
]

PSEUDOLOG_1D_LENGTH = 4096

# CLF process elements that carry inBitDepth / outBitDepth (ASC ST 2065-4).
_CLF_BITDEPTH_TAGS = frozenset(
    {
        "Matrix",
        "Log",
        "LUT1D",
        "LUT3D",
        "Range",
        "Exponent",
        "ExposureContrast",
        "ASC_CDL",
        "GradingPrimary",
    }
)


def enforce_clf_ops_32f(root: ET.Element) -> None:
    """Set inBitDepth/outBitDepth to 32f on every supported process op under ProcessList."""
    for el in root.iter():
        if el.tag in _CLF_BITDEPTH_TAGS:
            el.set("inBitDepth", "32f")
            el.set("outBitDepth", "32f")


def postprocess_clf(clf_path, name, clf_id, input_desc, output_desc, op_descriptions):
    """Add proper metadata to a CLF file generated by OCIO's GroupTransform.write()."""
    tree = ET.parse(clf_path)
    root = tree.getroot()

    root.set('name', name)
    root.set('id', clf_id)

    first_child = list(root)[0]
    in_el = ET.Element('InputDescriptor')
    in_el.text = input_desc
    out_el = ET.Element('OutputDescriptor')
    out_el.text = output_desc
    root.insert(0, out_el)
    root.insert(0, in_el)

    ops = [el for el in root if el.tag in ('Matrix', 'Log', 'LUT3D', 'LUT1D', 'Range', 'Exponent')]
    for op, desc in zip(ops, op_descriptions):
        desc_el = ET.Element('Description')
        desc_el.text = desc
        op.insert(0, desc_el)

    enforce_clf_ops_32f(root)

    ET.indent(tree, space='    ')
    tree.write(clf_path, xml_declaration=True, encoding='UTF-8')


def apply_processor_to_pixels(processor, pixels):
    """Apply an OCIO CPU processor to an array of RGB float pixels."""
    cpu = processor.getDefaultCPUProcessor()
    result = pixels.copy()
    buf = ocio.PackedImageDesc(result, len(result), 1, 3)
    cpu.apply(buf)
    return result


def write_spi1d_lut(filepath, input_values, output_values):
    """Write a 1D LUT in .spi1d format."""
    n = len(input_values)
    in_min = float(input_values[0])
    in_max = float(input_values[-1])
    with open(filepath, 'w') as f:
        f.write("Version 1\n")
        f.write(f"From {in_min} {in_max}\n")
        f.write(f"Length {n}\n")
        f.write("Components 1\n")
        f.write("{\n")
        for val in output_values:
            f.write(f"        {val:.10f}\n")
        f.write("}\n")


def get_aces2_view_transforms(config):
    """Get all ACES 2.0 view transform names and their BuiltIn styles."""
    vt_list = []
    for vt in config.getViewTransforms():
        name = vt.getName()
        if 'Un-tone-mapped' in name:
            continue
        transform = vt.getTransform(ocio.VIEWTRANSFORM_DIR_FROM_REFERENCE)
        if isinstance(transform, ocio.BuiltinTransform):
            style = transform.getStyle()
            if 'ACES-OUTPUT' in style and '_2.0' in style:
                vt_list.append((name, style))
    return vt_list


def _sync_view_transforms(bake_cfg, template_cfg):
    """Copy ACES 2.0 ViewTransforms from *template_cfg* into *bake_cfg*.

    The Baker resolves VT names against the config's registered
    ViewTransforms.  When the bake config is a built-in (e.g. studio)
    it may lack VTs present in the template (e.g. reference D60 variants).
    All underlying BuiltinTransform styles are in the OCIO registry, so
    adding the VT objects is sufficient.
    """
    bake_vt_names = {vt.getName() for vt in bake_cfg.getViewTransforms()}
    added = 0
    for vt in template_cfg.getViewTransforms():
        if vt.getName() not in bake_vt_names:
            bake_cfg.addViewTransform(vt)
            added += 1
    if added:
        print(f"  Synced {added} extra ViewTransform(s) into bake config")


def get_acescct_encode_ops(config=None):
    """
    ACES2065-1 -> ACEScct: Matrix (AP0->AP1) + LogCamera (CLF cameraLinToLog).

    Built explicitly so inverse/forward CLFs use native Log ops, not BuiltIn LUT paths.
    """
    m = ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1)
    log_enc = ocio.LogCameraTransform(
        [ACESCT_LIN_BREAK] * 3,
        base=2.0,
        logSideSlope=[ACESCT_LOG_SLOPE] * 3,
        logSideOffset=[ACESCT_LOG_OFFSET] * 3,
        linSideSlope=[1.0] * 3,
        linSideOffset=[0.0] * 3,
        linearSlope=[],
    )
    return m, log_enc


def get_acescct_decode_ops(config=None):
    """
    ACEScct -> ACES2065-1: LogCamera inverse (cameraLogToLin) + Matrix (AP1->AP0).
    """
    log_dec = ocio.LogCameraTransform(
        [ACESCT_LIN_BREAK] * 3,
        base=2.0,
        logSideSlope=[ACESCT_LOG_SLOPE] * 3,
        logSideOffset=[ACESCT_LOG_OFFSET] * 3,
        linSideSlope=[1.0] * 3,
        linSideOffset=[0.0] * 3,
        linearSlope=[],
        direction=ocio.TRANSFORM_DIR_INVERSE,
    )
    m = ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0)
    return log_dec, m


def get_acescct_remap_clf_ops(
    config,
    ap0_gray_min: float = 1e-8,
    ap0_gray_max: float = 65504.0,
    inv_remap_mode: str = "range",
):
    """
    Inverse LUT domain: normalized [0,1] <-> ACEScct log code (same LogCamera as forward).

    Uses neutral AP0 gray endpoints to define code range for Range (like camera-log).
    """
    if ap0_gray_max <= ap0_gray_min or ap0_gray_min <= 0:
        raise ValueError("acescct remap requires 0 < ap0_gray_min < ap0_gray_max")

    ap0_to_ap1, log_enc = get_acescct_encode_ops(config)
    log_dec, ap1_to_ap0 = get_acescct_decode_ops(config)

    g = ocio.GroupTransform()
    g.appendTransform(ap0_to_ap1)
    g.appendTransform(log_enc)
    proc = config.getProcessor(g)
    cpu = proc.getDefaultCPUProcessor()

    def _code(gray: float) -> float:
        p = np.array([[gray, gray, gray]], dtype=np.float32)
        cpu.apply(ocio.PackedImageDesc(p.ravel(), 1, 1, 3))
        return float(p[0, 0])

    c_lo = _code(ap0_gray_min)
    c_hi = _code(ap0_gray_max)
    code_min = min(c_lo, c_hi)
    code_max = max(c_lo, c_hi)
    if code_max <= code_min:
        raise ValueError("ACEScct code range collapsed; widen ap0_gray_min/max")

    if inv_remap_mode == "none":
        encode_ops = [ap0_to_ap1, log_enc]
        decode_ops = [log_dec, ap1_to_ap0]
        return encode_ops, decode_ops
    to01, from01 = _make_remap_to01_from01(code_min, code_max)
    encode_ops = [ap0_to_ap1, log_enc, to01]
    decode_ops = [from01, log_dec, ap1_to_ap0]
    return encode_ops, decode_ops


def setup_acescct_remap_cs(
    config,
    ap0_gray_min: float = 1e-8,
    ap0_gray_max: float = 65504.0,
    inv_remap_mode: str = "range",
):
    """Remap CS <-> ACES2065-1 via ACEScct LogCamera (+ optional remap to [0,1] for LUT)."""
    enc_ops, dec_ops = get_acescct_remap_clf_ops(
        config, ap0_gray_min, ap0_gray_max, inv_remap_mode
    )
    ap0_to_ap1 = enc_ops[0]
    log_encode = enc_ops[1]

    existing = config.getColorSpace(ACESCC_REMAP_CS)
    if existing:
        config.removeColorSpace(ACESCC_REMAP_CS)

    g_to = ocio.GroupTransform()
    for op in dec_ops:
        g_to.appendTransform(op)

    g_from = ocio.GroupTransform()
    g_from.appendTransform(ap0_to_ap1)
    g_from.appendTransform(log_encode)
    if len(enc_ops) > 2:
        g_from.appendTransform(enc_ops[2])

    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_DISPLAY, ACESCC_REMAP_CS)
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)
    config.addColorSpace(cs)


def get_acescc_clf_ops(config=None, inv_remap_mode: str = "range"):
    """
    ACEScc for inverse CLF + bake: **LogCamera** (CLF cameraLinToLog / cameraLogToLin), not
    LogAffine and not BuiltIn ACEScc_to_ACES2065-1 (internal LUT). Piecewise linear toe
    at 2^-15 + log segment per AMPAS ACEScc.
    inv_remap_mode: range | matrix | none (none: LUT carries raw ACEScc codes).
    """
    ap0_to_ap1 = ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1)
    ap1_to_ap0 = ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0)

    log_encode = ocio.LogCameraTransform(
        [ACESCC_LIN_BREAK] * 3,
        base=2.0,
        logSideSlope=[ACESCC_LOG_SLOPE] * 3,
        logSideOffset=[ACESCC_LOG_OFFSET] * 3,
        linSideSlope=[1.0] * 3,
        linSideOffset=[0.0] * 3,
        linearSlope=[],
    )
    log_decode = ocio.LogCameraTransform(
        [ACESCC_LIN_BREAK] * 3,
        base=2.0,
        logSideSlope=[ACESCC_LOG_SLOPE] * 3,
        logSideOffset=[ACESCC_LOG_OFFSET] * 3,
        linSideSlope=[1.0] * 3,
        linSideOffset=[0.0] * 3,
        linearSlope=[],
        direction=ocio.TRANSFORM_DIR_INVERSE,
    )

    if inv_remap_mode == "none":
        return [ap0_to_ap1, log_encode], [log_decode, ap1_to_ap0]
    to01, from01 = _make_remap_to01_from01(ACESCC_MIN, ACESCC_MAX)
    encode_ops = [ap0_to_ap1, log_encode, to01]
    decode_ops = [from01, log_decode, ap1_to_ap0]
    return encode_ops, decode_ops


def get_acescc_full_clf_ops(config=None, inv_remap_mode: str = "range"):
    """Alias for get_acescc_clf_ops (ACEScc is always LogCamera in CLF)."""
    return get_acescc_clf_ops(config, inv_remap_mode)


def get_extended_log_clf_ops(config, lin_min: float, lin_max: float):
    """
    Inverse CLF ops using a single native Log (OCIO LogAffine / CLF linToLog).
    Maps AP1 linear [lin_min, lin_max] directly to [0,1] so no Range is needed;
    more highlight headroom than ACEScc when lin_max is large (e.g. 65504).

    Formula: norm = log2(lin/lin_min) / log2(lin_max/lin_min).
    Pipeline: Matrix, Matrix, Log(linToLog), LUT3D, Log(logToLin), Matrix (7 ops).
    """
    enc_ops, dec_ops = get_acescc_clf_ops(config)
    ap0_to_ap1 = enc_ops[0]
    ap1_to_ap0 = dec_ops[-1]

    if lin_max <= lin_min or lin_min <= 0:
        raise ValueError("extended-log requires 0 < lin_min < lin_max")
    L = np.log2(lin_max / lin_min)
    log_slope = 1.0 / L
    log_offset = -np.log2(lin_min) / L

    log_encode = ocio.LogAffineTransform(
        logSideSlope=[log_slope] * 3,
        logSideOffset=[log_offset] * 3,
        linSideSlope=[1.0] * 3,
        linSideOffset=[0.0] * 3,
    )
    log_encode.setBase(2.0)

    log_decode = ocio.LogAffineTransform(
        logSideSlope=[log_slope] * 3,
        logSideOffset=[log_offset] * 3,
        linSideSlope=[1.0] * 3,
        linSideOffset=[0.0] * 3,
    )
    log_decode.setBase(2.0)
    log_decode.setDirection(ocio.TRANSFORM_DIR_INVERSE)

    encode_ops = [ap0_to_ap1, log_encode]
    decode_ops = [log_decode, ap1_to_ap0]
    return encode_ops, decode_ops


def setup_extended_log_remap_cs(config, lin_min: float, lin_max: float):
    """
    Remap CS: [0,1] = normalized log of AP1 linear [lin_min, lin_max].
    to_reference: norm -> Log decode -> lin AP1 -> AP0
    from_reference: AP0 -> AP1 -> Log encode -> norm
    Uses same LogAffine as get_extended_log_clf_ops (native OCIO/CLF Log).
    """
    enc_ops, dec_ops = get_extended_log_clf_ops(config, lin_min, lin_max)
    ap0_to_ap1 = enc_ops[0]
    ap1_to_ap0 = dec_ops[-1]
    log_encode = enc_ops[1]
    log_decode = dec_ops[0]

    existing = config.getColorSpace(ACESCC_REMAP_CS)
    if existing:
        config.removeColorSpace(ACESCC_REMAP_CS)

    g_to = ocio.GroupTransform()
    g_to.appendTransform(log_decode)
    g_to.appendTransform(ap1_to_ap0)

    g_from = ocio.GroupTransform()
    g_from.appendTransform(ap0_to_ap1)
    g_from.appendTransform(log_encode)

    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_DISPLAY, ACESCC_REMAP_CS)
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)
    config.addColorSpace(cs)


def _eval_log_camera_at_linear(lin_val: float, lin_break: float, log_slope: float, log_offset: float) -> float:
    """Evaluate camera log (linear toe + log segment) at one linear value."""
    if lin_val <= lin_break:
        # linear segment: derivative at break = log_slope / (lin_break * ln(2))
        import math
        log_break = log_slope * math.log2(lin_break) + log_offset
        linear_slope = log_slope / (lin_break * math.log(2))
        linear_offset = log_break - linear_slope * lin_break
        return linear_slope * lin_val + linear_offset
    return log_slope * np.log2(lin_val) + log_offset


def get_camera_log_clf_ops(
    config,
    lin_min: float,
    lin_max: float,
    lin_break: float = 0.0078125,
    inv_remap_mode: str = "range",
):
    """
    Inverse CLF ops using OCIO LogCameraTransform (CLF cameraLinToLog/cameraLogToLin).
    Piecewise: linear toe below lin_break, then log segment mapping to [0,1] via Range.
    Same log segment as extended-log for highlight range; linear toe preserves shadow detail.
    """
    enc0, dec0 = get_acescc_clf_ops(config, "range")
    ap0_to_ap1 = enc0[0]
    ap1_to_ap0 = dec0[-1]

    if lin_max <= lin_min or lin_min <= 0 or lin_break <= 0 or lin_break >= lin_max:
        raise ValueError("camera-log requires 0 < lin_min < lin_break < lin_max")
    L = np.log2(lin_max / lin_min)
    log_slope = 1.0 / L
    log_offset = -np.log2(lin_min) / L

    log_encode = ocio.LogCameraTransform(
        [lin_break] * 3,
        base=2.0,
        logSideSlope=[log_slope] * 3,
        logSideOffset=[log_offset] * 3,
        linSideSlope=[1.0] * 3,
        linSideOffset=[0.0] * 3,
        linearSlope=[],
    )
    log_decode = ocio.LogCameraTransform(
        [lin_break] * 3,
        base=2.0,
        logSideSlope=[log_slope] * 3,
        logSideOffset=[log_offset] * 3,
        linSideSlope=[1.0] * 3,
        linSideOffset=[0.0] * 3,
        linearSlope=[],
        direction=ocio.TRANSFORM_DIR_INVERSE,
    )

    code_min = float(_eval_log_camera_at_linear(lin_min, lin_break, log_slope, log_offset))
    code_max = float(_eval_log_camera_at_linear(lin_max, lin_break, log_slope, log_offset))

    if inv_remap_mode == "none":
        encode_ops = [ap0_to_ap1, log_encode]
        decode_ops = [log_decode, ap1_to_ap0]
        return encode_ops, decode_ops
    to01, from01 = _make_remap_to01_from01(code_min, code_max)
    encode_ops = [ap0_to_ap1, log_encode, to01]
    decode_ops = [from01, log_decode, ap1_to_ap0]
    return encode_ops, decode_ops


def setup_camera_log_remap_cs(
    config,
    lin_min: float,
    lin_max: float,
    lin_break: float = 0.0078125,
    inv_remap_mode: str = "range",
):
    """Remap CS for camera-log: LUT domain <-> ACES2065-1 via LogCamera (+ remap)."""
    enc_ops, dec_ops = get_camera_log_clf_ops(
        config, lin_min, lin_max, lin_break, inv_remap_mode
    )
    ap0_to_ap1 = enc_ops[0]
    log_encode = enc_ops[1]

    existing = config.getColorSpace(ACESCC_REMAP_CS)
    if existing:
        config.removeColorSpace(ACESCC_REMAP_CS)

    g_to = ocio.GroupTransform()
    for op in dec_ops:
        g_to.appendTransform(op)

    g_from = ocio.GroupTransform()
    g_from.appendTransform(ap0_to_ap1)
    g_from.appendTransform(log_encode)
    if len(enc_ops) > 2:
        g_from.appendTransform(enc_ops[2])

    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_DISPLAY, ACESCC_REMAP_CS)
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)
    config.addColorSpace(cs)


def setup_acescc_remap_cs(config, inv_remap_mode: str = "range"):
    """AP0 <-> LUT domain via ACEScc LogCamera (+ Range/Matrix/none per inv_remap_mode)."""
    enc_ops, dec_ops = get_acescc_clf_ops(config, inv_remap_mode)
    ap0_to_ap1 = enc_ops[0]
    log_encode = enc_ops[1]

    existing = config.getColorSpace(ACESCC_REMAP_CS)
    if existing:
        config.removeColorSpace(ACESCC_REMAP_CS)

    g_to = ocio.GroupTransform()
    for op in dec_ops:
        g_to.appendTransform(op)

    g_from = ocio.GroupTransform()
    g_from.appendTransform(ap0_to_ap1)
    g_from.appendTransform(log_encode)
    if len(enc_ops) > 2:
        g_from.appendTransform(enc_ops[2])

    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_DISPLAY, ACESCC_REMAP_CS)
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)
    config.addColorSpace(cs)


def setup_pseudolog_remap_cs(
    config, params: PseudoLogParams, lin_min: float, lin_max: float
):
    """
    Remap color space: [0,1] pseudo-log (JPlog2-style norm) <-> ACES2065-1.

    to_reference: norm -> Lut1D decode -> linear AP1 -> AP0
    from_reference: AP0 -> AP1 -> Range(lin range) -> Lut1D encode -> norm
    """
    enc_ops, dec_ops = get_acescc_clf_ops(config)
    ap0_to_ap1 = enc_ops[0]
    ap1_to_ap0 = dec_ops[-1]

    lut_dec = build_decode_lut1d(PSEUDOLOG_1D_LENGTH, params)
    encode_lut, _, _ = build_encode_lut1d(
        PSEUDOLOG_1D_LENGTH, params, lin_min, lin_max
    )
    rng = make_range_lin_to_unit(lin_min, lin_max)

    existing = config.getColorSpace(ACESCC_REMAP_CS)
    if existing:
        config.removeColorSpace(ACESCC_REMAP_CS)

    g_to = ocio.GroupTransform()
    g_to.appendTransform(lut_dec)
    g_to.appendTransform(ap1_to_ap0)

    g_from = ocio.GroupTransform()
    g_from.appendTransform(ap0_to_ap1)
    g_from.appendTransform(rng)
    g_from.appendTransform(encode_lut)

    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_DISPLAY, ACESCC_REMAP_CS)
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)
    config.addColorSpace(cs)


def get_jplog_clf_ops(
    config, params: PseudoLogParams, lin_min: float, lin_max: float
):
    """Encode/decode ops for inverse CLF when using JPlog2-style pseudo-log."""
    enc_ops, dec_ops = get_acescc_clf_ops(config)
    ap0_to_ap1 = enc_ops[0]
    ap1_to_ap0 = dec_ops[-1]
    encode_lut, _, _ = build_encode_lut1d(
        PSEUDOLOG_1D_LENGTH, params, lin_min, lin_max
    )
    lut_dec = build_decode_lut1d(PSEUDOLOG_1D_LENGTH, params)
    rng = make_range_lin_to_unit(lin_min, lin_max)
    encode_ops = [ap0_to_ap1, rng, encode_lut]
    decode_ops = [lut_dec, ap1_to_ap0]
    return encode_ops, decode_ops


def get_untm_ops(config):
    """
    Extract the analytical operators from the Un-tone-mapped VT.

    Forward (AP0 -> XYZ-D65): typically a single MatrixTransform.
    Inverse (XYZ-D65 -> AP0): the reverse ops.

    Returns (forward_ops_list, inverse_ops_list).
    """
    untm = config.getViewTransform('Un-tone-mapped')
    untm_transform = untm.getTransform(ocio.VIEWTRANSFORM_DIR_FROM_REFERENCE)

    proc_fwd = config.getProcessor(untm_transform, ocio.TRANSFORM_DIR_FORWARD)
    gt_fwd = proc_fwd.createGroupTransform()
    fwd_ops = [gt_fwd[i] for i in range(len(gt_fwd))]

    proc_inv = config.getProcessor(untm_transform, ocio.TRANSFORM_DIR_INVERSE)
    gt_inv = proc_inv.createGroupTransform()
    inv_ops = [gt_inv[i] for i in range(len(gt_inv))]

    return fwd_ops, inv_ops


def setup_bake_display(config):
    """Add a passthrough display-referred CS, temp display, and Un-tone-mapped view."""
    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_DISPLAY, TEMP_PASSTHROUGH_CS)
    config.addColorSpace(cs)
    config.addDisplayView(
        display=TEMP_DISPLAY, view='Un-tone-mapped',
        viewTransform='Un-tone-mapped', displayColorSpaceName=TEMP_PASSTHROUGH_CS,
    )


def bake_forward_cube(config, vt_name, cube_path, lut_size):
    """Bake a forward .cube LUT: ACEScct -> CIE-XYZ-D65 (VT only)."""
    view_short = sanitize_lut_filename(vt_name)
    existing_views = list(config.getViews(TEMP_DISPLAY))
    if view_short not in existing_views:
        config.addDisplayView(
            display=TEMP_DISPLAY, view=view_short,
            viewTransform=vt_name, displayColorSpaceName=TEMP_PASSTHROUGH_CS,
        )

    baker = ocio.Baker()
    baker.setConfig(config)
    baker.setFormat('iridas_cube')
    baker.setCubeSize(lut_size)
    baker.setInputSpace('ACEScct')
    baker.setDisplayView(TEMP_DISPLAY, view_short)
    baker.bake(cube_path)


def _inv_shaper_encode(gamma=None):
    """Gamma encode: display-linear [0,1] -> perceptual [0,1] (x^(1/gamma)).

    Uses NEGATIVE_CLAMP so negatives are clamped to 0 (safe for CLF).
    Returns None if gamma <= 1.0 (no shaper needed).
    """
    g = gamma if gamma is not None else INV_SHAPER_GAMMA
    if g <= 1.0:
        return None
    return ocio.ExponentTransform(
        value=[1.0 / g] * 3 + [1.0],
        negativeStyle=ocio.NEGATIVE_CLAMP,
        direction=ocio.TRANSFORM_DIR_FORWARD,
    )


def _inv_shaper_decode(gamma=None):
    """Gamma decode: perceptual [0,1] -> display-linear [0,1] (x^gamma).

    Uses NEGATIVE_CLAMP so negatives are clamped to 0 (safe for CLF).
    Returns None if gamma <= 1.0 (no shaper needed).
    """
    g = gamma if gamma is not None else INV_SHAPER_GAMMA
    if g <= 1.0:
        return None
    return ocio.ExponentTransform(
        value=[g] * 3 + [1.0],
        negativeStyle=ocio.NEGATIVE_CLAMP,
        direction=ocio.TRANSFORM_DIR_FORWARD,
    )


def bake_inverse_cube(config, vt_name, cube_path, lut_size, inv_shaper_gamma=None):
    """
    Bake inverse .cube: **gamma-shaped AP0 display-linear** -> remapped log domain.

    The XYZ-D65 -> AP0 matrix is extracted from the LUT and applied analytically
    in the CLF, so the 3D LUT operates in AP0 display-linear space.  This
    reduces cross-channel interpolation error because the ACES 2.0 tone mapping
    happens in AP0 internally.

    When inv_shaper_gamma > 1, a power-curve shaper is applied to the AP0
    display-linear input before the baker samples it, giving the 3D LUT far
    better resolution in the shadows.

    Pipeline baked: gamma-shaped-AP0-display -> LUT3D -> remapped-log [0,1]^3.
    Full CLF:  XYZ -> AP0_matrix -> [gamma_encode] -> LUT3D -> decode -> AP0.
    """
    view_short = sanitize_lut_filename(vt_name)
    existing_views = list(config.getViews(TEMP_DISPLAY))
    if view_short not in existing_views:
        config.addDisplayView(
            display=TEMP_DISPLAY,
            view=view_short,
            viewTransform=vt_name,
            displayColorSpaceName=TEMP_PASSTHROUGH_CS,
        )

    untm_fwd_ops, untm_inv_ops = get_untm_ops(config)
    shaper_enc = _inv_shaper_encode(inv_shaper_gamma)
    shaper_dec = _inv_shaper_decode(inv_shaper_gamma)

    if config.getColorSpace(INVERSE_LUT_DISPLAY_SRC):
        config.removeColorSpace(INVERSE_LUT_DISPLAY_SRC)

    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_DISPLAY, INVERSE_LUT_DISPLAY_SRC)

    g_to = ocio.GroupTransform()
    if shaper_dec is not None:
        g_to.appendTransform(shaper_dec)
    for op in untm_fwd_ops:
        g_to.appendTransform(op)
    g_to.appendTransform(
        ocio.DisplayViewTransform(
            src='ACES2065-1',
            display=TEMP_DISPLAY,
            view=view_short,
            direction=ocio.TRANSFORM_DIR_INVERSE,
        )
    )
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)

    g_from = ocio.GroupTransform()
    g_from.appendTransform(
        ocio.DisplayViewTransform(
            src='ACES2065-1',
            display=TEMP_DISPLAY,
            view=view_short,
            direction=ocio.TRANSFORM_DIR_FORWARD,
        )
    )
    for op in untm_inv_ops:
        g_from.appendTransform(op)
    if shaper_enc is not None:
        g_from.appendTransform(shaper_enc)
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)

    config.addColorSpace(cs)

    baker = ocio.Baker()
    baker.setConfig(config)
    baker.setFormat('iridas_cube')
    baker.setCubeSize(lut_size)
    baker.setInputSpace(INVERSE_LUT_DISPLAY_SRC)
    baker.setTargetSpace(ACESCC_REMAP_CS)
    baker.bake(cube_path)

    config.removeColorSpace(INVERSE_LUT_DISPLAY_SRC)


def build_forward_clf(config, cube_path, clf_path, matrix_encode, log_encode):
    """
    Build a forward CLF: Matrix(AP0->AP1) + Log(ACEScct encode) + LUT3D.
    Input: ACES2065-1, Output: CIE-XYZ-D65.
    """
    ft = ocio.FileTransform(src=os.path.abspath(cube_path), interpolation=ocio.INTERP_BEST)
    proc_lut = config.getProcessor(ft)
    gt_lut = proc_lut.createGroupTransform()

    combined = ocio.GroupTransform()
    combined.appendTransform(matrix_encode)
    combined.appendTransform(log_encode)
    for i in range(len(gt_lut)):
        combined.appendTransform(gt_lut[i])

    combined.write(
        formatName='Academy/ASC Common LUT Format',
        config=config,
        fileName=clf_path,
    )
    return len(combined)


def build_inverse_clf(config, cube_path, clf_path, cc_decode_ops,
                      inv_shaper_gamma=None):
    """
    Build inverse CLF: XYZ -> AP0_matrix -> [gamma shaper] -> LUT3D -> decode -> AP0.

    The analytical XYZ-D65 -> AP0 matrix is applied first, so the 3D LUT
    operates in AP0 display-linear space (reducing cross-channel interpolation
    error).  When inv_shaper_gamma > 1, a gamma shaper encodes AP0 display-linear
    into a perceptual domain before the 3D LUT, matching how the LUT was baked.
    """
    _, untm_inv_ops = get_untm_ops(config)
    shaper_enc = _inv_shaper_encode(inv_shaper_gamma)

    ft = ocio.FileTransform(src=os.path.abspath(cube_path), interpolation=ocio.INTERP_BEST)
    proc_lut = config.getProcessor(ft)
    gt_lut = proc_lut.createGroupTransform()

    combined = ocio.GroupTransform()
    for op in untm_inv_ops:
        combined.appendTransform(op)
    if shaper_enc is not None:
        combined.appendTransform(shaper_enc)
    for i in range(len(gt_lut)):
        combined.appendTransform(gt_lut[i])
    for op in cc_decode_ops:
        combined.appendTransform(op)

    combined.write(
        formatName='Academy/ASC Common LUT Format',
        config=config,
        fileName=clf_path,
    )
    return len(combined)


# ---------------------------------------------------------------------------
# ACEScct-domain bake/build: symmetric ACEScct-in / ACEScct-out LUTs
# ---------------------------------------------------------------------------

def _get_vt_builtin_style(config, vt_name):
    """Return the BuiltinTransform style string for a named ViewTransform."""
    vt = config.getViewTransform(vt_name)
    t = vt.getTransform(ocio.VIEWTRANSFORM_DIR_FROM_REFERENCE)
    if isinstance(t, ocio.BuiltinTransform):
        return t.getStyle()
    raise ValueError(f"VT '{vt_name}' is not a BuiltinTransform")


def _remove_cs_if_exists(config, name):
    if config.getColorSpace(name):
        config.removeColorSpace(name)


def probe_acescct_display_range(config, vt_name, grid_res=65, margin=0.005):
    """
    Determine the actual ACEScct(display) range for a given View Transform.

    Sweeps a dense 3D grid of ACEScct(scene) values through the full bake
    chain (ACEScct decode → AP0 → VT fwd → XYZ→AP1 → ACEScct encode) and
    returns (domain_min, domain_max) with a small safety margin so the LUT
    fully covers the output range.

    Uses the same grid resolution as the LUT (default 65) to capture the
    exact range the Baker will produce.
    """
    builtin_style = _get_vt_builtin_style(config, vt_name)
    untm_fwd_ops, untm_inv_ops = get_untm_ops(config)
    log_dec, ap1_to_ap0 = get_acescct_decode_ops()
    _, log_enc = get_acescct_encode_ops()

    g = ocio.GroupTransform()
    g.appendTransform(log_dec)
    g.appendTransform(ap1_to_ap0)
    g.appendTransform(ocio.BuiltinTransform(style=builtin_style))
    for op in untm_inv_ops:
        g.appendTransform(op)
    g.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1))
    g.appendTransform(log_enc)

    cpu = config.getProcessor(g).getDefaultCPUProcessor()

    vals_1d = np.linspace(0.0, 1.0, grid_res, dtype=np.float32)
    grid = np.array(
        np.meshgrid(vals_1d, vals_1d, vals_1d), dtype=np.float32
    ).T.reshape(-1, 3).copy()

    cpu.apply(ocio.PackedImageDesc(grid.ravel(), len(grid), 1, 3))

    raw_min = float(grid.min())
    raw_max = float(grid.max())
    span = raw_max - raw_min
    domain_min = max(0.0, raw_min - span * margin)
    domain_max = min(1.0, raw_max + span * margin)
    return domain_min, domain_max


def _make_domain_normalize(domain_min, domain_max):
    """Affine MatrixTransform that maps [domain_min, domain_max] → [0, 1] (no clamp)."""
    scale = 1.0 / (domain_max - domain_min)
    offset = -domain_min * scale
    return ocio.MatrixTransform(
        matrix=[scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, 1],
        offset=[offset, offset, offset, 0],
    )


def _make_domain_denormalize(domain_min, domain_max):
    """Affine MatrixTransform that maps [0, 1] → [domain_min, domain_max] (no clamp)."""
    scale = domain_max - domain_min
    offset = domain_min
    return ocio.MatrixTransform(
        matrix=[scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, 1],
        offset=[offset, offset, offset, 0],
    )


def bake_forward_cube_acescct(config, vt_name, cube_path, lut_size,
                              domain_min=None, domain_max=None):
    """
    Bake forward .cube in ACEScct domain: ACEScct(scene) -> normalized ACEScct(display).

    When domain_min/domain_max are provided, a Range operator remaps the
    ACEScct(display) output from [domain_min, domain_max] to [0, 1] so the
    full LUT grid covers only the useful range.

    Creates a temp scene-referred CS whose from_reference is:
      VT(fwd, AP0->XYZ) + XYZ->AP1 + ACEScct encode [+ Range normalize]
    Baker: input=ACEScct, target=temp CS.
    """
    builtin_style = _get_vt_builtin_style(config, vt_name)
    untm_fwd_ops, untm_inv_ops = get_untm_ops(config)
    _, log_enc = get_acescct_encode_ops()

    _remove_cs_if_exists(config, TEMP_ACESCCT_FWD_CS)
    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_SCENE, TEMP_ACESCCT_FWD_CS)

    g_from = ocio.GroupTransform()
    g_from.appendTransform(ocio.BuiltinTransform(style=builtin_style))
    for op in untm_inv_ops:
        g_from.appendTransform(op)
    g_from.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1))
    g_from.appendTransform(log_enc)
    if domain_min is not None and domain_max is not None:
        g_from.appendTransform(_make_domain_normalize(domain_min, domain_max))
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)

    g_to = ocio.GroupTransform()
    if domain_min is not None and domain_max is not None:
        g_to.appendTransform(_make_domain_denormalize(domain_min, domain_max))
    log_dec, _ = get_acescct_decode_ops()
    g_to.appendTransform(log_dec)
    g_to.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0))
    for op in untm_fwd_ops:
        g_to.appendTransform(op)
    g_to.appendTransform(
        ocio.BuiltinTransform(style=builtin_style,
                              direction=ocio.TRANSFORM_DIR_INVERSE)
    )
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)

    config.addColorSpace(cs)

    baker = ocio.Baker()
    baker.setConfig(config)
    baker.setFormat('iridas_cube')
    baker.setCubeSize(lut_size)
    baker.setInputSpace('ACEScct')
    baker.setTargetSpace(TEMP_ACESCCT_FWD_CS)
    baker.bake(cube_path)

    config.removeColorSpace(TEMP_ACESCCT_FWD_CS)


def bake_inverse_cube_acescct(config, vt_name, cube_path, lut_size,
                              domain_min=None, domain_max=None):
    """
    Bake inverse .cube in ACEScct domain: normalized ACEScct(display) -> ACEScct(scene).

    When domain_min/domain_max are provided, the temp CS includes a Range
    that maps [0, 1] → [domain_min, domain_max] before the ACEScct decode,
    so the Baker feeds the LUT with [0, 1] input covering the useful range.

    Creates a temp scene-referred CS whose to_reference is:
      [Range denormalize +] ACEScct decode + AP1->AP0 + untm_fwd + VT(inv)
    Baker: input=temp CS, target=ACEScct.
    """
    builtin_style = _get_vt_builtin_style(config, vt_name)
    untm_fwd_ops, untm_inv_ops = get_untm_ops(config)
    _, log_enc = get_acescct_encode_ops()

    _remove_cs_if_exists(config, TEMP_ACESCCT_INV_CS)
    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_SCENE, TEMP_ACESCCT_INV_CS)

    g_to = ocio.GroupTransform()
    if domain_min is not None and domain_max is not None:
        g_to.appendTransform(_make_domain_denormalize(domain_min, domain_max))
    log_dec, _ = get_acescct_decode_ops()
    g_to.appendTransform(log_dec)
    g_to.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0))
    for op in untm_fwd_ops:
        g_to.appendTransform(op)
    g_to.appendTransform(
        ocio.BuiltinTransform(style=builtin_style,
                              direction=ocio.TRANSFORM_DIR_INVERSE)
    )
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)

    g_from = ocio.GroupTransform()
    g_from.appendTransform(
        ocio.BuiltinTransform(style=builtin_style,
                              direction=ocio.TRANSFORM_DIR_FORWARD)
    )
    for op in untm_inv_ops:
        g_from.appendTransform(op)
    g_from.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1))
    g_from.appendTransform(log_enc)
    if domain_min is not None and domain_max is not None:
        g_from.appendTransform(_make_domain_normalize(domain_min, domain_max))
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)

    config.addColorSpace(cs)

    baker = ocio.Baker()
    baker.setConfig(config)
    baker.setFormat('iridas_cube')
    baker.setCubeSize(lut_size)
    baker.setInputSpace(TEMP_ACESCCT_INV_CS)
    baker.setTargetSpace('ACEScct')
    baker.bake(cube_path)

    config.removeColorSpace(TEMP_ACESCCT_INV_CS)


def build_forward_clf_acescct(config, cube_path, clf_path,
                              domain_min=None, domain_max=None):
    """
    Build forward CLF (ACEScct-domain):
      AP0->AP1 + ACEScct encode [+ normalize] + LUT3D [+ denormalize] + ACEScct decode + AP1->XYZ-D65.
    Input: ACES2065-1.  Output: CIE-XYZ-D65.

    When domain_min/domain_max are provided, affine normalize/denormalize
    operators bracket the LUT3D so it operates over the full [0,1] grid.
    """
    untm_fwd_ops, _ = get_untm_ops(config)
    ap0_to_ap1, log_enc = get_acescct_encode_ops()
    log_dec, ap1_to_ap0 = get_acescct_decode_ops()

    ft = ocio.FileTransform(src=os.path.abspath(cube_path),
                            interpolation=ocio.INTERP_BEST)
    proc_lut = config.getProcessor(ft)
    gt_lut = proc_lut.createGroupTransform()

    combined = ocio.GroupTransform()
    combined.appendTransform(ap0_to_ap1)
    combined.appendTransform(log_enc)
    for i in range(len(gt_lut)):
        combined.appendTransform(gt_lut[i])
    if domain_min is not None and domain_max is not None:
        combined.appendTransform(_make_domain_denormalize(domain_min, domain_max))
    combined.appendTransform(log_dec)
    combined.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0))
    for op in untm_fwd_ops:
        combined.appendTransform(op)

    combined.write(
        formatName='Academy/ASC Common LUT Format',
        config=config,
        fileName=clf_path,
    )
    return len(combined)


def build_inverse_clf_acescct(config, cube_path, clf_path,
                              domain_min=None, domain_max=None):
    """
    Build inverse CLF (ACEScct-domain):
      XYZ-D65->AP1 + ACEScct encode [+ normalize] + LUT3D [+ denormalize] + ACEScct decode + AP1->AP0.
    Input: CIE-XYZ-D65.  Output: ACES2065-1.

    When domain_min/domain_max are provided, affine normalize/denormalize
    operators bracket the LUT3D so it operates over the full [0,1] grid.
    """
    _, untm_inv_ops = get_untm_ops(config)
    _, log_enc = get_acescct_encode_ops()
    log_dec, _ = get_acescct_decode_ops()

    ft = ocio.FileTransform(src=os.path.abspath(cube_path),
                            interpolation=ocio.INTERP_BEST)
    proc_lut = config.getProcessor(ft)
    gt_lut = proc_lut.createGroupTransform()

    combined = ocio.GroupTransform()
    for op in untm_inv_ops:
        combined.appendTransform(op)
    combined.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1))
    combined.appendTransform(log_enc)
    if domain_min is not None and domain_max is not None:
        combined.appendTransform(_make_domain_normalize(domain_min, domain_max))
    for i in range(len(gt_lut)):
        combined.appendTransform(gt_lut[i])
    combined.appendTransform(log_dec)
    combined.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0))

    combined.write(
        formatName='Academy/ASC Common LUT Format',
        config=config,
        fileName=clf_path,
    )
    return len(combined)


FWD_OP_DESCRIPTIONS_ACESCCT = [
    "ACES AP0 to AP1 matrix",
    "Linear to ACEScct log (encode for LUT input)",
    "3D LUT - ACEScct(scene) to normalized ACEScct(display)",
    "Denormalize [0,1] to ACEScct(display) domain",
    "ACEScct log to linear (decode LUT output)",
    "ACES AP1 to AP0 matrix",
    "AP0 to CIE-XYZ-D65 (Un-tone-mapped forward)",
]

INV_OP_DESCRIPTIONS_ACESCCT = [
    "CIE-XYZ-D65 to AP0 (Un-tone-mapped inverse)",
    "ACES AP0 to AP1 matrix",
    "Linear to ACEScct log (encode for LUT input)",
    "Normalize ACEScct(display) domain to [0,1]",
    "3D LUT - normalized ACEScct(display) to ACEScct(scene)",
    "ACEScct log to linear (decode LUT output)",
    "ACES AP1 to AP0 matrix",
]


def generate_clf_files_acescct(
    config,
    vt_list,
    lut_dir,
    lut_size_fwd,
    lut_size_inv,
):
    """
    Symmetric ACEScct-domain CLF generation with per-VT domain normalization.

    Both forward and inverse 3D LUTs operate in normalized ACEScct space.
    A probe determines the actual ACEScct(display) range for each VT, and
    affine normalize/denormalize operators bracket the LUT3D so the full
    [0,1] grid covers only the useful range.

    Returns a dict mapping BuiltIn style -> {"forward": filename, "inverse": filename}.
    """
    os.makedirs(lut_dir, exist_ok=True)

    vt_to_clf = {}

    for vt_name, builtin_style in vt_list:
        base = sanitize_lut_filename(vt_name)
        fwd_clf = f"{base}.clf"
        inv_clf = f"{base}_inv.clf"
        fwd_path = os.path.join(lut_dir, fwd_clf)
        inv_path = os.path.join(lut_dir, inv_clf)

        fwd_cube = os.path.join(lut_dir, f"_tmp_{base}_fwd.cube")
        inv_cube = os.path.join(lut_dir, f"_tmp_{base}_inv.cube")

        domain_min, domain_max = probe_acescct_display_range(
            config, vt_name, grid_res=max(lut_size_fwd, lut_size_inv),
        )

        bake_forward_cube_acescct(
            config, vt_name, fwd_cube, lut_size_fwd,
            domain_min=domain_min, domain_max=domain_max,
        )
        bake_inverse_cube_acescct(
            config, vt_name, inv_cube, lut_size_inv,
            domain_min=domain_min, domain_max=domain_max,
        )

        n_fwd = build_forward_clf_acescct(
            config, fwd_cube, fwd_path,
            domain_min=domain_min, domain_max=domain_max,
        )
        n_inv = build_inverse_clf_acescct(
            config, inv_cube, inv_path,
            domain_min=domain_min, domain_max=domain_max,
        )

        os.remove(fwd_cube)
        os.remove(inv_cube)

        postprocess_clf(
            fwd_path,
            name=f"{vt_name} - Forward",
            clf_id=f"urn:aswf:ocio:transformId:{base}:fwd",
            input_desc='ACES2065-1',
            output_desc='CIE-XYZ-D65',
            op_descriptions=FWD_OP_DESCRIPTIONS_ACESCCT,
        )
        postprocess_clf(
            inv_path,
            name=f"{vt_name} - Inverse",
            clf_id=f"urn:aswf:ocio:transformId:{base}:inv",
            input_desc='CIE-XYZ-D65',
            output_desc='ACES2065-1',
            op_descriptions=INV_OP_DESCRIPTIONS_ACESCCT,
        )

        fwd_size = os.path.getsize(fwd_path)
        inv_size = os.path.getsize(inv_path)
        print(f"    {vt_name}  [domain: {domain_min:.4f} .. {domain_max:.4f}]")
        print(f"      Forward: {fwd_clf} ({fwd_size / 1024:.0f} KB, {n_fwd} ops)")
        print(f"      Inverse: {inv_clf} ({inv_size / 1024:.0f} KB, {n_inv} ops)")

        vt_to_clf[builtin_style] = {
            "forward": fwd_clf,
            "inverse": inv_clf,
        }

    return vt_to_clf


# ---------------------------------------------------------------------------
# Display-shaper CLF pipeline
#
# Uses the display's native encoding as the LUT domain shaper:
#   SDR views  -> gamma 2.2 at AP1 primaries
#   HDR views  -> PQ (ST 2084) at AP1 primaries
#
# The 3D LUT maps display-encoded AP1 <-> ACEScct, so the [0,1] LUT domain
# naturally covers the full displayable range without range normalization.
# ---------------------------------------------------------------------------

GAMMA22_EXPONENT = 2.2


def _is_hdr_view(vt_name):
    """Classify a VT as HDR (True) or SDR (False) based on its name."""
    if 'SDR' in vt_name:
        return False
    if 'HDR' in vt_name:
        nits = 0
        import re as _re
        m = _re.search(r'(\d+)\s*nits', vt_name)
        if m:
            nits = int(m.group(1))
        return nits > 108
    return False


def _get_display_shaper_label(vt_name):
    """Return a human-readable label for the shaper used by this VT."""
    return "PQ (ST 2084)" if _is_hdr_view(vt_name) else "Gamma 2.2"


def get_gamma22_encode_op():
    """Linear AP1 -> Gamma 2.2 encoded AP1: x^(1/2.2), negatives clamped to 0."""
    return ocio.ExponentTransform(
        value=[GAMMA22_EXPONENT, GAMMA22_EXPONENT, GAMMA22_EXPONENT, 1.0],
        negativeStyle=ocio.NEGATIVE_CLAMP,
        direction=ocio.TRANSFORM_DIR_INVERSE,
    )


def get_gamma22_decode_op():
    """Gamma 2.2 encoded AP1 -> Linear AP1: x^2.2, negatives clamped to 0."""
    return ocio.ExponentTransform(
        value=[GAMMA22_EXPONENT, GAMMA22_EXPONENT, GAMMA22_EXPONENT, 1.0],
        negativeStyle=ocio.NEGATIVE_CLAMP,
        direction=ocio.TRANSFORM_DIR_FORWARD,
    )


def get_pq_encode_op():
    """Linear AP1 (normalised to 10000 nits) -> PQ [0,1].

    Uses the OCIO BuiltinTransform which resolves to a half-domain LUT1D.
    """
    return ocio.BuiltinTransform(
        style="CURVE - LINEAR_to_ST-2084",
        direction=ocio.TRANSFORM_DIR_FORWARD,
    )


def _resolve_pq_decode_for_clf():
    """PQ [0,1] -> Linear: resolved forward LUT1D (CLF-writable).

    The BuiltinTransform inverse is an InverseLUT1D which CLF cannot represent.
    We resolve it through OPTIMIZATION_DEFAULT to get a forward LUT1D.
    """
    bake_cfg = ocio.Config.CreateFromBuiltinConfig(BUILTIN_BAKE_CONFIG)
    pq_enc = ocio.BuiltinTransform(style="CURVE - LINEAR_to_ST-2084")
    proc = bake_cfg.getProcessor(pq_enc, ocio.TRANSFORM_DIR_INVERSE)
    proc_opt = proc.getOptimizedProcessor(ocio.OPTIMIZATION_DEFAULT)
    gt = proc_opt.createGroupTransform()
    return [gt[i] for i in range(len(gt))]


def get_pq_decode_op():
    """PQ [0,1] -> Linear AP1 (normalised to 10000 nits).

    For baking (processed by OCIO runtime), uses the BuiltinTransform inverse.
    """
    return ocio.BuiltinTransform(
        style="CURVE - LINEAR_to_ST-2084",
        direction=ocio.TRANSFORM_DIR_INVERSE,
    )


def _get_shaper_encode_decode(vt_name):
    """Return (encode_op, decode_op) for the appropriate display shaper."""
    if _is_hdr_view(vt_name):
        return get_pq_encode_op(), get_pq_decode_op()
    return get_gamma22_encode_op(), get_gamma22_decode_op()


def probe_display_shaper_range(config, vt_name, grid_res=65, margin=0.005):
    """
    Determine the display-shaper output range for a given View Transform.

    Sweeps a dense 3D grid of ACEScct(scene) values through:
      ACEScct decode → AP0 → VT fwd → XYZ→AP1 → display encode (gamma/PQ)
    and returns (domain_min, domain_max) with a small safety margin.
    """
    builtin_style = _get_vt_builtin_style(config, vt_name)
    _, untm_inv_ops = get_untm_ops(config)
    log_dec, ap1_to_ap0 = get_acescct_decode_ops()
    shaper_enc, _ = _get_shaper_encode_decode(vt_name)

    g = ocio.GroupTransform()
    g.appendTransform(log_dec)
    g.appendTransform(ap1_to_ap0)
    g.appendTransform(ocio.BuiltinTransform(style=builtin_style))
    for op in untm_inv_ops:
        g.appendTransform(op)
    g.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1))
    g.appendTransform(shaper_enc)

    cpu = config.getProcessor(g).getDefaultCPUProcessor()

    vals_1d = np.linspace(0.0, 1.0, grid_res, dtype=np.float32)
    grid = np.array(
        np.meshgrid(vals_1d, vals_1d, vals_1d), dtype=np.float32
    ).T.reshape(-1, 3).copy()

    cpu.apply(ocio.PackedImageDesc(grid.ravel(), len(grid), 1, 3))

    raw_min = float(grid.min())
    raw_max = float(grid.max())
    span = raw_max - raw_min
    domain_min = max(0.0, raw_min - span * margin)
    domain_max = min(1.0, raw_max + span * margin)
    return domain_min, domain_max


def bake_forward_cube_display_shaper(config, vt_name, cube_path, lut_size,
                                     domain_min=None, domain_max=None):
    """
    Bake forward .cube: ACEScct(scene) -> normalized display-encoded AP1.

    When domain_min/domain_max are provided, a normalize operator remaps the
    display-shaper output from [domain_min, domain_max] to [0, 1].

    Baker: input=ACEScct, target=temp CS.
    """
    builtin_style = _get_vt_builtin_style(config, vt_name)
    untm_fwd_ops, untm_inv_ops = get_untm_ops(config)
    shaper_enc, _ = _get_shaper_encode_decode(vt_name)

    _remove_cs_if_exists(config, TEMP_DISPSHAPER_FWD_CS)
    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_SCENE, TEMP_DISPSHAPER_FWD_CS)

    g_from = ocio.GroupTransform()
    g_from.appendTransform(ocio.BuiltinTransform(style=builtin_style))
    for op in untm_inv_ops:
        g_from.appendTransform(op)
    g_from.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1))
    g_from.appendTransform(shaper_enc)
    if domain_min is not None and domain_max is not None:
        g_from.appendTransform(_make_domain_normalize(domain_min, domain_max))
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)

    _, shaper_dec = _get_shaper_encode_decode(vt_name)
    g_to = ocio.GroupTransform()
    if domain_min is not None and domain_max is not None:
        g_to.appendTransform(_make_domain_denormalize(domain_min, domain_max))
    g_to.appendTransform(shaper_dec)
    g_to.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0))
    for op in untm_fwd_ops:
        g_to.appendTransform(op)
    g_to.appendTransform(
        ocio.BuiltinTransform(style=builtin_style,
                              direction=ocio.TRANSFORM_DIR_INVERSE)
    )
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)

    config.addColorSpace(cs)

    baker = ocio.Baker()
    baker.setConfig(config)
    baker.setFormat('iridas_cube')
    baker.setCubeSize(lut_size)
    baker.setInputSpace('ACEScct')
    baker.setTargetSpace(TEMP_DISPSHAPER_FWD_CS)
    baker.bake(cube_path)

    config.removeColorSpace(TEMP_DISPSHAPER_FWD_CS)


def bake_inverse_cube_display_shaper(config, vt_name, cube_path, lut_size,
                                     domain_min=None, domain_max=None):
    """
    Bake inverse .cube: normalized display-encoded AP1 -> ACEScct(scene).

    When domain_min/domain_max are provided, a denormalize operator remaps
    [0, 1] → [domain_min, domain_max] before the display decode.

    Baker: input=temp CS, target=ACEScct.
    """
    builtin_style = _get_vt_builtin_style(config, vt_name)
    untm_fwd_ops, untm_inv_ops = get_untm_ops(config)
    _, shaper_dec = _get_shaper_encode_decode(vt_name)

    _remove_cs_if_exists(config, TEMP_DISPSHAPER_INV_CS)
    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_SCENE, TEMP_DISPSHAPER_INV_CS)

    g_to = ocio.GroupTransform()
    if domain_min is not None and domain_max is not None:
        g_to.appendTransform(_make_domain_denormalize(domain_min, domain_max))
    g_to.appendTransform(shaper_dec)
    g_to.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0))
    for op in untm_fwd_ops:
        g_to.appendTransform(op)
    g_to.appendTransform(
        ocio.BuiltinTransform(style=builtin_style,
                              direction=ocio.TRANSFORM_DIR_INVERSE)
    )
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)

    shaper_enc, _ = _get_shaper_encode_decode(vt_name)
    g_from = ocio.GroupTransform()
    g_from.appendTransform(
        ocio.BuiltinTransform(style=builtin_style,
                              direction=ocio.TRANSFORM_DIR_FORWARD)
    )
    for op in untm_inv_ops:
        g_from.appendTransform(op)
    g_from.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1))
    g_from.appendTransform(shaper_enc)
    if domain_min is not None and domain_max is not None:
        g_from.appendTransform(_make_domain_normalize(domain_min, domain_max))
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)

    config.addColorSpace(cs)

    baker = ocio.Baker()
    baker.setConfig(config)
    baker.setFormat('iridas_cube')
    baker.setCubeSize(lut_size)
    baker.setInputSpace(TEMP_DISPSHAPER_INV_CS)
    baker.setTargetSpace('ACEScct')
    baker.bake(cube_path)

    config.removeColorSpace(TEMP_DISPSHAPER_INV_CS)


def _get_shaper_clf_ops(vt_name):
    """Return (encode_ops, decode_ops) suitable for CLF writing.

    For gamma 2.2: single ExponentTransform in each direction.
    For PQ: encode is the BuiltinTransform (forward LUT1D), decode is resolved
    via _resolve_pq_decode_for_clf() to avoid InverseLUT1D.
    """
    if _is_hdr_view(vt_name):
        enc_ops = [get_pq_encode_op()]
        dec_ops = _resolve_pq_decode_for_clf()
        return enc_ops, dec_ops
    return [get_gamma22_encode_op()], [get_gamma22_decode_op()]


def build_forward_clf_display_shaper(config, cube_path, clf_path, vt_name,
                                     domain_min=None, domain_max=None):
    """
    Build forward CLF (display-shaper domain):
      AP0->AP1 + ACEScct encode + LUT3D (ACEScct -> norm display AP1)
      [+ denormalize] + display decode (gamma/PQ) + AP1->XYZ-D65.
    Input: ACES2065-1.  Output: CIE-XYZ-D65.
    """
    untm_fwd_ops, _ = get_untm_ops(config)
    ap0_to_ap1, log_enc = get_acescct_encode_ops()
    _, shaper_dec_ops = _get_shaper_clf_ops(vt_name)

    ft = ocio.FileTransform(src=os.path.abspath(cube_path),
                            interpolation=ocio.INTERP_BEST)
    proc_lut = config.getProcessor(ft)
    gt_lut = proc_lut.createGroupTransform()

    combined = ocio.GroupTransform()
    combined.appendTransform(ap0_to_ap1)
    combined.appendTransform(log_enc)
    for i in range(len(gt_lut)):
        combined.appendTransform(gt_lut[i])
    if domain_min is not None and domain_max is not None:
        combined.appendTransform(_make_domain_denormalize(domain_min, domain_max))
    for op in shaper_dec_ops:
        combined.appendTransform(op)
    combined.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0))
    for op in untm_fwd_ops:
        combined.appendTransform(op)

    combined.write(
        formatName='Academy/ASC Common LUT Format',
        config=config,
        fileName=clf_path,
    )
    return len(combined)


def build_inverse_clf_display_shaper(config, cube_path, clf_path, vt_name,
                                     domain_min=None, domain_max=None):
    """
    Build inverse CLF (display-shaper domain):
      XYZ-D65->AP1 + display encode (gamma/PQ) [+ normalize]
      + LUT3D (norm display AP1 -> ACEScct) + ACEScct decode + AP1->AP0.
    Input: CIE-XYZ-D65.  Output: ACES2065-1.
    """
    _, untm_inv_ops = get_untm_ops(config)
    log_dec, _ = get_acescct_decode_ops()
    shaper_enc_ops, _ = _get_shaper_clf_ops(vt_name)

    ft = ocio.FileTransform(src=os.path.abspath(cube_path),
                            interpolation=ocio.INTERP_BEST)
    proc_lut = config.getProcessor(ft)
    gt_lut = proc_lut.createGroupTransform()

    combined = ocio.GroupTransform()
    for op in untm_inv_ops:
        combined.appendTransform(op)
    combined.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1))
    for op in shaper_enc_ops:
        combined.appendTransform(op)
    if domain_min is not None and domain_max is not None:
        combined.appendTransform(_make_domain_normalize(domain_min, domain_max))
    for i in range(len(gt_lut)):
        combined.appendTransform(gt_lut[i])
    combined.appendTransform(log_dec)
    combined.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0))

    combined.write(
        formatName='Academy/ASC Common LUT Format',
        config=config,
        fileName=clf_path,
    )
    return len(combined)


FWD_OP_DESCRIPTIONS_DISPSHAPER = [
    "ACES AP0 to AP1 matrix",
    "Linear to ACEScct log (encode for LUT input)",
    "3D LUT - ACEScct(scene) to normalized display-encoded AP1",
    "Denormalize [0,1] to display-shaper domain",
    "Display decode (gamma 2.2 or PQ) to linear AP1",
    "ACES AP1 to AP0 matrix",
    "AP0 to CIE-XYZ-D65 (Un-tone-mapped forward)",
]

INV_OP_DESCRIPTIONS_DISPSHAPER = [
    "CIE-XYZ-D65 to AP0 (Un-tone-mapped inverse)",
    "ACES AP0 to AP1 matrix",
    "Display encode (gamma 2.2 or PQ) from linear AP1",
    "Normalize display-shaper domain to [0,1]",
    "3D LUT - normalized display-encoded AP1 to ACEScct(scene)",
    "ACEScct log to linear (decode LUT output)",
    "ACES AP1 to AP0 matrix",
]


def generate_clf_files_display_shaper(
    config,
    vt_list,
    lut_dir,
    lut_size_fwd,
    lut_size_inv,
):
    """
    Display-shaper CLF generation with per-VT domain normalization.

    Uses gamma 2.2 (SDR) or PQ (HDR) at AP1 primaries as the LUT domain
    shaper, then normalizes the effective range to [0,1] so the full LUT
    grid covers only the useful range.

    Returns a dict mapping BuiltIn style -> {"forward": filename, "inverse": filename}.
    """
    os.makedirs(lut_dir, exist_ok=True)

    vt_to_clf = {}

    for vt_name, builtin_style in vt_list:
        base = sanitize_lut_filename(vt_name)
        fwd_clf = f"{base}.clf"
        inv_clf = f"{base}_inv.clf"
        fwd_path = os.path.join(lut_dir, fwd_clf)
        inv_path = os.path.join(lut_dir, inv_clf)

        fwd_cube = os.path.join(lut_dir, f"_tmp_{base}_dshaper_fwd.cube")
        inv_cube = os.path.join(lut_dir, f"_tmp_{base}_dshaper_inv.cube")

        shaper_label = _get_display_shaper_label(vt_name)

        domain_min, domain_max = probe_display_shaper_range(
            config, vt_name, grid_res=max(lut_size_fwd, lut_size_inv),
        )

        bake_forward_cube_display_shaper(
            config, vt_name, fwd_cube, lut_size_fwd,
            domain_min=domain_min, domain_max=domain_max,
        )
        bake_inverse_cube_display_shaper(
            config, vt_name, inv_cube, lut_size_inv,
            domain_min=domain_min, domain_max=domain_max,
        )

        n_fwd = build_forward_clf_display_shaper(
            config, fwd_cube, fwd_path, vt_name,
            domain_min=domain_min, domain_max=domain_max,
        )
        n_inv = build_inverse_clf_display_shaper(
            config, inv_cube, inv_path, vt_name,
            domain_min=domain_min, domain_max=domain_max,
        )

        os.remove(fwd_cube)
        os.remove(inv_cube)

        postprocess_clf(
            fwd_path,
            name=f"{vt_name} - Forward",
            clf_id=f"urn:aswf:ocio:transformId:{base}:fwd",
            input_desc='ACES2065-1',
            output_desc='CIE-XYZ-D65',
            op_descriptions=FWD_OP_DESCRIPTIONS_DISPSHAPER,
        )
        postprocess_clf(
            inv_path,
            name=f"{vt_name} - Inverse",
            clf_id=f"urn:aswf:ocio:transformId:{base}:inv",
            input_desc='CIE-XYZ-D65',
            output_desc='ACES2065-1',
            op_descriptions=INV_OP_DESCRIPTIONS_DISPSHAPER,
        )

        fwd_size = os.path.getsize(fwd_path)
        inv_size = os.path.getsize(inv_path)
        print(f"    {vt_name}  [shaper: {shaper_label}, domain: {domain_min:.4f} .. {domain_max:.4f}]")
        print(f"      Forward: {fwd_clf} ({fwd_size / 1024:.0f} KB, {n_fwd} ops)")
        print(f"      Inverse: {inv_clf} ({inv_size / 1024:.0f} KB, {n_inv} ops)")

        vt_to_clf[builtin_style] = {
            "forward": fwd_clf,
            "inverse": inv_clf,
        }

    return vt_to_clf


def generate_clf_files(
    config,
    vt_list,
    lut_dir,
    lut_size_fwd,
    lut_size_inv,
    *,
    inv_encoding="acescc",
    pseudolog_params=None,
    pseudolog_lin_min=-0.02,
    pseudolog_lin_max=65504.0,
    inv_log_lin_min=2.0 ** -12,
    inv_log_lin_max=65504.0,
    inv_camera_log_lin_break=0.015625,
    inv_acescct_gray_min=1e-8,
    inv_acescct_gray_max=65504.0,
    inv_remap_mode="range",
    inv_shaper_gamma=None,
):
    """
    For each ACES 2.0 view transform, bake .cube LUTs then wrap with
    analytical operators to produce self-contained CLF files.

    inv_encoding: acescc | acescct | extended-log | camera-log | jplog2.

    Returns a dict mapping BuiltIn style -> {"forward": filename, "inverse": filename}.
    """
    os.makedirs(lut_dir, exist_ok=True)

    # Forward uses ACEScct (good precision, no linear toe issue for forward)
    cct_matrix_encode, cct_log_encode = get_acescct_encode_ops(config)

    setup_bake_display(config)
    if inv_encoding == "jplog2":
        params = pseudolog_params or PseudoLogParams()
        setup_pseudolog_remap_cs(
            config, params, pseudolog_lin_min, pseudolog_lin_max
        )
        cc_encode_ops, cc_decode_ops = get_jplog_clf_ops(
            config, params, pseudolog_lin_min, pseudolog_lin_max
        )
        inv_op_descriptions = INV_OP_DESCRIPTIONS_JPLOG
    elif inv_encoding == "extended-log":
        setup_extended_log_remap_cs(config, inv_log_lin_min, inv_log_lin_max)
        cc_encode_ops, cc_decode_ops = get_extended_log_clf_ops(
            config, inv_log_lin_min, inv_log_lin_max
        )
        inv_op_descriptions = INV_OP_DESCRIPTIONS_EXTENDED_LOG
    elif inv_encoding == "camera-log":
        setup_camera_log_remap_cs(
            config,
            inv_log_lin_min,
            inv_log_lin_max,
            inv_camera_log_lin_break,
            inv_remap_mode,
        )
        cc_encode_ops, cc_decode_ops = get_camera_log_clf_ops(
            config,
            inv_log_lin_min,
            inv_log_lin_max,
            inv_camera_log_lin_break,
            inv_remap_mode,
        )
        inv_op_descriptions = INV_OP_DESCRIPTIONS_CAMERA_LOG
    elif inv_encoding == "acescct":
        setup_acescct_remap_cs(
            config,
            inv_acescct_gray_min,
            inv_acescct_gray_max,
            inv_remap_mode,
        )
        _, cc_decode_ops = get_acescct_remap_clf_ops(
            config,
            inv_acescct_gray_min,
            inv_acescct_gray_max,
            inv_remap_mode,
        )
        inv_op_descriptions = INV_OP_DESCRIPTIONS_ACESCT
    else:
        setup_acescc_remap_cs(config, inv_remap_mode)
        cc_encode_ops, cc_decode_ops = get_acescc_clf_ops(config, inv_remap_mode)
        inv_op_descriptions = INV_OP_DESCRIPTIONS

    effective_gamma = inv_shaper_gamma if inv_shaper_gamma is not None else INV_SHAPER_GAMMA
    if effective_gamma <= 1.0:
        inv_op_descriptions = [d for d in inv_op_descriptions if "shaper" not in d.lower()]

    vt_to_clf = {}

    for vt_name, builtin_style in vt_list:
        base = sanitize_lut_filename(vt_name)
        fwd_clf = f"{base}.clf"
        inv_clf = f"{base}_inv.clf"
        fwd_path = os.path.join(lut_dir, fwd_clf)
        inv_path = os.path.join(lut_dir, inv_clf)

        fwd_cube = os.path.join(lut_dir, f"_tmp_{base}_fwd.cube")
        inv_cube = os.path.join(lut_dir, f"_tmp_{base}_inv.cube")

        bake_forward_cube(config, vt_name, fwd_cube, lut_size_fwd)
        bake_inverse_cube(config, vt_name, inv_cube, lut_size_inv,
                          inv_shaper_gamma=inv_shaper_gamma)

        n_fwd = build_forward_clf(config, fwd_cube, fwd_path,
                                  cct_matrix_encode, cct_log_encode)
        n_inv = build_inverse_clf(config, inv_cube, inv_path, cc_decode_ops,
                                  inv_shaper_gamma=inv_shaper_gamma)

        os.remove(fwd_cube)
        os.remove(inv_cube)

        postprocess_clf(
            fwd_path,
            name=f"{vt_name} - Forward",
            clf_id=f"urn:aswf:ocio:transformId:{base}:fwd",
            input_desc='ACES2065-1',
            output_desc='CIE-XYZ-D65',
            op_descriptions=FWD_OP_DESCRIPTIONS,
        )
        postprocess_clf(
            inv_path,
            name=f"{vt_name} - Inverse",
            clf_id=f"urn:aswf:ocio:transformId:{base}:inv",
            input_desc='CIE-XYZ-D65 (display-linear)',
            output_desc='ACES2065-1',
            op_descriptions=inv_op_descriptions,
        )

        fwd_size = os.path.getsize(fwd_path)
        inv_size = os.path.getsize(inv_path)
        print(f"    {vt_name}")
        print(f"      Forward: {fwd_clf} ({fwd_size / 1024:.0f} KB, {n_fwd} ops)")
        print(f"      Inverse: {inv_clf} ({inv_size / 1024:.0f} KB, {n_inv} ops)")

        vt_to_clf[builtin_style] = {
            "forward": fwd_clf,
            "inverse": inv_clf,
        }

    # Clean up temp display/CS
    for cs_name in (TEMP_PASSTHROUGH_CS, ACESCC_REMAP_CS):
        try:
            config.removeColorSpace(cs_name)
        except Exception:
            pass

    return vt_to_clf


def bake_1d_luts(config, lut_dir, target_version="2.3"):
    """Bake incompatible curve and CSC BuiltIns into 1D LUTs."""
    curve_lut_files = {}
    if CURVE_BUILTINS_TO_BAKE:
        print(f"  [1D LUTs] {len(CURVE_BUILTINS_TO_BAKE)} curve BuiltIns...")
        for builtin_style, lut_name in CURVE_BUILTINS_TO_BAKE.items():
            lut_path = os.path.join(lut_dir, f"{lut_name}.spi1d")
            print(f"    {lut_name}")
            input_values = np.linspace(0.0, 1.0, 4096, dtype=np.float32)
            pixels = np.column_stack([input_values, input_values, input_values])
            bt = ocio.BuiltinTransform(style=builtin_style)
            proc = config.getProcessor(bt, ocio.TRANSFORM_DIR_FORWARD)
            result = apply_processor_to_pixels(proc, pixels)
            write_spi1d_lut(lut_path, input_values, result[:, 0])
            curve_lut_files[builtin_style] = f"{lut_name}.spi1d"

    csc_lut_files = {}
    if CSC_BUILTINS_TO_BAKE:
        print(f"  [1D LUTs + Matrix] {len(CSC_BUILTINS_TO_BAKE)} CSC BuiltIns...")
        for builtin_style, lut_name in CSC_BUILTINS_TO_BAKE.items():
            lut_path = os.path.join(lut_dir, f"{lut_name}.spi1d")
            print(f"    {lut_name}")

            bt = ocio.BuiltinTransform(style=builtin_style)
            proc = config.getProcessor(bt)
            gt = proc.createGroupTransform()
            matrix_values = None
            for i in range(len(gt)):
                t = gt[i]
                if isinstance(t, ocio.MatrixTransform):
                    matrix_values = list(t.getMatrix())

            input_values = np.linspace(0.0, 1.0, 4096, dtype=np.float32)
            pixels = np.column_stack([input_values, input_values, input_values])
            group = ocio.GroupTransform()
            group.appendTransform(ocio.BuiltinTransform(style=builtin_style))
            if matrix_values:
                inv_matrix = ocio.MatrixTransform(matrix=matrix_values)
                inv_matrix.setDirection(ocio.TRANSFORM_DIR_INVERSE)
                group.appendTransform(inv_matrix)
            proc_curve = config.getProcessor(group, ocio.TRANSFORM_DIR_FORWARD)
            result = apply_processor_to_pixels(proc_curve, pixels)
            write_spi1d_lut(lut_path, input_values, result[:, 0])

            csc_lut_files[builtin_style] = {
                "lut_path": f"{lut_name}.spi1d",
                "matrix": matrix_values,
            }

    # Bake PQ/HLG EOTFs for DISPLAY builtins that need 1D LUTs.
    # DISPLAY_BUILTINS_NEEDING_1D_LUT: v2.4+ builtins, always replaced.
    # DISPLAY_BUILTINS_NEEDING_1D_LUT_V21: v2.3+ builtins, only for v2.1 target.
    display_eotf_lut_files = {}
    all_display_lut_builtins = dict(DISPLAY_BUILTINS_NEEDING_1D_LUT)
    if target_version == "2.1":
        all_display_lut_builtins.update(DISPLAY_BUILTINS_NEEDING_1D_LUT_V21)

    if all_display_lut_builtins:
        already_baked = set()
        for builtin_style, info in all_display_lut_builtins.items():
            lut_name = info["lut_name"]
            if lut_name in already_baked:
                display_eotf_lut_files[builtin_style] = info
                continue
            lut_path = os.path.join(lut_dir, f"{lut_name}.spi1d")
            print(f"    {lut_name} (EOTF for {builtin_style})")
            # Use a builtin that has the same EOTF to extract the curve.
            # For styles with no matrix (e.g. DCDM), use a related PQ builtin.
            bake_style = builtin_style
            if info.get("matrix") is None:
                for s, i in DISPLAY_BUILTINS_NEEDING_1D_LUT_V21.items():
                    if i["lut_name"] == lut_name:
                        bake_style = s
                        break
            bt = ocio.BuiltinTransform(style=bake_style)
            proc = config.getProcessor(bt)
            gt = proc.createGroupTransform()
            eotf_group = ocio.GroupTransform()
            for i in range(len(gt)):
                t = gt[i]
                if not isinstance(t, ocio.MatrixTransform):
                    eotf_group.appendTransform(t)
            proc_eotf = config.getProcessor(eotf_group, ocio.TRANSFORM_DIR_FORWARD)
            input_values = np.linspace(0.0, 1.0, 4096, dtype=np.float32)
            pixels = np.column_stack([input_values, input_values, input_values])
            result = apply_processor_to_pixels(proc_eotf, pixels)
            write_spi1d_lut(lut_path, input_values, result[:, 0])
            already_baked.add(lut_name)
            display_eotf_lut_files[builtin_style] = info

    return curve_lut_files, csc_lut_files, display_eotf_lut_files


def migrate_interchange_to_description(text):
    """Migrate v2.5 interchange.amf_transform_ids URNs into description fields.

    For each ``interchange: / amf_transform_ids: |`` block found in *text*,
    the URNs are appended to the nearest preceding ``description:`` field as
    ``ACEStransformID:`` lines.  The original ``interchange`` block is removed.

    Used when downgrading OCIO v2.5 configs to v2.4 or v2.3, where ACES
    transform IDs live in the description attribute rather than interchange.
    """
    interchange_pat = re.compile(
        r'^(?P<indent>[ \t]*)interchange:\s*\n'
        r'[ \t]+amf_transform_ids:\s*\|\s*\n'
        r'(?P<urns>(?:[ \t]+urn:[^\n]*\n)+)',
        re.MULTILINE,
    )
    for m in reversed(list(interchange_pat.finditer(text))):
        urns = [u.strip() for u in m.group('urns').strip().splitlines() if u.strip()]
        if not urns:
            continue
        aces_block = '\n'.join(f'      ACEStransformID: {u}' for u in urns)

        block_start = m.start()
        preceding = text[:block_start]

        desc_pat = re.compile(
            r'^(?P<full>'
            r'(?P<indent>[ \t]*)description:[ \t]*'
            r'(?P<val>[^\n]*)\n'
            r'(?P<body>(?:[ \t]+[^\n]+\n)*)'
            r')',
            re.MULTILINE,
        )
        desc_match = None
        for dm in desc_pat.finditer(preceding):
            desc_match = dm

        if desc_match:
            val = desc_match.group('val').strip()
            body = desc_match.group('body').rstrip('\n')
            if val.startswith('|'):
                if body:
                    new_desc = (
                        f'    description: |\n'
                        f'{body}\n\n'
                        f'{aces_block}\n'
                    )
                else:
                    new_desc = (
                        f'    description: |\n'
                        f'{aces_block}\n'
                    )
            elif val:
                new_desc = (
                    f'    description: |\n'
                    f'      {val}\n\n'
                    f'{aces_block}\n'
                )
            else:
                new_desc = (
                    f'    description: |\n'
                    f'{aces_block}\n'
                )
            text = (
                text[:desc_match.start()]
                + new_desc
                + text[desc_match.end():m.start()]
                + text[m.end():]
            )
        else:
            replacement = (
                f'{m.group("indent")}description: |\n'
                f'{aces_block}\n'
            )
            text = text[:m.start()] + replacement + text[m.end():]

    return text


def generate_v23_config(ref_config_path, vt_to_clf, curve_lut_files, csc_lut_files,
                        output_config_path, display_eotf_lut_files=None):
    """
    Generate an OCIO 2.3 config by text-replacing BuiltinTransform references
    in the v2.4/v2.5 YAML with FileTransform CLF references.
    """
    with open(ref_config_path, 'r') as f:
        config_text = f.read()

    config_text = re.sub(
        r'^(ocio_profile_version:\s*)2\.[45]',
        r'\g<1>2.3',
        config_text,
        count=1,
        flags=re.MULTILINE,
    )

    if re.search(r'^search_path:\s*""', config_text, re.MULTILINE):
        config_text = re.sub(
            r'^(search_path:\s*)""',
            r'\1luts',
            config_text,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        config_text = re.sub(
            r'^(search_path:\s*)(.+)$',
            lambda m: f'{m.group(1)}{m.group(2).strip()}:luts',
            config_text,
            count=1,
            flags=re.MULTILINE,
        )

    old_name_match = re.search(r'^name:\s*(.+)$', config_text, re.MULTILINE)
    if old_name_match:
        old_name = old_name_match.group(1).strip()
        new_name = re.sub(r'ocio-v2\.[45]', 'ocio-v2.3-clf', old_name)
        if new_name == old_name:
            new_name = old_name + "-clf-based"
        config_text = config_text.replace(f"name: {old_name}", f"name: {new_name}", 1)

    config_text = migrate_interchange_to_description(config_text)

    # Strip remaining v2.5 interchange attributes (not valid in v2.3)
    config_text = re.sub(
        r'^\s*aces_interchange:.*\n', '', config_text, flags=re.MULTILINE
    )
    config_text = re.sub(
        r'^\s*cie_xyz_d65_interchange:.*\n', '', config_text, flags=re.MULTILINE
    )
    # Any remaining interchange blocks (single-line form, no URNs, etc.)
    config_text = re.sub(
        r'^\s*interchange:\s*\n\s+amf_transform_ids:\s*\S.*\n',
        '',
        config_text,
        flags=re.MULTILINE,
    )
    # Strip interop_id (v2.5 attribute, not valid in v2.3)
    config_text = re.sub(
        r'^\s*interop_id:.*\n', '', config_text, flags=re.MULTILINE
    )

    # Replace ColorSpaceTransform references to "Linear Rec.2020" with an
    # inline BT.2020->AP0 MatrixTransform.  The reference config uses this CS
    # in Canon CLog2/CLog3 BT2020 color spaces, but "Linear Rec.2020" only
    # exists in studio configs — not in reference configs.
    config_text = re.sub(
        r'- !<ColorSpaceTransform>\s*\{src:\s*Linear Rec\.2020,\s*dst:\s*ACES2065-1\}',
        f'- !<MatrixTransform> {{matrix: [{BT2020_TO_AP0_MATRIX_YAML}]}}',
        config_text,
    )

    # Replace ACES 2.0 VT BuiltIns with CLF FileTransforms (forward + inverse)
    for builtin_style, clf_info in vt_to_clf.items():
        fwd_clf = clf_info["forward"]
        inv_clf = clf_info["inverse"]
        escaped_style = re.escape(builtin_style)
        pattern = (
            r'(from_scene_reference:\s*)!<BuiltinTransform>\s*\{style:\s*'
            + escaped_style
            + r'\}'
        )
        replacement = (
            r'\g<1>!<FileTransform> {src: '
            + fwd_clf
            + ', interpolation: best}\n'
            + '    to_scene_reference: !<FileTransform> {src: '
            + inv_clf
            + ', interpolation: best}'
        )
        config_text = re.sub(pattern, replacement, config_text)

    # Replace display BuiltIns that are incompatible with OCIO 2.3
    for builtin_style, replacement_yaml in DISPLAY_BUILTIN_REPLACEMENTS.items():
        escaped_style = re.escape(builtin_style)
        pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
        config_text = re.sub(pattern, replacement_yaml, config_text)

    # Replace v2.4+ DISPLAY builtins needing 1D LUTs (always applied)
    if display_eotf_lut_files is not None:
        for builtin_style, info in display_eotf_lut_files.items():
            if builtin_style not in DISPLAY_BUILTINS_NEEDING_1D_LUT:
                continue
            escaped_style = re.escape(builtin_style)
            pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
            lut_rel = f"{info['lut_name']}.spi1d"
            mat = info.get("matrix")
            if mat:
                replacement = (
                    f'!<GroupTransform>\n'
                    f'      name: {info["name"]}\n'
                    f'      children:\n'
                    f'        - !<MatrixTransform> {{matrix: [{mat}]}}\n'
                    f'        - !<FileTransform> {{src: {lut_rel}, interpolation: linear}}'
                )
            else:
                replacement = (
                    f'!<FileTransform> {{src: {lut_rel}, interpolation: linear}}'
                )
            config_text = re.sub(pattern, replacement, config_text)

        # v2.1 only: replace v2.3+ DISPLAY builtins with analytical Matrix + EOTF
        v21_styles = {s for s in display_eotf_lut_files if s in DISPLAY_BUILTINS_NEEDING_1D_LUT_V21}
        if v21_styles:
            for builtin_style, replacement_yaml in DISPLAY_BUILTIN_REPLACEMENTS_V21.items():
                escaped_style = re.escape(builtin_style)
                pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
                config_text = re.sub(pattern, replacement_yaml, config_text)

            for builtin_style, info in display_eotf_lut_files.items():
                if builtin_style not in DISPLAY_BUILTINS_NEEDING_1D_LUT_V21:
                    continue
                escaped_style = re.escape(builtin_style)
                pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
                lut_rel = f"{info['lut_name']}.spi1d"
                mat = info["matrix"]
                replacement = (
                    f'!<GroupTransform>\n'
                    f'      name: {info["name"]}\n'
                    f'      children:\n'
                    f'        - !<MatrixTransform> {{matrix: [{mat}]}}\n'
                    f'        - !<FileTransform> {{src: {lut_rel}, interpolation: linear}}'
                )
                config_text = re.sub(pattern, replacement, config_text)

    # Replace curve BuiltIns with 1D LUT references
    for builtin_style, lut_rel_path in curve_lut_files.items():
        escaped_style = re.escape(builtin_style)
        pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
        replacement = f'!<FileTransform> {{src: {lut_rel_path}, interpolation: linear}}'
        config_text = re.sub(pattern, replacement, config_text)

    # Replace CSC BuiltIns with 1D LUT + matrix
    for builtin_style, csc_info in csc_lut_files.items():
        escaped_style = re.escape(builtin_style)
        lut_rel = csc_info["lut_path"]
        mat = csc_info["matrix"]
        mat_str = ", ".join(f"{v}" for v in mat)
        pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
        replacement = (
            f'!<GroupTransform>\n'
            f'      children:\n'
            f'        - !<FileTransform> {{src: {lut_rel}, interpolation: linear}}\n'
            f'        - !<MatrixTransform> {{matrix: [{mat_str}]}}'
        )
        config_text = re.sub(pattern, replacement, config_text)

    with open(output_config_path, 'w') as f:
        f.write(config_text)

    return output_config_path


def downgrade_v25_to_v24(config_path, output_path=None):
    """Downgrade an OCIO v2.5 config to v2.4.

    OCIO v2.4 has most of the same BuiltinTransforms as v2.5 (including
    ACES 2.0 output transforms), but uses description-based
    ``ACEStransformID:`` lines instead of the structured
    ``interchange.amf_transform_ids`` attribute.

    The only builtins missing from OCIO 2.4 are the ``MIRROR NEGS`` display
    variants introduced in v2.5; these are replaced with analytical
    Matrix + EOTF equivalents.

    This function:
    - Sets ``ocio_profile_version`` to 2.4
    - Migrates ``interchange.amf_transform_ids`` URNs into ``description``
    - Strips per-item ``interchange:`` blocks and ``interop_id:`` lines
    - Preserves ``aces_interchange`` / ``cie_xyz_d65_interchange`` role names
    - Replaces v2.5-only MIRROR NEGS builtins with analytical equivalents
    - Updates the config ``name:`` field
    """
    with open(config_path, 'r') as f:
        text = f.read()

    # Version
    text = re.sub(
        r'^(ocio_profile_version:\s*)2\.5',
        r'\g<1>2.4',
        text,
        count=1,
        flags=re.MULTILINE,
    )

    # Config name
    old_name_match = re.search(r'^name:\s*(.+)$', text, re.MULTILINE)
    if old_name_match:
        old_name = old_name_match.group(1).strip()
        new_name = old_name.replace('ocio-v2.5', 'ocio-v2.4')
        if new_name != old_name:
            text = text.replace(f"name: {old_name}", f"name: {new_name}", 1)

    # Migrate interchange.amf_transform_ids URNs into description fields.
    text = migrate_interchange_to_description(text)

    # Strip remaining per-item interchange blocks (single-line form, etc.).
    # These sit inside colorspaces/looks/view_transforms, indented with spaces.
    text = re.sub(
        r'^\s*interchange:\s*\n\s+amf_transform_ids:\s*\S.*\n',
        '',
        text,
        flags=re.MULTILINE,
    )

    # Strip interop_id (v2.5-only attribute on color spaces).
    text = re.sub(
        r'^\s*interop_id:.*\n', '', text, flags=re.MULTILINE
    )

    # Replace v2.5-only MIRROR NEGS builtins with analytical equivalents.
    for builtin_style, replacement_yaml in DISPLAY_BUILTIN_REPLACEMENTS_V25.items():
        escaped_style = re.escape(builtin_style)
        pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
        text = re.sub(pattern, replacement_yaml, text)

    if output_path is None:
        output_path = config_path
    with open(output_path, 'w') as f:
        f.write(text)

    return output_path


def downgrade_v23_to_v21(config_path, output_path=None):
    """
    Downgrade an OCIO 2.3 config to 2.1 by stripping v2.2+ features
    and replacing v2.3+ BuiltinTransforms with analytical equivalents.

    Removes: named_transforms section, aliases, encoding attributes,
    and interchange roles.  Replaces DISPLAY builtins that require v2.3+
    with Matrix + EOTF transforms (baking PQ/HLG 1D LUTs as needed).
    """
    with open(config_path, 'r') as f:
        text = f.read()

    text = re.sub(
        r'^(ocio_profile_version:\s*)2\.3',
        r'\g<1>2.1',
        text,
        count=1,
        flags=re.MULTILINE,
    )

    text = re.sub(r'^\s*aliases:\s*\[.*\]\s*\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*encoding:\s*\S+.*\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*interop_id:\s*\S+.*\n', '', text, flags=re.MULTILINE)

    text = re.sub(
        r'^named_transforms:\s*\n(?:(?:  .*\n|\n)*)',
        '',
        text,
        flags=re.MULTILINE,
    )

    name_match = re.search(r'^name:\s*(.+)$', text, re.MULTILINE)
    if name_match:
        old = name_match.group(1).strip()
        new = old.replace('v2.3-clf', 'v2.1-clf')
        if new != old:
            text = text.replace(f'name: {old}', f'name: {new}', 1)

    # Replace v2.3+ DISPLAY builtins with analytical Matrix + EOTF
    for builtin_style, replacement_yaml in DISPLAY_BUILTIN_REPLACEMENTS_V21.items():
        escaped_style = re.escape(builtin_style)
        pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
        text = re.sub(pattern, replacement_yaml, text)

    # Replace v2.3+ PQ/HLG DISPLAY builtins with Matrix + 1D LUT
    config_dir = os.path.dirname(output_path or config_path)
    lut_dir = os.path.join(config_dir, "luts")
    needs_luts = False
    all_v21_lut_builtins = dict(DISPLAY_BUILTINS_NEEDING_1D_LUT)
    all_v21_lut_builtins.update(DISPLAY_BUILTINS_NEEDING_1D_LUT_V21)
    for builtin_style, info in all_v21_lut_builtins.items():
        escaped_style = re.escape(builtin_style)
        pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
        if not re.search(pattern, text):
            continue
        needs_luts = True
        lut_name = info["lut_name"]
        lut_rel = f"{lut_name}.spi1d"
        lut_path = os.path.join(lut_dir, lut_rel)
        if not os.path.isfile(lut_path):
            os.makedirs(lut_dir, exist_ok=True)
            bake_style = builtin_style
            if info.get("matrix") is None:
                for s, i in DISPLAY_BUILTINS_NEEDING_1D_LUT_V21.items():
                    if i["lut_name"] == lut_name:
                        bake_style = s
                        break
            config_obj = ocio.Config.CreateFromBuiltinConfig("studio-config-v2.1.0_aces-v1.3_ocio-v2.3")
            bt = ocio.BuiltinTransform(style=bake_style)
            proc = config_obj.getProcessor(bt)
            gt = proc.createGroupTransform()
            eotf_group = ocio.GroupTransform()
            for idx in range(len(gt)):
                t = gt[idx]
                if not isinstance(t, ocio.MatrixTransform):
                    eotf_group.appendTransform(t)
            proc_eotf = config_obj.getProcessor(eotf_group, ocio.TRANSFORM_DIR_FORWARD)
            input_values = np.linspace(0.0, 1.0, 4096, dtype=np.float32)
            pixels = np.column_stack([input_values, input_values, input_values])
            result = apply_processor_to_pixels(proc_eotf, pixels)
            write_spi1d_lut(lut_path, input_values, result[:, 0])

        mat = info.get("matrix")
        if mat:
            replacement = (
                f'!<GroupTransform>\n'
                f'      name: {info["name"]}\n'
                f'      children:\n'
                f'        - !<MatrixTransform> {{matrix: [{mat}]}}\n'
                f'        - !<FileTransform> {{src: {lut_rel}, interpolation: linear}}'
            )
        else:
            replacement = (
                f'!<FileTransform> {{src: {lut_rel}, interpolation: linear}}'
            )
        text = re.sub(pattern, replacement, text)

    # Replace v2.2+ CURVE builtins (Canon CLog2/3, etc.) with baked 1D LUTs
    for builtin_style, lut_name in CURVE_BUILTINS_V22.items():
        escaped_style = re.escape(builtin_style)
        pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
        if not re.search(pattern, text):
            continue
        needs_luts = True
        lut_rel = f"{lut_name}.spi1d"
        lut_path = os.path.join(lut_dir, lut_rel)
        if not os.path.isfile(lut_path):
            os.makedirs(lut_dir, exist_ok=True)
            config_obj = ocio.Config.CreateFromBuiltinConfig(
                "studio-config-v2.1.0_aces-v1.3_ocio-v2.3")
            bt = ocio.BuiltinTransform(style=builtin_style)
            proc = config_obj.getProcessor(bt, ocio.TRANSFORM_DIR_FORWARD)
            input_values = np.linspace(0.0, 1.0, 4096, dtype=np.float32)
            pixels = np.column_stack([input_values, input_values, input_values])
            result = apply_processor_to_pixels(proc, pixels)
            write_spi1d_lut(lut_path, input_values, result[:, 0])
        replacement = f'!<FileTransform> {{src: {lut_rel}, interpolation: linear}}'
        text = re.sub(pattern, replacement, text)

    # Replace v2.2+ CSC builtins (Canon CLog2/3 CGamut, etc.) with 1D LUT + Matrix
    for builtin_style, lut_name in CSC_BUILTINS_V22.items():
        escaped_style = re.escape(builtin_style)
        pattern = r'!<BuiltinTransform>\s*\{style:\s*' + escaped_style + r'\}'
        if not re.search(pattern, text):
            continue
        needs_luts = True
        lut_rel = f"{lut_name}.spi1d"
        lut_path = os.path.join(lut_dir, lut_rel)
        if not os.path.isfile(lut_path):
            os.makedirs(lut_dir, exist_ok=True)
            config_obj = ocio.Config.CreateFromBuiltinConfig(
                "studio-config-v2.1.0_aces-v1.3_ocio-v2.3")
            bt = ocio.BuiltinTransform(style=builtin_style)
            proc = config_obj.getProcessor(bt)
            gt = proc.createGroupTransform()
            matrix_values = None
            for idx in range(len(gt)):
                t = gt[idx]
                if isinstance(t, ocio.MatrixTransform):
                    matrix_values = list(t.getMatrix())
            group = ocio.GroupTransform()
            group.appendTransform(ocio.BuiltinTransform(style=builtin_style))
            if matrix_values:
                inv_mat = ocio.MatrixTransform(matrix=matrix_values)
                inv_mat.setDirection(ocio.TRANSFORM_DIR_INVERSE)
                group.appendTransform(inv_mat)
            proc_curve = config_obj.getProcessor(group, ocio.TRANSFORM_DIR_FORWARD)
            input_values = np.linspace(0.0, 1.0, 4096, dtype=np.float32)
            pixels = np.column_stack([input_values, input_values, input_values])
            result = apply_processor_to_pixels(proc_curve, pixels)
            write_spi1d_lut(lut_path, input_values, result[:, 0])
        config_obj = ocio.Config.CreateFromBuiltinConfig(
            "studio-config-v2.1.0_aces-v1.3_ocio-v2.3")
        bt = ocio.BuiltinTransform(style=builtin_style)
        proc = config_obj.getProcessor(bt)
        gt = proc.createGroupTransform()
        matrix_values = None
        for idx in range(len(gt)):
            t = gt[idx]
            if isinstance(t, ocio.MatrixTransform):
                matrix_values = list(t.getMatrix())
        if matrix_values:
            mat_str = ", ".join(f"{v}" for v in matrix_values)
            replacement = (
                f'!<GroupTransform>\n'
                f'      children:\n'
                f'        - !<FileTransform> {{src: {lut_rel}, interpolation: linear}}\n'
                f'        - !<MatrixTransform> {{matrix: [{mat_str}]}}'
            )
        else:
            replacement = f'!<FileTransform> {{src: {lut_rel}, interpolation: linear}}'
        text = re.sub(pattern, replacement, text)

    if needs_luts:
        if re.search(r'^search_path:\s*""', text, re.MULTILINE):
            text = re.sub(
                r'^search_path:\s*""',
                'search_path: luts',
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif 'search_path:' not in text:
            text = re.sub(
                r'^(roles:)',
                r'search_path: luts\n\n\1',
                text,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r'^search_path:\s*\S', text, re.MULTILINE):
            sp_match = re.search(r'^search_path:\s*(.+)$', text, re.MULTILINE)
            if sp_match and 'luts' not in sp_match.group(1):
                text = re.sub(
                    r'^(search_path:\s*)(.+)$',
                    r'\1\2:luts',
                    text,
                    count=1,
                    flags=re.MULTILINE,
                )

    out = output_path or config_path
    with open(out, 'w') as f:
        f.write(text)
    return out


VALIDATION_VENVS = {
    "2.1": os.path.join(os.path.dirname(__file__), ".venv_ocio22", "bin", "python"),
    "2.3": os.path.join(os.path.dirname(__file__), ".venv_ocio23", "bin", "python"),
}

_VALIDATE_SCRIPT = textwrap.dedent("""\
    import os, sys
    os.chdir(os.path.dirname(os.path.abspath(sys.argv[1])))
    import PyOpenColorIO as ocio
    c = ocio.Config.CreateFromFile(os.path.basename(sys.argv[1]))
    c.validate()
    print(f"  OCIO runtime: {ocio.__version__}")
    print(f"  Config version: {c.getMajorVersion()}.{c.getMinorVersion()}")
    print(f"  View transforms: {len(c.getViewTransforms())}")
    print(f"  Color spaces: {len(c.getColorSpaces())}")
    nt = len(c.getNamedTransforms()) if hasattr(c, 'getNamedTransforms') else 0
    print(f"  Named transforms: {nt}")
    print("  Validation: PASSED")
""")


def validate_config(config_path, target_version=None):
    """Load and validate the generated config.

    When *target_version* is given and a matching validation venv exists,
    validation is run in a subprocess with the correct OCIO runtime so that
    version-specific constraints are actually enforced.
    """
    print(f"\nValidating: {config_path}")
    venv_python = VALIDATION_VENVS.get(target_version) if target_version else None
    if venv_python and os.path.isfile(venv_python):
        import subprocess
        abs_config = os.path.abspath(config_path)
        result = subprocess.run(
            [venv_python, "-c", _VALIDATE_SCRIPT, abs_config],
            capture_output=True, text=True,
        )
        for line in (result.stdout + result.stderr).splitlines():
            if line.strip():
                print(line)
        if result.returncode != 0:
            print("  Validation FAILED (subprocess)")
            return False
        return True

    try:
        config = ocio.Config.CreateFromFile(config_path)
        config.validate()
        print(f"  OCIO runtime: {ocio.__version__}")
        print(f"  Config version: {config.getMajorVersion()}.{config.getMinorVersion()}")
        print(f"  View transforms: {len(config.getViewTransforms())}")
        print(f"  Color spaces: {len(config.getColorSpaces())}")
        print(f"  Named transforms: {len(config.getNamedTransforms())}")
        print("  Validation: PASSED")
        return True
    except Exception as e:
        print(f"  Validation FAILED: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Generate a CLF-based OCIO 2.3 config from an ACES 2.0 OCIO v2.4 or v2.5 config"
    )
    parser.add_argument("reference_config",
                        help="Path to the reference OCIO v2.4 or v2.5 config "
                             "(used as template for the output config structure)")
    parser.add_argument(
        "--bake-config",
        default=None,
        help="Config used for CLF/LUT baking (default: OCIO built-in "
             f"'{BUILTIN_BAKE_CONFIG}'). Can be a file path or a built-in "
             "config name.",
    )
    parser.add_argument("-o", "--output-dir", default="OUTPUT/clf_based_config",
                        help="Output directory (default: OUTPUT/clf_based_config)")
    parser.add_argument(
        "--target-ocio-version",
        choices=("2.3", "2.1"),
        default="2.3",
        help="Target OCIO profile version (default: 2.3). "
        "2.1 strips named_transforms, aliases, and encoding attributes.",
    )
    parser.add_argument("-s", "--lut-size", type=int, default=65,
                        help="3D LUT cube size for forward CLFs (default: 65)")
    parser.add_argument("--inv-lut-size", type=int, default=97,
                        help="3D LUT cube size for inverse CLFs (default: 97)")
    parser.add_argument(
        "--inv-encoding",
        choices=("display-shaper", "acescct-domain", "acescc", "acescct", "extended-log", "camera-log", "jplog2"),
        default="display-shaper",
        help="Inverse encoding: display-shaper (default, gamma 2.2 for SDR / PQ for HDR "
        "at AP1 primaries — best perceptual distribution), "
        "acescct-domain (symmetric ACEScct-in/ACEScct-out LUT with per-VT range normalization), "
        "acescct (ACEScct LogCamera shaper), "
        "acescc (pure log shaper), extended-log, camera-log, jplog2",
    )
    parser.add_argument(
        "--inv-log-lin-min",
        type=float,
        default=2.0 ** -12,
        help="AP1 linear min for extended-log (norm 0); default 2^-12",
    )
    parser.add_argument(
        "--inv-log-lin-max",
        type=float,
        default=65504.0,
        help="AP1 linear max for extended-log/camera-log (norm 1); default 65504",
    )
    parser.add_argument(
        "--inv-camera-log-lin-break",
        type=float,
        default=0.015625,
        help="Camera-log linear toe break (camera-log only); 0.015625 ~best SDR shadow inversion per optimize_inverse_log_encoding.py; try 0.0078125 for ACEScct-like toe",
    )
    parser.add_argument(
        "--inv-acescct-gray-min",
        type=float,
        default=1e-8,
        help="ACEScct inverse: min neutral AP0 gray for LUT code range (acescct only)",
    )
    parser.add_argument(
        "--inv-acescct-gray-max",
        type=float,
        default=65504.0,
        help="ACEScct inverse: max neutral AP0 gray for LUT code range (acescct only)",
    )
    parser.add_argument(
        "--inv-remap",
        choices=("range", "none"),
        default="range",
        help="range (default): RangeTransform maps code endpoints to [0,1] for the 3D LUT. "
        "none: skip Range; LUT stores raw log/camera codes then analytical decode (acescc/"
        "acescct/camera-log only). Compare metrics to see remap effect.",
    )
    parser.add_argument(
        "--inv-shaper-gamma",
        type=float,
        default=INV_SHAPER_GAMMA,
        help=f"Inverse LUT input shaper gamma (default: {INV_SHAPER_GAMMA}). "
        "Set to 1.0 to disable the shaper (classic mode). "
        "Higher values spread more shadow resolution at the cost of highlights.",
    )
    parser.add_argument(
        "--pseudolog-lin-min",
        type=float,
        default=-0.02,
        help="AP1 linear min for Range before pseudo-log encode (jplog2 only)",
    )
    parser.add_argument(
        "--pseudolog-lin-max",
        type=float,
        default=65504.0,
        help="AP1 linear max for Range before pseudo-log encode (jplog2 only)",
    )
    parser.add_argument(
        "--pseudolog-lin-break",
        type=float,
        default=None,
        help="Override JPlog2 lin/log breakpoint (jplog2 only)",
    )
    parser.add_argument(
        "--pseudolog-log-divisor",
        type=float,
        default=None,
        help="Override (log2(lin)+offset)/divisor divisor, default 20.46 (jplog2 only)",
    )
    parser.add_argument(
        "--pseudolog-log-offset",
        type=float,
        default=None,
        help="Override log2 offset in log segment, default 10.5 (jplog2 only)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.reference_config):
        print(f"Error: Reference config not found: {args.reference_config}")
        sys.exit(1)
    if args.inv_remap == "none" and args.inv_encoding not in (
        "acescc",
        "acescct",
        "camera-log",
    ):
        print(
            "Error: --inv-remap none only applies to acescc, acescct, or camera-log",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.inv_encoding == "acescct-domain" and args.inv_shaper_gamma != INV_SHAPER_GAMMA:
        print(
            "Note: --inv-shaper-gamma is ignored for acescct-domain mode (no shaper needed)",
            file=sys.stderr,
        )

    print(f"Reference config: {args.reference_config}")
    print(f"Output directory: {args.output_dir}")
    print(f"Forward LUT size: {args.lut_size}^3")
    print(f"Inverse LUT size: {args.inv_lut_size}^3")
    print(f"Inverse encoding: {args.inv_encoding}")
    if args.inv_encoding == "acescct-domain":
        print("  Symmetric ACEScct-in/ACEScct-out with per-VT range normalization")
    elif args.inv_encoding == "display-shaper":
        print("  Display-shaper: gamma 2.2 (SDR) / PQ (HDR) at AP1 primaries")
    elif args.inv_encoding == "extended-log":
        print(
            f"  Extended-log AP1 linear range: [{args.inv_log_lin_min}, {args.inv_log_lin_max}]"
        )
    elif args.inv_encoding == "camera-log":
        print(
            f"  Camera-log AP1 range: [{args.inv_log_lin_min}, {args.inv_log_lin_max}], lin break: {args.inv_camera_log_lin_break}"
        )
    elif args.inv_encoding == "acescct":
        print(
            f"  ACEScct shaper AP0 gray range: [{args.inv_acescct_gray_min}, {args.inv_acescct_gray_max}]"
        )
    elif args.inv_encoding == "jplog2":
        print(
            f"  Pseudo-log AP1 linear range: [{args.pseudolog_lin_min}, {args.pseudolog_lin_max}]"
        )
    if args.inv_encoding not in ("acescct-domain", "display-shaper"):
        if args.inv_remap != "range":
            print(f"  Inverse remap mode: {args.inv_remap}")
        if args.inv_shaper_gamma != INV_SHAPER_GAMMA:
            print(f"  Inverse shaper gamma: {args.inv_shaper_gamma}")
        elif args.inv_shaper_gamma <= 1.0:
            print("  Inverse shaper: DISABLED (classic mode)")
    print()

    print("Loading template config (for VT discovery + output structure)...")
    template_cfg = ocio.Config.CreateFromFile(args.reference_config)
    print(f"  Version: {template_cfg.getMajorVersion()}.{template_cfg.getMinorVersion()}")

    if args.bake_config:
        if os.path.exists(args.bake_config):
            print(f"Loading bake config from file: {args.bake_config}")
            bake_cfg = ocio.Config.CreateFromFile(args.bake_config)
        else:
            print(f"Loading bake config from built-in: {args.bake_config}")
            bake_cfg = ocio.Config.CreateFromBuiltinConfig(args.bake_config)
    else:
        print(f"Loading bake config from built-in: {BUILTIN_BAKE_CONFIG}")
        bake_cfg = ocio.Config.CreateFromBuiltinConfig(BUILTIN_BAKE_CONFIG)
    _sync_view_transforms(bake_cfg, template_cfg)
    print()

    vt_list = get_aces2_view_transforms(template_cfg)
    print(f"Found {len(vt_list)} ACES 2.0 view transforms")
    print()

    lut_dir = os.path.join(args.output_dir, "luts")
    os.makedirs(lut_dir, exist_ok=True)

    inv_labels = {
        "acescct-domain": "ACEScct symmetric (ACEScct-in/ACEScct-out, ranged)",
        "display-shaper": "display-shaper (gamma 2.2 SDR / PQ HDR)",
        "acescc": "ACEScc",
        "acescct": "ACEScct (LogCamera shaper)",
        "extended-log": "extended log (native Log)",
        "camera-log": "camera log (native LogCamera)",
        "jplog2": "JPlog2 pseudo-log",
    }
    inv_label = inv_labels.get(args.inv_encoding, args.inv_encoding)
    print(f"Generating CLF files (fwd: ACEScct, inv: {inv_label})...")

    if args.inv_encoding == "acescct-domain":
        vt_to_clf = generate_clf_files_acescct(
            bake_cfg,
            vt_list,
            lut_dir,
            args.lut_size,
            args.inv_lut_size,
        )
    elif args.inv_encoding == "display-shaper":
        vt_to_clf = generate_clf_files_display_shaper(
            bake_cfg,
            vt_list,
            lut_dir,
            args.lut_size,
            args.inv_lut_size,
        )
    else:
        pl_params = None
        if args.inv_encoding == "jplog2":
            pl_params = PseudoLogParams()
            if args.pseudolog_lin_break is not None:
                pl_params = replace(pl_params, lin_break=args.pseudolog_lin_break)
            if args.pseudolog_log_divisor is not None:
                pl_params = replace(pl_params, log_divisor=args.pseudolog_log_divisor)
            if args.pseudolog_log_offset is not None:
                pl_params = replace(pl_params, log_offset=args.pseudolog_log_offset)
        vt_to_clf = generate_clf_files(
            bake_cfg,
            vt_list,
            lut_dir,
            args.lut_size,
            args.inv_lut_size,
            inv_encoding=args.inv_encoding,
            pseudolog_params=pl_params if args.inv_encoding == "jplog2" else None,
            pseudolog_lin_min=args.pseudolog_lin_min,
            pseudolog_lin_max=args.pseudolog_lin_max,
            inv_log_lin_min=args.inv_log_lin_min,
            inv_log_lin_max=args.inv_log_lin_max,
            inv_camera_log_lin_break=args.inv_camera_log_lin_break,
            inv_acescct_gray_min=args.inv_acescct_gray_min,
            inv_acescct_gray_max=args.inv_acescct_gray_max,
            inv_remap_mode=args.inv_remap,
            inv_shaper_gamma=args.inv_shaper_gamma,
        )
    print(f"\n  Total: {len(vt_to_clf)} view transforms -> {len(vt_to_clf) * 2} CLF files")
    print()

    target_ver = args.target_ocio_version

    print("Baking 1D LUTs for incompatible BuiltIns...")
    curve_lut_files, csc_lut_files, display_eotf_lut_files = bake_1d_luts(
        bake_cfg, lut_dir, target_version=target_ver
    )
    total_1d = len(curve_lut_files) + len(csc_lut_files) + len(display_eotf_lut_files)
    print(f"\n  Total: {total_1d} 1D LUTs")
    print()

    ver_tag = f"v{target_ver}-clf"
    print(f"Generating OCIO {target_ver} config...")
    config_filename = os.path.basename(args.reference_config)
    new_filename = re.sub(r'ocio-v2\.[45]', f'ocio-{ver_tag}', config_filename)
    if new_filename != config_filename:
        config_filename = new_filename
    else:
        config_filename = config_filename.replace(".ocio", f"-{ver_tag}.ocio")
    output_config_path = os.path.join(args.output_dir, config_filename)
    generate_v23_config(
        args.reference_config, vt_to_clf,
        curve_lut_files, csc_lut_files, output_config_path,
        display_eotf_lut_files=display_eotf_lut_files or None,
    )
    print(f"  Written: {output_config_path}")

    if target_ver == "2.1":
        v21_path = downgrade_v23_to_v21(output_config_path)
        print(f"  Downgraded to OCIO 2.1: {v21_path}")

    validate_config(output_config_path, target_version=target_ver)

    print("\nDone!")


if __name__ == "__main__":
    main()
