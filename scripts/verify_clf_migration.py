#!/usr/bin/env python3
"""Compare old (pre-CLF) vs new (CLF-based) vendor family transform chains.

Loads each display color space from both the old and new family snippets,
creates OCIO processors, and compares their output on test patches.

Usage:
    python scripts/verify_clf_migration.py [--family arri|davinci|filmlight|red_ipp2|sony]
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

try:
    import PyOpenColorIO as OCIO
except ImportError:
    print("ERROR: PyOpenColorIO required. pip install opencolorio", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FAMILIES_DIR = os.path.join(SCRIPT_DIR, "..", "ocio_vendor_extensions", "families")
BACKUP_DIR = os.path.join(SCRIPT_DIR, "..", "ocio_vendor_extensions", "families_pre_clf")

DISPLAY_FAMILY_PREFIXES = {
    "arri": "ARRI/display_referred",
    "davinci": "DaVinci/display_referred",
    "filmlight": "FilmLight/display_referred",
    "red_ipp2": "RED-IPP2/display_referred",
    "sony": "SONY/display_referred",
}

TEST_PATCHES_ACES = np.array(
    [
        [0.1150, 0.1000, 0.0500],
        [0.3900, 0.3500, 0.2400],
        [0.1800, 0.1800, 0.3100],
        [0.1000, 0.1500, 0.0500],
        [0.2700, 0.2400, 0.4200],
        [0.2700, 0.5800, 0.4000],
        [0.5600, 0.2900, 0.0200],
        [0.1100, 0.1000, 0.3800],
        [0.4300, 0.1200, 0.0600],
        [0.0600, 0.0300, 0.1000],
        [0.3400, 0.4400, 0.0200],
        [0.5800, 0.4500, 0.0200],
        [0.0500, 0.0400, 0.3100],
        [0.1400, 0.2700, 0.0600],
        [0.3200, 0.0500, 0.0200],
        [0.6600, 0.5900, 0.0100],
        [0.3700, 0.1100, 0.2800],
        [0.0800, 0.2400, 0.3900],
        [0.9000, 0.8600, 0.7600],
        [0.5900, 0.5700, 0.5100],
        [0.3600, 0.3500, 0.3200],
        [0.2000, 0.1900, 0.1900],
        [0.0900, 0.0900, 0.0800],
        [0.0300, 0.0300, 0.0300],
    ],
    dtype=np.float32,
)


def load_config(path: str) -> OCIO.Config:
    """Load an OCIO config from file, working around search_path by chdir."""
    config_dir = os.path.dirname(os.path.abspath(path))
    luts_dir = os.path.join(config_dir, "luts")
    config = OCIO.Config.CreateFromFile(path)
    if os.path.isdir(luts_dir):
        config.setSearchPath(luts_dir)
    return config


def get_display_colorspaces(config: OCIO.Config, family_prefix: str) -> list[str]:
    names = []
    for cs in config.getColorSpaces():
        if cs.getFamily().startswith(family_prefix):
            names.append(cs.getName())
    return names


def compare_processors(
    old_config: OCIO.Config,
    new_config: OCIO.Config,
    cs_name: str,
    reference_cs: str = "ACES2065-1",
) -> tuple[float | None, str | None]:
    try:
        old_cpu = old_config.getProcessor(reference_cs, cs_name).getDefaultCPUProcessor()
    except Exception as e:
        return None, f"OLD config error: {e}"

    try:
        new_cpu = new_config.getProcessor(reference_cs, cs_name).getDefaultCPUProcessor()
    except Exception as e:
        return None, f"NEW config error: {e}"

    max_err = 0.0
    for patch in TEST_PATCHES_ACES:
        old_result = old_cpu.applyRGB(list(patch))
        new_result = new_cpu.applyRGB(list(patch))
        err = max(abs(old_result[i] - new_result[i]) for i in range(3))
        max_err = max(max_err, err)

    return max_err, None


def verify_filmlight_analytical() -> bool:
    """Verify the new analytical T-Log intermediate round-trips correctly.

    The old intermediate used a vendor-provided 1D LUT for T-Log decode,
    so a direct comparison would show ~0.7 error. Instead, we verify that
    the new analytical transform (LogCameraTransform + MatrixTransform)
    round-trips accurately: ACES → T-Log E-Gamut 2 → ACES should be identity.
    """
    new_path = os.path.join(FAMILIES_DIR, "filmlight", "colorspaces.ocio")
    if not os.path.exists(new_path):
        print("  SKIP: No new FilmLight config found")
        return True

    new_config = load_config(new_path)
    cs_name = "FilmLight : T-Log : E-Gamut 2"
    ref_cs = "ACES2065-1"

    try:
        fwd_cpu = new_config.getProcessor(ref_cs, cs_name).getDefaultCPUProcessor()
        inv_cpu = new_config.getProcessor(cs_name, ref_cs).getDefaultCPUProcessor()
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

    max_err = 0.0
    for patch in TEST_PATCHES_ACES:
        encoded = fwd_cpu.applyRGB(list(patch))
        decoded = inv_cpu.applyRGB(list(encoded))
        err = max(abs(float(patch[i]) - decoded[i]) for i in range(3))
        max_err = max(max_err, err)

    tolerance = 1e-5
    if max_err < tolerance:
        print(f"  PASS  T-Log analytical round-trip: max error = {max_err:.2e} (< {tolerance})")
        return True
    else:
        print(f"  FAIL  T-Log analytical round-trip: max error = {max_err:.2e} (>= {tolerance})")
        return False


def verify_family(family_name: str) -> bool:
    old_path = os.path.join(BACKUP_DIR, family_name, "colorspaces.ocio")
    new_path = os.path.join(FAMILIES_DIR, family_name, "colorspaces.ocio")

    if not os.path.exists(old_path):
        print(f"  SKIP: No backup found at {old_path}")
        return True

    if not os.path.exists(new_path):
        print(f"  SKIP: No new config found at {new_path}")
        return True

    old_config = load_config(old_path)
    new_config = load_config(new_path)

    prefix = DISPLAY_FAMILY_PREFIXES.get(family_name, "")
    display_cs = get_display_colorspaces(new_config, prefix)
    if not display_cs:
        print(f"  WARN: No display color spaces found in {family_name}")
        return True

    tolerance = 0.002 if family_name == "filmlight" else 0.001
    all_pass = True
    for cs_name in display_cs:
        max_err, error = compare_processors(old_config, new_config, cs_name)
        if error:
            print(f"  ERROR {cs_name}: {error}")
            all_pass = False
        elif max_err is not None and max_err > tolerance:
            print(f"  FAIL  {cs_name}: max error = {max_err:.6f} (tol={tolerance})")
            all_pass = False
        elif max_err is not None:
            print(f"  PASS  {cs_name}: max error = {max_err:.2e}")

    if family_name == "filmlight":
        print("\n  --- FilmLight Analytical Intermediate ---")
        if not verify_filmlight_analytical():
            all_pass = False

    return all_pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify CLF migration accuracy")
    parser.add_argument(
        "--family",
        choices=["arri", "davinci", "filmlight", "red_ipp2", "sony"],
        help="Verify a single family (default: all)",
    )
    args = parser.parse_args()

    families = [args.family] if args.family else ["arri", "davinci", "filmlight", "red_ipp2", "sony"]

    all_pass = True
    for family in families:
        print(f"\n=== {family.upper()} ===")
        if not verify_family(family):
            all_pass = False

    print(f"\n{'ALL PASSED' if all_pass else 'SOME FAILURES'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
