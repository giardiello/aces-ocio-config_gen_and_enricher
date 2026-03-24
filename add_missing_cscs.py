#!/usr/bin/env python3
"""
Add missing ACES 2.0 CSC color spaces to CLF-based OCIO configs.

Uses PyOpenColorIO to load the config, add color spaces programmatically,
and serialize back — avoiding fragile YAML text manipulation.
"""

import os
import sys
import re

import PyOpenColorIO as ocio

# BT.2020 to ACES2065-1 (AP0) matrix — from the official ACES v2.0 config.
# Used inline instead of ColorSpaceTransform(src="Linear Rec.2020") so the
# Canon CLog color spaces work in reference configs (which lack that CS).
BT2020_TO_AP0_MATRIX = [
    0.679085634706913, 0.157700914643159, 0.163213450649929, 0,
    0.0460020030800595, 0.859054673002905, 0.0949433239170316, 0,
    -0.000573943187616201, 0.0284677684080262, 0.972106174779585, 0,
    0, 0, 0, 1,
]

# ---------------------------------------------------------------------------
# URNs to add to existing color spaces
# ---------------------------------------------------------------------------
URNS_FOR_EXISTING = {
    "ADX10": [
        "urn:ampas:aces:transformId:v2.0:CSC.Academy.ADX10_to_ACES.a2.v1",
    ],
    "ADX16": [
        "urn:ampas:aces:transformId:v2.0:CSC.Academy.ADX16_to_ACES.a2.v1",
    ],
    "ACES2065-1": [
        "urn:ampas:aces:transformId:v2.0:CSC.Academy.Unity.a2.v1",
    ],
}


def build_acesproxy(config):
    cs = ocio.ColorSpace()
    cs.setName("ACESproxy")
    cs.setFamily("ACES")
    cs.setBitDepth(ocio.BIT_DEPTH_F32)
    cs.setDescription("Convert ACESproxy to ACES2065-1")
    cs.setIsData(False)
    cs.addCategory("file-io")
    cs.addCategory("working-space")
    cs.addCategory("texture")
    bt = ocio.BuiltinTransform()
    bt.setStyle("ACESproxy10i_to_ACES2065-1")
    cs.setTransform(bt, ocio.COLORSPACE_DIR_TO_REFERENCE)
    return cs


def _bake_curve_to_1d(style, out_path, lut_size=4096):
    """Bake a CURVE BuiltinTransform to a .spi1d file."""
    if os.path.isfile(out_path):
        return
    raw = ocio.Config.CreateRaw()
    bt = ocio.BuiltinTransform(style=style)
    proc = raw.getProcessor(bt)
    cpu = proc.getDefaultCPUProcessor()
    import array
    vals = []
    for i in range(lut_size):
        t = i / (lut_size - 1)
        px = array.array('f', [t, t, t])
        cpu.applyRGB(px)
        vals.append(px[0])
    with open(out_path, 'w') as f:
        f.write(f"Version 1\n")
        f.write(f"From 0.0 1.0\n")
        f.write(f"Length {lut_size}\n")
        f.write("Components 1\n")
        f.write("{\n")
        for v in vals:
            f.write(f"        {v:.10f}\n")
        f.write("}\n")
    print(f"  Baked 1D LUT: {out_path}")


def build_canonlog2_bt2020(config, lut_dir=None):
    cs = ocio.ColorSpace()
    cs.setName("CanonLog2 BT2020")
    cs.setFamily("Input/Canon")
    cs.setBitDepth(ocio.BIT_DEPTH_F32)
    cs.setDescription("Convert Canon Log 2 BT2020 to ACES2065-1")
    cs.setIsData(False)
    cs.addCategory("file-io")
    gt = ocio.GroupTransform()
    version = config.getMajorVersion() + config.getMinorVersion() / 10.0
    if version < 2.2 and lut_dir:
        lut_name = "CURVE_CANON_CLOG2_to_LINEAR.spi1d"
        _bake_curve_to_1d("CURVE - CANON_CLOG2_to_LINEAR",
                          os.path.join(lut_dir, lut_name))
        gt.appendTransform(ocio.FileTransform(src=lut_name, interpolation=ocio.INTERP_LINEAR))
    else:
        gt.appendTransform(ocio.BuiltinTransform("CURVE - CANON_CLOG2_to_LINEAR"))
    gt.appendTransform(ocio.MatrixTransform(matrix=BT2020_TO_AP0_MATRIX))
    cs.setTransform(gt, ocio.COLORSPACE_DIR_TO_REFERENCE)
    return cs


def build_canonlog3_bt2020(config, lut_dir=None):
    cs = ocio.ColorSpace()
    cs.setName("CanonLog3 BT2020")
    cs.setFamily("Input/Canon")
    cs.setBitDepth(ocio.BIT_DEPTH_F32)
    cs.setDescription("Convert Canon Log 3 BT2020 to ACES2065-1")
    cs.setIsData(False)
    cs.addCategory("file-io")
    gt = ocio.GroupTransform()
    version = config.getMajorVersion() + config.getMinorVersion() / 10.0
    if version < 2.2 and lut_dir:
        lut_name = "CURVE_CANON_CLOG3_to_LINEAR.spi1d"
        _bake_curve_to_1d("CURVE - CANON_CLOG3_to_LINEAR",
                          os.path.join(lut_dir, lut_name))
        gt.appendTransform(ocio.FileTransform(src=lut_name, interpolation=ocio.INTERP_LINEAR))
    else:
        gt.appendTransform(ocio.BuiltinTransform("CURVE - CANON_CLOG3_to_LINEAR"))
    gt.appendTransform(ocio.MatrixTransform(matrix=BT2020_TO_AP0_MATRIX))
    cs.setTransform(gt, ocio.COLORSPACE_DIR_TO_REFERENCE)
    return cs


def build_slog1_sgamut(config):
    cs = ocio.ColorSpace()
    cs.setName("S-Log1 S-Gamut")
    cs.setFamily("Input/Sony")
    cs.setBitDepth(ocio.BIT_DEPTH_F32)
    cs.setDescription("S-Log1 - S-Gamut")
    cs.setIsData(False)
    cs.setAllocation(ocio.ALLOCATION_UNIFORM)
    cs.setAllocationVars([0.0, 1.0])
    gt = ocio.GroupTransform()
    gt.appendTransform(ocio.FileTransform(src="S-Log1_to_linear.spi1d", interpolation=ocio.INTERP_LINEAR))
    gt.appendTransform(ocio.MatrixTransform(matrix=[
        0.754339, 0.133697, 0.111968, 0,
        0.0211981, 1.00541, -0.0266105, 0,
        -0.00975699, 0.00450856, 1.00525, 0,
        0, 0, 0, 1]))
    cs.setTransform(gt, ocio.COLORSPACE_DIR_TO_REFERENCE)
    return cs


def build_slog2_sgamut_daylight(config):
    cs = ocio.ColorSpace()
    cs.setName("S-Log2 S-Gamut Daylight")
    cs.setFamily("Input/Sony")
    cs.setBitDepth(ocio.BIT_DEPTH_F32)
    cs.setDescription("S-Log2 - S-Gamut Daylight")
    cs.setIsData(False)
    cs.setAllocation(ocio.ALLOCATION_UNIFORM)
    cs.setAllocationVars([0.0, 1.0])
    gt = ocio.GroupTransform()
    gt.appendTransform(ocio.FileTransform(src="S-Log2_to_linear.spi1d", interpolation=ocio.INTERP_LINEAR))
    gt.appendTransform(ocio.MatrixTransform(matrix=[
        0.876446, 0.0145412, 0.109013, 0,
        0.0774075, 0.952957, -0.0303647, 0,
        0.0573564, -0.115107, 1.05775, 0,
        0, 0, 0, 1]))
    cs.setTransform(gt, ocio.COLORSPACE_DIR_TO_REFERENCE)
    return cs


def build_slog2_sgamut_tungsten(config):
    cs = ocio.ColorSpace()
    cs.setName("S-Log2 S-Gamut Tungsten")
    cs.setFamily("Input/Sony")
    cs.setBitDepth(ocio.BIT_DEPTH_F32)
    cs.setDescription("S-Log2 - S-Gamut Tungsten")
    cs.setIsData(False)
    cs.setAllocation(ocio.ALLOCATION_UNIFORM)
    cs.setAllocationVars([0.0, 1.0])
    gt = ocio.GroupTransform()
    gt.appendTransform(ocio.FileTransform(src="S-Log2_to_linear.spi1d", interpolation=ocio.INTERP_LINEAR))
    gt.appendTransform(ocio.MatrixTransform(matrix=[
        1.01102, -0.136253, 0.125229, 0,
        0.101199, 0.95622, -0.0574191, 0,
        0.0600767, -0.101019, 1.04094, 0,
        0, 0, 0, 1]))
    cs.setTransform(gt, ocio.COLORSPACE_DIR_TO_REFERENCE)
    return cs


NEW_CS_BUILDERS = [
    ("ACESproxy", build_acesproxy, False),
    ("CanonLog2 BT2020", build_canonlog2_bt2020, True),
    ("CanonLog3 BT2020", build_canonlog3_bt2020, True),
    ("S-Log1 S-Gamut", build_slog1_sgamut, False),
    ("S-Log2 S-Gamut Daylight", build_slog2_sgamut_daylight, False),
    ("S-Log2 S-Gamut Tungsten", build_slog2_sgamut_tungsten, False),
]

# URN -> color space name mapping for description injection
CS_URN_MAP = {
    "ACESproxy": [
        "urn:ampas:aces:transformId:v2.0:CSC.Academy.ACESproxy10i_to_ACES.a2.v1",
        "urn:ampas:aces:transformId:v2.0:CSC.Academy.ACESproxy12i_to_ACES.a2.v1",
        "urn:ampas:aces:transformId:v2.0:CSC.Academy.ACES_to_ACESproxy10i.a2.v1",
        "urn:ampas:aces:transformId:v2.0:CSC.Academy.ACES_to_ACESproxy12i.a2.v1",
    ],
    "CanonLog2 BT2020": [
        "urn:ampas:aces:transformId:v2.0:CSC.Canon.CLog2_BT2020_to_ACES.a1.v1",
        "urn:ampas:aces:transformId:v2.0:CSC.Canon.ACES_to_CLog2_BT2020.a1.v1",
    ],
    "CanonLog3 BT2020": [
        "urn:ampas:aces:transformId:v2.0:CSC.Canon.CLog3_BT2020_to_ACES.a1.v1",
        "urn:ampas:aces:transformId:v2.0:CSC.Canon.ACES_to_CLog3_BT2020.a1.v1",
    ],
    "S-Log1 S-Gamut": [
        "urn:ampas:aces:transformId:v2.0:CSC.Sony.SLog1_SGamut_10i_to_ACES.a2.v1",
        "urn:ampas:aces:transformId:v2.0:CSC.Sony.SLog1_SGamut_12i_to_ACES.a2.v1",
    ],
    "S-Log2 S-Gamut Daylight": [
        "urn:ampas:aces:transformId:v2.0:CSC.Sony.SLog2_SGamut_Daylight_10i_to_ACES.a2.v1",
        "urn:ampas:aces:transformId:v2.0:CSC.Sony.SLog2_SGamut_Daylight_12i_to_ACES.a2.v1",
    ],
    "S-Log2 S-Gamut Tungsten": [
        "urn:ampas:aces:transformId:v2.0:CSC.Sony.SLog2_SGamut_Tungsten_10i_to_ACES.a2.v1",
        "urn:ampas:aces:transformId:v2.0:CSC.Sony.SLog2_SGamut_Tungsten_12i_to_ACES.a2.v1",
    ],
}


def add_urns_to_description(config, cs_name, urns):
    """Add ACEStransformID URNs to a color space's description field."""
    cs = config.getColorSpace(cs_name)
    if not cs:
        print(f"  Warning: '{cs_name}' not found")
        return
    desc = cs.getDescription() or ""
    new_urns = [u for u in urns if u not in desc]
    if not new_urns:
        print(f"  '{cs_name}': all URNs already present")
        return
    urn_lines = "\n".join(f"ACEStransformID: {u}" for u in new_urns)
    if desc:
        desc = desc.rstrip() + "\n\n" + urn_lines
    else:
        desc = urn_lines
    cs.setDescription(desc)
    config.addColorSpace(cs)
    print(f"  '{cs_name}': added {len(new_urns)} URN(s)")


def process_config(config_path):
    """Add missing CSCs and URNs to a single config file."""
    print(f"\nProcessing: {config_path}")

    config_dir = os.path.dirname(os.path.abspath(config_path))
    old_cwd = os.getcwd()
    os.chdir(config_dir)

    try:
        config = ocio.Config.CreateFromFile(os.path.basename(config_path))
        version = config.getMajorVersion() + config.getMinorVersion() / 10.0
        print(f"  Profile version: {version}")

        # Determine lut directory
        lut_dir = os.path.join(config_dir, "luts")
        os.makedirs(lut_dir, exist_ok=True)

        # 1. Add new color spaces
        added = 0
        for cs_name, builder, needs_lut_dir in NEW_CS_BUILDERS:
            if config.getColorSpace(cs_name):
                print(f"  '{cs_name}': already exists, skipping")
                continue
            if needs_lut_dir:
                cs = builder(config, lut_dir=lut_dir)
            else:
                cs = builder(config)
            config.addColorSpace(cs)
            added += 1
            print(f"  Added: {cs.getName()}")
        print(f"  Total new color spaces: {added}")

        # 2. Add URNs to new color spaces' descriptions
        for cs_name, urns in CS_URN_MAP.items():
            add_urns_to_description(config, cs_name, urns)

        # 3. Add URNs to existing color spaces
        for cs_name, urns in URNS_FOR_EXISTING.items():
            add_urns_to_description(config, cs_name, urns)

        # 4. Serialize via OCIO (preserves version-correct format)
        serialized = config.serialize()

        # Write back
        with open(os.path.basename(config_path), 'w') as f:
            f.write(serialized)
        print(f"  Saved: {config_path}")

        # 5. Validate
        config.validate()
        print(f"  Validation: PASSED")

    except Exception as e:
        print(f"  ERROR: {e}")
    finally:
        os.chdir(old_cwd)


def main():
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "OUTPUT", "FINAL_CLF_ACES_2_versions")

    configs = [
        os.path.join(base, "studio-all-views_v2.3-clf",
                     "studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
        os.path.join(base, "studio-all-views_v2.1-clf",
                     "studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.1-clf.ocio"),
        os.path.join(base, "studio_v2.3-clf",
                     "studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
        os.path.join(base, "studio_v2.1-clf",
                     "studio-config-v3.0.0_aces-v2.0_ocio-v2.1-clf.ocio"),
    ]

    for path in configs:
        if not os.path.isfile(path):
            print(f"  SKIP (not found): {path}")
            continue
        process_config(path)


if __name__ == "__main__":
    main()
