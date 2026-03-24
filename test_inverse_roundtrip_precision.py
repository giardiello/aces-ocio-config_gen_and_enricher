#!/usr/bin/env python3
"""
Roundtrip precision test for inverse CLFs (ACES -> forward VT -> inverse VT -> ACES).

Reports max error (in CV, 100 * abs diff) per scene-linear band. Bands extend to 222
(scene linear) to cover the full ACEScct range.

Usage:
    python test_inverse_roundtrip_precision.py [path_to_config.ocio] [path_to_luts_dir]
    Defaults: OUTPUT/clf_v2/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio, OUTPUT/clf_v2/luts
"""

import os
import sys

try:
    import numpy as np
    import PyOpenColorIO as ocio
except ImportError as e:
    print("Error: need numpy and PyOpenColorIO.", e)
    sys.exit(1)

# Bands (scene-linear gray level ranges) and sample count per band.
# Extended to ~222 to cover full ACEScct range (scene linear up to ~222).
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


def run_roundtrip(config_path, luts_dir, vt_name="ACES 2.0 - SDR 100 nits (Rec.709)"):
    config_path = os.path.abspath(config_path)
    luts_dir = os.path.abspath(luts_dir)
    if not os.path.isfile(config_path):
        print(f"Config not found: {config_path}")
        return False
    os.chdir(os.path.dirname(config_path))
    config = ocio.Config.CreateFromFile(config_path)

    vt = config.getViewTransform(vt_name)
    if vt is None:
        print(f"ViewTransform not found: {vt_name}")
        return False

    from_ref = vt.getTransform(ocio.VIEWTRANSFORM_DIR_FROM_REFERENCE)
    to_ref = vt.getTransform(ocio.VIEWTRANSFORM_DIR_TO_REFERENCE)
    proc_fwd = config.getProcessor(from_ref)
    proc_inv = config.getProcessor(to_ref)

    cpu_fwd = proc_fwd.getDefaultCPUProcessor()
    cpu_inv = proc_inv.getDefaultCPUProcessor()

    band_errors = []
    for name, lo, hi, n in BANDS:
        # Gray samples in [lo, hi]
        if n <= 1:
            vals = np.array([lo if lo == hi else (lo + hi) / 2.0], dtype=np.float32)
        else:
            vals = np.linspace(lo, hi, n, dtype=np.float32)
        pixels = np.stack([vals, vals, vals], axis=1)  # (n, 3)
        orig = pixels.copy()

        buf = ocio.PackedImageDesc(pixels.ravel(), len(pixels), 1, 3)
        cpu_fwd.apply(buf)
        cpu_inv.apply(buf)

        err = np.abs(pixels.ravel().reshape(-1, 3) - orig)
        max_err_linear = float(np.max(err))
        cv_error = max_err_linear * 100.0
        band_errors.append((name, cv_error, max_err_linear))

    return band_errors


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base, "OUTPUT", "clf_v2", "studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio")
    luts_dir = os.path.join(base, "OUTPUT", "clf_v2", "luts")
    if len(sys.argv) >= 2:
        config_path = sys.argv[1]
    if len(sys.argv) >= 3:
        luts_dir = sys.argv[2]

    print("Inverse CLF roundtrip precision (ACES -> forward -> inverse -> ACES)")
    print(f"Config: {config_path}")
    print(f"VT: ACES 2.0 - SDR 100 nits (Rec.709)")
    print()

    result = run_roundtrip(config_path, luts_dir)
    if result is False:
        sys.exit(1)

    print(f"{'Band':<28} {'Max error (CV)':>14} {'Max diff (linear)':>18}")
    print("-" * 62)
    for name, cv_err, lin_err in result:
        print(f"{name:<28} {cv_err:>14.2f} {lin_err:>18.6f}")
    print()

    upper_cv = next(cv for (n, cv, _) in result if "Upper (0.1-0.5)" in n)
    threshold_cv = 1.0  # no shaper/highlight compression; expect ~0.15 CV
    if upper_cv > threshold_cv:
        print(f"FAIL: Upper (0.1-0.5) error {upper_cv:.2f} CV > {threshold_cv}")
        sys.exit(1)
    print(f"PASS: Upper (0.1-0.5) error {upper_cv:.2f} CV <= {threshold_cv}")
    sys.exit(0)


if __name__ == "__main__":
    main()
