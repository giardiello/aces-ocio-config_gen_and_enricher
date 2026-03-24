#!/usr/bin/env python3
"""
Render ACES2065-1 EXR inputs through all OCIO display+view combos as DPX16,
then apply the inverse transform and write ACEScct DPX16.

Renders through BOTH configs:
  - Reference BuiltIn (v2.4) -- the ground truth you can't access in Nuke
  - CLF-based (v2.1) -- what Nuke will use, rendered here for offline comparison

Output structure:
  <output_dir>/
    REF_v24/
      forward/   <input>_<display>_<view>.dpx       (ACES2065-1 -> display DPX16)
      inverse/   <input>_<display>_<view>_inv.dpx    (display -> ACEScct DPX16)
    CLF_v21/
      forward/   <input>_<display>_<view>.dpx
      inverse/   <input>_<display>_<view>_inv.dpx

Usage:
    python3 render_comparison_dpx.py <input_exr> [<input_exr2> ...] [-o <output_dir>]
"""

import argparse
import os
import sys
import re

import numpy as np
import PyOpenColorIO as ocio
import OpenImageIO as oiio


def sanitize_name(name):
    """Convert display/view name to filesystem-safe string."""
    s = re.sub(r'[^\w\s\-]', '', name)
    s = re.sub(r'\s+', '_', s.strip())
    return s


def read_exr(filepath):
    """Read EXR, return (pixels_float32_Nx3, width, height, nchannels)."""
    inp = oiio.ImageInput.open(filepath)
    if inp is None:
        print(f"  ERROR: cannot open {filepath}")
        sys.exit(1)
    spec = inp.spec()
    pixels = np.array(inp.read_image(format=oiio.FLOAT), dtype=np.float32)
    inp.close()
    h, w, c = spec.height, spec.width, spec.nchannels
    pixels = pixels.reshape(h * w, c)
    if c > 3:
        rgb = pixels[:, :3]
    else:
        rgb = pixels
    return rgb, w, h, c


def write_dpx16(filepath, pixels_flat, width, height):
    """Write 16-bit DPX from float32 Nx3 pixel array."""
    pixels_clipped = np.clip(pixels_flat, 0.0, 1.0)
    pixels_uint16 = (pixels_clipped * 65535.0 + 0.5).astype(np.uint16)
    pixels_uint16 = pixels_uint16.reshape(height, width, 3)

    spec = oiio.ImageSpec(width, height, 3, oiio.UINT16)
    spec.attribute("oiio:BitsPerSample", 16)
    out = oiio.ImageOutput.create(filepath)
    if out is None:
        print(f"  ERROR: cannot create {filepath}")
        return False
    out.open(filepath, spec)
    out.write_image(pixels_uint16)
    out.close()
    return True


def get_display_view_combos(config):
    """Get all (display, view) combos that have a view transform (skip Raw, Un-tone-mapped)."""
    combos = []
    for display in config.getDisplays():
        for view in config.getViews(display):
            vt_name = config.getDisplayViewTransformName(display, view)
            if not vt_name:
                continue
            if 'Un-tone-mapped' in vt_name:
                continue
            combos.append((display, view))
    return combos


def process_forward(config, display, view, pixels):
    """ACES2065-1 -> display encoding."""
    dvt = ocio.DisplayViewTransform()
    dvt.setSrc('ACES2065-1')
    dvt.setDisplay(display)
    dvt.setView(view)
    proc = config.getProcessor(dvt)
    cpu = proc.getDefaultCPUProcessor()
    result = pixels.copy()
    cpu.apply(ocio.PackedImageDesc(result, len(result), 1, 3))
    return result


def process_inverse_to_acescct(config, display, view, display_pixels):
    """Display encoding -> ACEScct via inverse DisplayViewTransform then CSC."""
    dvt = ocio.DisplayViewTransform()
    dvt.setSrc('ACES2065-1')
    dvt.setDisplay(display)
    dvt.setView(view)

    proc_inv = config.getProcessor(dvt, ocio.TRANSFORM_DIR_INVERSE)
    cpu_inv = proc_inv.getDefaultCPUProcessor()

    result = display_pixels.copy()
    cpu_inv.apply(ocio.PackedImageDesc(result, len(result), 1, 3))

    csc = ocio.ColorSpaceTransform()
    csc.setSrc('ACES2065-1')
    csc.setDst('ACEScct')
    proc_csc = config.getProcessor(csc)
    cpu_csc = proc_csc.getDefaultCPUProcessor()
    cpu_csc.apply(ocio.PackedImageDesc(result, len(result), 1, 3))

    return result


def render_config(config, config_label, combos, input_files, output_dir):
    """Render all combos for one config."""
    fwd_dir = os.path.join(output_dir, config_label, "forward")
    inv_dir = os.path.join(output_dir, config_label, "inverse")
    os.makedirs(fwd_dir, exist_ok=True)
    os.makedirs(inv_dir, exist_ok=True)

    for input_path in input_files:
        basename = os.path.splitext(os.path.basename(input_path))[0]
        print(f"\n  Input: {basename}")
        rgb, w, h, _ = read_exr(input_path)
        print(f"    {w}x{h}, {len(rgb)} pixels")

        for display, view in combos:
            tag = f"{basename}_{sanitize_name(display)}_{sanitize_name(view)}"

            fwd_pixels = process_forward(config, display, view, rgb)
            fwd_path = os.path.join(fwd_dir, f"{tag}.dpx")
            write_dpx16(fwd_path, fwd_pixels, w, h)

            inv_pixels = process_inverse_to_acescct(config, display, view, fwd_pixels)
            inv_path = os.path.join(inv_dir, f"{tag}_inv.dpx")
            write_dpx16(inv_path, inv_pixels, w, h)

            print(f"    {display} / {view}  ->  fwd + inv OK")


def main():
    parser = argparse.ArgumentParser(
        description="Render ACES2065-1 EXRs through all display+view combos as DPX16"
    )
    parser.add_argument("inputs", nargs='+', help="Input EXR files (ACES2065-1)")
    parser.add_argument("-o", "--output-dir", default=None,
                        help="Output directory (default: OUTPUT/render_comparison)")
    args = parser.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))

    ref_path = os.path.join(base, 'INPUT_OCIO/STUDIO/studio-config-v3.0.0_aces-v2.0_ocio-v2.4.ocio')
    clf_dir = os.path.join(base, 'OUTPUT/studio-config-v3.0.0_aces-v2.0_ocio-v2.1_CLF')
    clf_path = os.path.join(clf_dir, 'studio-config-v3.0.0_aces-v2.0_ocio-v2.1.ocio')

    output_dir = args.output_dir or os.path.join(base, 'OUTPUT', 'render_comparison')
    os.makedirs(output_dir, exist_ok=True)

    os.environ['OCIO'] = clf_path
    os.chdir(clf_dir)

    print("Loading reference config (v2.4 BuiltIn)...")
    ref_config = ocio.Config.CreateFromFile(ref_path)
    print(f"  Version: {ref_config.getMajorVersion()}.{ref_config.getMinorVersion()}")

    print("Loading CLF config (v2.1)...")
    clf_config = ocio.Config.CreateFromFile(clf_path)
    print(f"  Version: {clf_config.getMajorVersion()}.{clf_config.getMinorVersion()}")

    ref_combos = get_display_view_combos(ref_config)
    clf_combos_set = set(get_display_view_combos(clf_config))
    combos = [c for c in ref_combos if c in clf_combos_set]
    print(f"\n{len(combos)} display+view combinations to render")

    for f in args.inputs:
        if not os.path.exists(f):
            print(f"ERROR: {f} not found")
            sys.exit(1)

    print(f"\n{'='*60}")
    print("Rendering REF (v2.4 BuiltIn)...")
    print(f"{'='*60}")
    render_config(ref_config, "REF_v24", combos, args.inputs, output_dir)

    print(f"\n{'='*60}")
    print("Rendering CLF (v2.1)...")
    print(f"{'='*60}")
    render_config(clf_config, "CLF_v21", combos, args.inputs, output_dir)

    total = len(combos) * len(args.inputs) * 2 * 2
    print(f"\n{'='*60}")
    print(f"Done. {total} DPX files written to: {output_dir}")
    print(f"  REF_v24/forward/  - Reference BuiltIn forward renders")
    print(f"  REF_v24/inverse/  - Reference BuiltIn inverse -> ACEScct")
    print(f"  CLF_v21/forward/  - CLF v2.1 forward renders")
    print(f"  CLF_v21/inverse/  - CLF v2.1 inverse -> ACEScct")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
