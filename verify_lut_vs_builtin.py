#!/usr/bin/env python3
"""
Verify LUT-based OCIO config against the reference BuiltIn config.

Processes a test image (33-mesh CMS file or generated test grid) through every
(display, view) combination in both configs, compares pixel outputs, and reports
per-channel max/mean deltas with a configurable threshold.

Usage:
    python3.14 verify_lut_vs_builtin.py <reference_config> <lut_config> [--test-image <path>] [--threshold <value>]

    If no test image is provided, uses test_assets/CMS_32.exr when present, otherwise
    generates a uniform 33^3 grid covering [0, 1].

Output:
    CSV report with columns: display, view, max_delta_R, max_delta_G, max_delta_B,
    mean_delta, max_delta, status

Requires: PyOpenColorIO, numpy.
"""

import argparse
import csv
import os
import sys

import numpy as np
import PyOpenColorIO as ocio


def generate_test_grid(size=33):
    """Generate a uniform 3D grid of RGB test values in [0, 1]."""
    coords = np.linspace(0.0, 1.0, size, dtype=np.float32)
    b, g, r = np.meshgrid(coords, coords, coords, indexing='ij')
    grid = np.stack([r, g, b], axis=-1)
    return grid.reshape(-1, 3)


def load_test_image(filepath):
    """
    Load a test image file. Supports:
    - .exr, .tif, .tiff, .hdr, .png, .jpg: via OpenImageIO (flattened to Nx3 RGB)
    - .csv: comma-separated RGB triplets, one per line
    - .cube: extract the LUT grid values as test points
    - .npy: numpy array
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext in ('.exr', '.tif', '.tiff', '.hdr', '.png', '.jpg', '.jpeg'):
        import OpenImageIO as oiio
        inp = oiio.ImageInput.open(filepath)
        if inp is None:
            print(f"Error: could not open {filepath}: {oiio.geterror()}")
            sys.exit(1)
        spec = inp.spec()
        print(f"  Image: {spec.width}x{spec.height}, {spec.nchannels} channels")
        pixels = inp.read_image(format=oiio.FLOAT)
        inp.close()
        pixels = np.array(pixels, dtype=np.float32)
        if pixels.ndim == 3:
            pixels = pixels.reshape(-1, pixels.shape[-1])
        if pixels.shape[1] > 3:
            pixels = pixels[:, :3]
        return pixels

    if ext == '.npy':
        data = np.load(filepath).astype(np.float32)
        if data.ndim == 1:
            data = data.reshape(-1, 3)
        return data

    if ext == '.csv':
        rows = []
        with open(filepath, 'r') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 3:
                    try:
                        rows.append([float(row[0]), float(row[1]), float(row[2])])
                    except ValueError:
                        continue
        return np.array(rows, dtype=np.float32)

    if ext == '.cube':
        rows = []
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or line.startswith('TITLE') or \
                   line.startswith('LUT_') or line.startswith('DOMAIN'):
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except ValueError:
                        continue
        return np.array(rows, dtype=np.float32)

    print(f"Error: unsupported test image format: {ext}")
    sys.exit(1)


def get_display_view_combos(config, skip_untone_mapped=True):
    """Get all (display, view) combinations that use view transforms."""
    combos = []
    for display in config.getDisplays():
        for view in config.getViews(display):
            vt_name = config.getDisplayViewTransformName(display, view)
            if not vt_name:
                continue
            if skip_untone_mapped and 'Un-tone-mapped' in vt_name:
                continue
            combos.append((display, view))
    return combos


def process_pixels(config, display, view, pixels):
    """Process pixels through a display+view transform."""
    dvt = ocio.DisplayViewTransform()
    dvt.setSrc('ACES2065-1')
    dvt.setDisplay(display)
    dvt.setView(view)

    proc = config.getProcessor(dvt)
    cpu = proc.getDefaultCPUProcessor()

    result = pixels.copy()
    buf = ocio.PackedImageDesc(result, len(result), 1, 3)
    cpu.apply(buf)
    return result


def compare_configs(ref_config, lut_config, test_pixels, threshold, output_csv=None):
    """
    Compare two configs across all display+view combos.
    Returns list of result dicts and overall pass/fail.
    """
    combos = get_display_view_combos(ref_config)

    lut_combos = set(get_display_view_combos(lut_config))
    combos = [c for c in combos if c in lut_combos]

    results = []
    all_pass = True

    print(f"\nComparing {len(combos)} display+view combinations...")
    print(f"Test pixels: {len(test_pixels)} samples")
    print(f"Threshold: max_delta < {threshold}")
    print("-" * 90)

    for display, view in combos:
        ref_result = process_pixels(ref_config, display, view, test_pixels)
        lut_result = process_pixels(lut_config, display, view, test_pixels)

        delta = np.abs(ref_result - lut_result)
        max_delta_per_ch = delta.max(axis=0)
        max_delta = delta.max()
        mean_delta = delta.mean()

        status = "PASS" if max_delta < threshold else "FAIL"
        if status == "FAIL":
            all_pass = False

        result = {
            "display": display,
            "view": view,
            "max_delta_R": max_delta_per_ch[0],
            "max_delta_G": max_delta_per_ch[1],
            "max_delta_B": max_delta_per_ch[2],
            "mean_delta": mean_delta,
            "max_delta": max_delta,
            "status": status,
        }
        results.append(result)

        print(f"  {status}  max={max_delta:.6f}  mean={mean_delta:.6f}  "
              f"R={max_delta_per_ch[0]:.6f} G={max_delta_per_ch[1]:.6f} B={max_delta_per_ch[2]:.6f}  "
              f"{display} / {view}")

    print("-" * 90)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    print(f"Results: {passed} PASS, {failed} FAIL out of {len(results)} combinations")

    if output_csv:
        with open(output_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                "display", "view", "max_delta_R", "max_delta_G", "max_delta_B",
                "mean_delta", "max_delta", "status"
            ])
            writer.writeheader()
            for r in results:
                writer.writerow({
                    k: f"{v:.8f}" if isinstance(v, float) else v
                    for k, v in r.items()
                })
        print(f"\nCSV report: {output_csv}")

    return results, all_pass


def main():
    parser = argparse.ArgumentParser(
        description="Verify LUT-based config against reference BuiltIn config"
    )
    parser.add_argument("reference_config", help="Path to the reference OCIO config (BuiltIn)")
    parser.add_argument("lut_config", help="Path to the LUT-based OCIO config")
    parser.add_argument("--test-image", help="Path to test image (CSV, .cube, or .npy). "
                        "If not provided, generates a 33^3 uniform grid.")
    parser.add_argument("--threshold", type=float, default=0.001,
                        help="Max delta threshold for PASS/FAIL (default: 0.001)")
    parser.add_argument("--output-csv", default=None,
                        help="Path for CSV report output")
    parser.add_argument("--grid-size", type=int, default=33,
                        help="Size of generated test grid if no test image (default: 33)")
    args = parser.parse_args()

    print("Loading reference config...")
    ref_config = ocio.Config.CreateFromFile(args.reference_config)
    print(f"  {args.reference_config}")
    print(f"  Version: {ref_config.getMajorVersion()}.{ref_config.getMinorVersion()}")

    print("Loading LUT-based config...")
    lut_config = ocio.Config.CreateFromFile(args.lut_config)
    print(f"  {args.lut_config}")
    print(f"  Version: {lut_config.getMajorVersion()}.{lut_config.getMinorVersion()}")

    if args.test_image:
        print(f"\nLoading test image: {args.test_image}")
        test_pixels = load_test_image(args.test_image)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
        default_cms = os.path.join(base, "test_assets", "CMS_32.exr")
        if os.path.isfile(default_cms):
            print(f"\nUsing project CMS: {default_cms}")
            test_pixels = load_test_image(default_cms)
        else:
            print(f"\nGenerating {args.grid_size}^3 test grid...")
            test_pixels = generate_test_grid(args.grid_size)

    print(f"  Samples: {len(test_pixels)}")

    output_csv = args.output_csv
    if output_csv is None:
        output_csv = os.path.splitext(args.lut_config)[0] + "_verification.csv"

    results, all_pass = compare_configs(
        ref_config, lut_config, test_pixels, args.threshold, output_csv
    )

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
