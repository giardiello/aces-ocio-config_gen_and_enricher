#!/usr/bin/env python3
"""
Precision of a single 3D LUT baked from Display -> ACES (inverse display+view).

Bakes a N³ mesh (default 65³) in display space [0,1]³, each node storing the
ACES2065-1 value from the inverse display+view transform. Then runs roundtrip:
  ACES -> forward (display+view) -> trilinear interpolate in LUT -> ACES
and reports max error (CV) per scene-linear band.

So this answers: "If you bake Display -> ACES straight with a 65³ LUT, what
precision do you get?" (All in scene-linear bands; LUT is in display space.)

Usage:
  python test_display_to_aces_lut_precision.py [config.ocio] [--display NAME] [--view NAME] [--size 65]

Requires: numpy, PyOpenColorIO.
"""

import argparse
import os
import sys

try:
    import numpy as np
    import PyOpenColorIO as ocio
except ImportError as e:
    print("Error: need numpy and PyOpenColorIO.", e)
    sys.exit(1)

# Scene-linear bands (same as inverse roundtrip test)
BANDS = [
    ("Shadow (0.001-0.01)", 0.001, 0.01, 20),
    ("Low-mid (0.01-0.1)", 0.01, 0.1, 30),
    ("Upper (0.1-0.5)", 0.1, 0.5, 40),
    ("Bright (0.5-1)", 0.5, 1.0, 25),
    ("Super bright (1-2)", 1.0, 2.0, 20),
    ("Very bright (2-10)", 2.0, 10.0, 25),
    ("High (10-50)", 10.0, 50.0, 30),
    ("Very high (50-100)", 50.0, 100.0, 25),
    ("ACEScct top (100-222)", 100.0, 222.0, 30),
]


def trilinear_interp(grid, r, g, b):
    """
    grid: (size, size, size, 3) float32, display [0,1] -> ACES.
    r, g, b: arrays of shape (n,) in [0, 1] (display coords).
    Returns (n, 3) interpolated ACES values.
    """
    n = int(np.size(r))
    r = np.atleast_1d(r).astype(np.float64).ravel()
    g = np.atleast_1d(g).astype(np.float64).ravel()
    b = np.atleast_1d(b).astype(np.float64).ravel()
    size = grid.shape[0]
    max_i = size - 1
    # Map [0,1] -> index; clamp so we don't go out of bounds
    r = np.clip(r, 0.0, 1.0)
    g = np.clip(g, 0.0, 1.0)
    b = np.clip(b, 0.0, 1.0)
    # For size 65, indices 0..64; coord 1.0 -> index 64
    ri = r * max_i
    gi = g * max_i
    bi = b * max_i
    i0 = np.floor(ri).astype(np.int32)
    j0 = np.floor(gi).astype(np.int32)
    k0 = np.floor(bi).astype(np.int32)
    i0 = np.clip(i0, 0, max_i - 1)
    j0 = np.clip(j0, 0, max_i - 1)
    k0 = np.clip(k0, 0, max_i - 1)
    i1 = np.minimum(i0 + 1, max_i)
    j1 = np.minimum(j0 + 1, max_i)
    k1 = np.minimum(k0 + 1, max_i)
    u = ri - i0
    v = gi - j0
    w = bi - k0
    out = np.empty((n, 3), dtype=np.float32)
    for c in range(3):
        c000 = grid[i0, j0, k0, c]
        c100 = grid[i1, j0, k0, c]
        c010 = grid[i0, j1, k0, c]
        c110 = grid[i1, j1, k0, c]
        c001 = grid[i0, j0, k1, c]
        c101 = grid[i1, j0, k1, c]
        c011 = grid[i0, j1, k1, c]
        c111 = grid[i1, j1, k1, c]
        c00 = c000 * (1 - u) + c100 * u
        c01 = c001 * (1 - u) + c101 * u
        c10 = c010 * (1 - u) + c110 * u
        c11 = c011 * (1 - u) + c111 * u
        c0 = c00 * (1 - v) + c10 * v
        c1 = c01 * (1 - v) + c11 * v
        out[:, c] = (c0 * (1 - w) + c1 * w).astype(np.float32)
    return out


def bake_display_to_aces_grid(config, display, view, size, config_dir):
    """Fill (size, size, size, 3) with ACES values for display [0,1]^3 via inverse DVT."""
    dvt_inv = ocio.DisplayViewTransform()
    dvt_inv.setSrc("ACES2065-1")
    dvt_inv.setDisplay(display)
    dvt_inv.setView(view)
    dvt_inv.setDirection(ocio.TRANSFORM_DIR_INVERSE)
    proc = config.getProcessor(dvt_inv)
    cpu = proc.getDefaultCPUProcessor()

    coords = np.linspace(0.0, 1.0, size, dtype=np.float32)
    # Build flat list of (r,g,b) display points
    rr, gg, bb = np.meshgrid(coords, coords, coords, indexing="ij")
    pixels = np.stack([rr.ravel(), gg.ravel(), bb.ravel()], axis=1).astype(np.float32)
    n = pixels.shape[0]
    buf = ocio.PackedImageDesc(pixels.ravel(), n, 1, 3)
    cpu.apply(buf)
    aces = pixels.ravel().reshape(n, 3).copy()
    grid = aces.reshape(size, size, size, 3)
    return grid


def run_roundtrip_via_lut(config_path, display, view, size, bands=None):
    """Bake size³ display->ACES grid, then measure roundtrip error per band."""
    config_path = os.path.abspath(config_path)
    config_dir = os.path.dirname(config_path)
    if not os.path.isfile(config_path):
        print(f"Config not found: {config_path}")
        return None
    os.chdir(config_dir)
    config = ocio.Config.CreateFromFile(config_path)

    # Forward: ACES2065-1 -> display
    dvt_fwd = ocio.DisplayViewTransform()
    dvt_fwd.setSrc("ACES2065-1")
    dvt_fwd.setDisplay(display)
    dvt_fwd.setView(view)
    dvt_fwd.setDirection(ocio.TRANSFORM_DIR_FORWARD)
    proc_fwd = config.getProcessor(dvt_fwd)
    cpu_fwd = proc_fwd.getDefaultCPUProcessor()

    print(f"Baking {size}³ display -> ACES grid...")
    grid = bake_display_to_aces_grid(config, display, view, size, config_dir)
    print("Done.")

    if bands is None:
        bands = BANDS
    band_errors = []
    for name, lo, hi, n in bands:
        if n <= 1:
            vals = np.array([lo if lo == hi else (lo + hi) / 2.0], dtype=np.float32)
        else:
            vals = np.linspace(lo, hi, n, dtype=np.float32)
        pixels = np.stack([vals, vals, vals], axis=1)  # (n, 3) ACES
        orig = pixels.copy()

        # ACES -> display
        buf = ocio.PackedImageDesc(pixels.ravel(), len(pixels), 1, 3)
        cpu_fwd.apply(buf)
        disp = pixels.ravel().reshape(-1, 3).copy()

        # Trilinear in grid (display -> ACES)
        aces_back = trilinear_interp(grid, disp[:, 0], disp[:, 1], disp[:, 2])

        err = np.abs(aces_back - orig)
        max_err_linear = float(np.max(err))
        cv_error = max_err_linear * 100.0
        band_errors.append((name, cv_error, max_err_linear))

    return band_errors


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    default_config = os.path.join(
        base, "INPUT_OCIO", "STUDIO", "studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio"
    )
    ap = argparse.ArgumentParser(
        description="Precision of a 65³ (or N³) Display->ACES LUT roundtrip"
    )
    ap.add_argument("config", nargs="?", default=default_config, help="OCIO config path")
    ap.add_argument(
        "--display",
        default="sRGB - Display",
        help="Display name (default: sRGB - Display)",
    )
    ap.add_argument(
        "--view",
        default="ACES 2.0 - SDR 100 nits (Rec.709)",
        help="View name",
    )
    ap.add_argument("--size", type=int, default=65, help="LUT grid size (default 65)")
    args = ap.parse_args()

    print("Display -> ACES LUT roundtrip precision (baked inverse, trilinear interp)")
    print(f"Config: {args.config}")
    print(f"Display: {args.display}, View: {args.view}")
    print(f"LUT: {args.size}³ mesh in display [0,1]³ -> ACES2065-1")
    print()

    result = run_roundtrip_via_lut(args.config, args.display, args.view, args.size)
    if result is None:
        sys.exit(1)

    print(f"{'Band':<28} {'Max error (CV)':>14} {'Max diff (linear)':>18}")
    print("-" * 62)
    for name, cv_err, lin_err in result:
        print(f"{name:<28} {cv_err:>14.2f} {lin_err:>18.6f}")

    # Summary
    max_cv = max(r[1] for r in result)
    mean_cv = np.mean([r[1] for r in result])
    print()
    print(f"Max over bands: {max_cv:.2f} CV   Mean over bands: {mean_cv:.2f} CV")
    sys.exit(0)


if __name__ == "__main__":
    main()
