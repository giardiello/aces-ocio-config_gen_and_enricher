#!/usr/bin/env python3
"""
Roundtrip precision test for inverse CLFs (ACES -> forward VT -> inverse VT -> ACES).

Reports max error (in CV, 100 * abs diff) per scene-linear band. Bands extend to 222
(scene linear) to cover the full ACEScct range.

Usage:
    python test_inverse_roundtrip_precision.py CONFIG [--luts-dir DIR] [--vt NAME ...] [--csv OUT]
    Defaults: all SDR + HDR view transforms found in the config.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

try:
    import numpy as np
    import PyOpenColorIO as ocio
except ImportError as e:
    print("Error: need numpy and PyOpenColorIO.", e)
    sys.exit(1)

BANDS = [
    ("Shadow (0.001-0.01)",    0.001,  0.01,   40),
    ("Low-mid (0.01-0.1)",     0.01,   0.1,    60),
    ("Upper (0.1-0.5)",        0.1,    0.5,    80),
    ("Bright (0.5-1)",         0.5,    1.0,    50),
    ("Super bright (1-2)",     1.0,    2.0,    40),
    ("Very bright (2-10)",     2.0,    10.0,   50),
    ("High (10-50)",           10.0,   50.0,   60),
    ("Very high (50-100)",     50.0,   100.0,  50),
    ("ACEScct top (100-222)",  100.0,  222.0,  60),
]

DEFAULT_VTS = [
    "ACES 2.0 - SDR 100 nits (Rec.709)",
    "ACES 2.0 - HDR 1000 nits (Rec.2020)",
    "ACES 2.0 - HDR 4000 nits (Rec.2020)",
    "ACES 2.0 - HDR 1000 nits (P3 D65)",
]


def run_roundtrip(config_path: str, vt_name: str) -> list[tuple[str, float, float]] | None:
    config_path = os.path.abspath(config_path)
    if not os.path.isfile(config_path):
        print(f"Config not found: {config_path}")
        return None
    saved_cwd = os.getcwd()
    os.chdir(os.path.dirname(config_path))
    try:
        config = ocio.Config.CreateFromFile(os.path.basename(config_path))

        vt = config.getViewTransform(vt_name)
        if vt is None:
            print(f"ViewTransform not found: {vt_name}")
            return None

        from_ref = vt.getTransform(ocio.VIEWTRANSFORM_DIR_FROM_REFERENCE)
        to_ref = vt.getTransform(ocio.VIEWTRANSFORM_DIR_TO_REFERENCE)
        proc_fwd = config.getProcessor(from_ref)
        proc_inv = config.getProcessor(to_ref)

        cpu_fwd = proc_fwd.getDefaultCPUProcessor()
        cpu_inv = proc_inv.getDefaultCPUProcessor()

        band_errors = []
        for name, lo, hi, n in BANDS:
            if n <= 1:
                vals = np.array([lo if lo == hi else (lo + hi) / 2.0], dtype=np.float32)
            else:
                vals = np.linspace(lo, hi, n, dtype=np.float32)
            pixels = np.stack([vals, vals, vals], axis=1)
            orig = pixels.copy()

            buf = ocio.PackedImageDesc(pixels.ravel(), len(pixels), 1, 3)
            cpu_fwd.apply(buf)
            cpu_inv.apply(buf)

            err = np.abs(pixels.ravel().reshape(-1, 3) - orig)
            max_err_linear = float(np.max(err))
            cv_error = max_err_linear * 100.0
            band_errors.append((name, cv_error, max_err_linear))

        return band_errors
    finally:
        os.chdir(saved_cwd)


def _classify_vt(vt_name: str) -> str:
    if "SDR" in vt_name:
        return "SDR"
    m = re.search(r"(\d+)\s*nits", vt_name)
    if m and int(m.group(1)) > 108:
        return "HDR"
    return "SDR"


def main() -> int:
    base = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Inverse CLF roundtrip precision test")
    ap.add_argument("config", nargs="?",
                    default=os.path.join(base, "OUTPUT", "benchmark_display_shaper",
                                         "studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.3-clf.ocio"))
    ap.add_argument("--luts-dir", default=None, help="LUTs directory (unused, kept for compat)")
    ap.add_argument("--vt", nargs="*", default=None,
                    help="View transform names to test (default: SDR + HDR set)")
    ap.add_argument("--csv", default=None, help="Save results to CSV file")
    ap.add_argument("--threshold", type=float, default=1.0,
                    help="Max acceptable CV error for Upper (0.1-0.5) band (default: 1.0)")
    args = ap.parse_args()

    vt_names = args.vt or DEFAULT_VTS

    print("Inverse CLF roundtrip precision (ACES -> forward VT -> inverse VT -> ACES)")
    print(f"Config: {args.config}")
    print()

    csv_rows = []
    worst_upper_cv = 0.0
    any_fail = False

    for vt_name in vt_names:
        vt_class = _classify_vt(vt_name)
        print(f"=== {vt_name} ({vt_class}) ===")
        result = run_roundtrip(args.config, vt_name)
        if result is None:
            print("  SKIP (not found)\n")
            continue

        print(f"  {'Band':<28} {'Max CV':>10} {'Max linear':>14}")
        print(f"  {'-' * 54}")
        for name, cv_err, lin_err in result:
            print(f"  {name:<28} {cv_err:>10.2f} {lin_err:>14.6f}")
            csv_rows.append([vt_name, vt_class, name, f"{cv_err:.4f}", f"{lin_err:.8f}"])

        upper_cv = next((cv for (n, cv, _) in result if "Upper (0.1-0.5)" in n), 0.0)
        worst_upper_cv = max(worst_upper_cv, upper_cv)
        status = "PASS" if upper_cv <= args.threshold else "FAIL"
        if status == "FAIL":
            any_fail = True
        print(f"  Upper (0.1-0.5): {upper_cv:.2f} CV -> {status}")
        print()

    if args.csv:
        os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ViewTransform", "Type", "Band", "Max CV", "Max Linear"])
            w.writerows(csv_rows)
        print(f"Results saved to {args.csv}")

    print(f"Worst Upper (0.1-0.5) across all VTs: {worst_upper_cv:.2f} CV")
    if any_fail:
        print(f"FAIL: exceeds threshold {args.threshold} CV")
        return 1
    print(f"PASS: all within threshold {args.threshold} CV")
    return 0


if __name__ == "__main__":
    sys.exit(main())
