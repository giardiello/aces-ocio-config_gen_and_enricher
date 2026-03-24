#!/usr/bin/env python3
"""
Verify generated OCIO configs against source/reference configs.

For each shared display+view pair, bakes ACEScct → display+view through both
configs and compares the results across a grid of test values.

Usage:
    python verify_configs.py
"""

import sys
import re
import tempfile
import os
from pathlib import Path

import PyOpenColorIO as OCIO
import numpy as np


# ── helpers ──────────────────────────────────────────────────────────────────

def load_config_permissive(path: str):
    """Load an OCIO config, bumping version if needed for incompatible BuiltIns."""
    path = str(Path(path).resolve())
    try:
        return OCIO.Config.CreateFromFile(path)
    except OCIO.Exception:
        txt = open(path).read()
        txt = re.sub(r'^(ocio_profile_version:\s*)[\d.]+',
                     r'\g<1>2.5', txt, count=1, flags=re.MULTILINE)
        config_dir = str(Path(path).parent)
        fd, tmp = tempfile.mkstemp(suffix='.ocio', dir=config_dir)
        try:
            os.write(fd, txt.encode()); os.close(fd)
            return OCIO.Config.CreateFromFile(tmp)
        finally:
            os.unlink(tmp)


def get_display_views(cfg):
    """Return set of (display, view) tuples, excluding Raw/Un-tone-mapped/Video."""
    skip_views = {'Raw', 'Un-tone-mapped', 'Video (colorimetric)'}
    pairs = set()
    for d in cfg.getDisplays():
        for v in cfg.getViews(d):
            if v not in skip_views:
                pairs.add((d, v))
    return pairs


def make_test_grid():
    """ACEScct-range test grid: 65 evenly spaced values per channel, 3-channel combos."""
    vals_1d = np.linspace(0.0, 1.0, 65, dtype=np.float32)
    ramp = np.stack([vals_1d, vals_1d, vals_1d], axis=-1)

    grey_ramp = ramp.copy()

    r_only = np.zeros_like(ramp); r_only[:, 0] = vals_1d
    g_only = np.zeros_like(ramp); g_only[:, 1] = vals_1d
    b_only = np.zeros_like(ramp); b_only[:, 2] = vals_1d

    skin = np.array([[0.44, 0.32, 0.25]], dtype=np.float32)
    sky  = np.array([[0.30, 0.38, 0.52]], dtype=np.float32)
    red  = np.array([[0.62, 0.15, 0.10]], dtype=np.float32)
    green = np.array([[0.22, 0.50, 0.18]], dtype=np.float32)

    grid = np.concatenate([grey_ramp, r_only, g_only, b_only,
                           skin, sky, red, green], axis=0)
    return grid


def apply_display_view(cfg, display, view, pixels):
    """Apply ACEScct → display+view transform to pixel array."""
    try:
        proc = cfg.getProcessor('ACEScct', display, view,
                                OCIO.TRANSFORM_DIR_FORWARD)
    except OCIO.Exception:
        return None
    cpu = proc.getDefaultCPUProcessor()
    out = pixels.copy()
    cpu.applyRGB(out)
    return out


def compare_results(ref_pixels, test_pixels, label):
    """Compare two pixel arrays, return (max_abs_err, mean_abs_err, max_rel_err)."""
    diff = np.abs(ref_pixels.astype(np.float64) - test_pixels.astype(np.float64))
    max_abs = float(np.max(diff))
    mean_abs = float(np.mean(diff))

    denom = np.maximum(np.abs(ref_pixels.astype(np.float64)), 1e-6)
    rel = diff / denom
    max_rel = float(np.max(rel[np.abs(ref_pixels) > 0.001]))

    return max_abs, mean_abs, max_rel


# ── test runners ─────────────────────────────────────────────────────────────

def run_comparison(source_cfg, target_cfg, source_label, target_label,
                   restrict_views=None):
    """Compare all shared display+view pairs between source and target."""
    src_dv = get_display_views(source_cfg)
    tgt_dv = get_display_views(target_cfg)

    shared = sorted(src_dv & tgt_dv)
    if restrict_views:
        shared = [(d, v) for d, v in shared if any(r in v for r in restrict_views)]

    src_only = sorted(src_dv - tgt_dv)
    tgt_only = sorted(tgt_dv - src_dv)

    grid = make_test_grid()
    results = []

    for display, view in shared:
        ref_out = apply_display_view(source_cfg, display, view, grid)
        tgt_out = apply_display_view(target_cfg, display, view, grid)

        if ref_out is None:
            results.append((display, view, 'SKIP (source failed)', None, None, None))
            continue
        if tgt_out is None:
            results.append((display, view, 'FAIL (target failed)', None, None, None))
            continue

        max_abs, mean_abs, max_rel = compare_results(ref_out, tgt_out,
                                                      f"{display}/{view}")
        if max_abs < 1e-4:
            status = 'EXACT'
        elif max_abs < 1e-2:
            status = 'CLOSE'
        elif max_abs < 0.05:
            status = 'WARN'
        else:
            status = 'FAIL'

        results.append((display, view, status, max_abs, mean_abs, max_rel))

    return results, src_only, tgt_only


def print_results(results, src_only, tgt_only, source_label, target_label):
    """Pretty-print comparison results."""
    print(f"\n  {'Display':<30} {'View':<45} {'Status':<7} {'MaxAbs':>10} {'MeanAbs':>10} {'MaxRel':>10}")
    print(f"  {'─'*30} {'─'*45} {'─'*7} {'─'*10} {'─'*10} {'─'*10}")

    pass_count = 0
    for display, view, status, max_abs, mean_abs, max_rel in results:
        if max_abs is not None:
            print(f"  {display:<30} {view:<45} {status:<7} {max_abs:10.2e} {mean_abs:10.2e} {max_rel:10.2e}")
        else:
            print(f"  {display:<30} {view:<45} {status}")
        if status in ('EXACT', 'CLOSE'):
            pass_count += 1

    total = len(results)
    print(f"\n  Result: {pass_count}/{total} views match")

    if src_only:
        print(f"\n  Views only in source ({len(src_only)}):")
        for d, v in src_only[:5]:
            print(f"    {d} / {v}")
        if len(src_only) > 5:
            print(f"    ... and {len(src_only)-5} more")

    if tgt_only:
        print(f"\n  Views only in target ({len(tgt_only)}):")
        for d, v in tgt_only[:5]:
            print(f"    {d} / {v}")
        if len(tgt_only) > 5:
            print(f"    ... and {len(tgt_only)-5} more")

    return pass_count, total


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    base = Path(__file__).parent

    total_pass = 0
    total_tests = 0

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TEST 1: ACES 1.3 — source (v2.4 worktree) vs our OCIO 2.5 config
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 120)
    print("TEST 1: ACES 1.3 — Original source vs our OCIO 2.5 studio config")
    print("=" * 120)

    src_13 = base / "INPUT_OCIO/STUDIO/studio-config-v2.2.0_aces-v1.3_ocio-v2.4.ocio"
    tgt_13_v25 = base / "OUTPUT_CONFIGS/OCIO-v2.5/studio-config-v4.0.0_aces-v1.3_ocio-v2.5.ocio"

    if src_13.exists() and tgt_13_v25.exists():
        cfg_src = load_config_permissive(str(src_13))
        cfg_tgt = load_config_permissive(str(tgt_13_v25))
        results, src_only, tgt_only = run_comparison(
            cfg_src, cfg_tgt,
            "Original ACES 1.3 (v2.4)", "Our ACES 1.3 (v2.5)",
            restrict_views=['ACES 1.']
        )
        p, t = print_results(results, src_only, tgt_only,
                             "Original ACES 1.3", "Our ACES 1.3 v2.5")
        total_pass += p; total_tests += t
    else:
        print(f"  SKIP: source={src_13.exists()}, target={tgt_13_v25.exists()}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TEST 2: ACES 2.0 — built-in v2.5 vs our OCIO 2.3 CLF config
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 120)
    print("TEST 2: ACES 2.0 — Built-in v2.5 vs our OCIO 2.3 CLF studio config")
    print("=" * 120)

    tgt_20_v23 = base / "OUTPUT_CONFIGS/OCIO-v2.3/studio-config-v4.0.0_aces-v2.0_ocio-v2.3-clf/studio-config-v4.0.0_aces-v2.0_ocio-v2.3-clf.ocio"

    if tgt_20_v23.exists():
        cfg_src = OCIO.Config.CreateFromBuiltinConfig(
            "studio-config-v4.0.0_aces-v2.0_ocio-v2.5")
        cfg_tgt = load_config_permissive(str(tgt_20_v23))
        results, src_only, tgt_only = run_comparison(
            cfg_src, cfg_tgt,
            "Built-in ACES 2.0 (v2.5)", "Our ACES 2.0 (v2.3 CLF)",
            restrict_views=['ACES 2.']
        )
        p, t = print_results(results, src_only, tgt_only,
                             "Built-in ACES 2.0", "Our ACES 2.0 v2.3 CLF")
        total_pass += p; total_tests += t
    else:
        print(f"  SKIP: target not found")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TEST 3: ACES 2.0 — built-in v2.5 vs our OCIO 2.5 config
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 120)
    print("TEST 3: ACES 2.0 — Built-in v2.5 vs our OCIO 2.5 studio config")
    print("=" * 120)

    tgt_20_v25 = base / "OUTPUT_CONFIGS/OCIO-v2.5/studio-config-v4.0.0_aces-v2.0_ocio-v2.5.ocio"

    if tgt_20_v25.exists():
        cfg_src = OCIO.Config.CreateFromBuiltinConfig(
            "studio-config-v4.0.0_aces-v2.0_ocio-v2.5")
        cfg_tgt = load_config_permissive(str(tgt_20_v25))
        results, src_only, tgt_only = run_comparison(
            cfg_src, cfg_tgt,
            "Built-in ACES 2.0 (v2.5)", "Our ACES 2.0 (v2.5)",
            restrict_views=['ACES 2.']
        )
        p, t = print_results(results, src_only, tgt_only,
                             "Built-in ACES 2.0", "Our ACES 2.0 v2.5")
        total_pass += p; total_tests += t
    else:
        print(f"  SKIP: target not found")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TEST 4: Combined — ACES 1.3 views in combined v2.5 config
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 120)
    print("TEST 4: Combined v2.5 — ACES 1.3 views (vs original ACES 1.3 source)")
    print("=" * 120)

    tgt_combined_v25 = base / "OUTPUT_CONFIGS/OCIO-v2.5/studio-config-v4.0.0_aces-v1.3-v2.0_ocio-v2.5.ocio"

    if src_13.exists() and tgt_combined_v25.exists():
        cfg_src = load_config_permissive(str(src_13))
        cfg_tgt = load_config_permissive(str(tgt_combined_v25))
        results, src_only, tgt_only = run_comparison(
            cfg_src, cfg_tgt,
            "Original ACES 1.3", "Combined v2.5 (ACES 1.3 views)",
            restrict_views=['ACES 1.']
        )
        p, t = print_results(results, src_only, tgt_only,
                             "Original ACES 1.3", "Combined v2.5")
        total_pass += p; total_tests += t
    else:
        print(f"  SKIP")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TEST 5: Combined — ACES 2.0 views in combined v2.5 config
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 120)
    print("TEST 5: Combined v2.5 — ACES 2.0 views (vs built-in ACES 2.0)")
    print("=" * 120)

    if tgt_combined_v25.exists():
        cfg_src = OCIO.Config.CreateFromBuiltinConfig(
            "studio-config-v4.0.0_aces-v2.0_ocio-v2.5")
        cfg_tgt = load_config_permissive(str(tgt_combined_v25))
        results, src_only, tgt_only = run_comparison(
            cfg_src, cfg_tgt,
            "Built-in ACES 2.0", "Combined v2.5 (ACES 2.0 views)",
            restrict_views=['ACES 2.']
        )
        p, t = print_results(results, src_only, tgt_only,
                             "Built-in ACES 2.0", "Combined v2.5")
        total_pass += p; total_tests += t
    else:
        print(f"  SKIP")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TEST 6: Combined v2.3 — ACES 1.3 views
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 120)
    print("TEST 6: Combined v2.3 — ACES 1.3 views (vs original ACES 1.3 source)")
    print("=" * 120)

    tgt_combined_v23 = base / "OUTPUT_CONFIGS/OCIO-v2.3/studio-config-v2.2.0_aces-v1.3-v2.0_ocio-v2.3.ocio"

    if src_13.exists() and tgt_combined_v23.exists():
        cfg_src = load_config_permissive(str(src_13))
        cfg_tgt = load_config_permissive(str(tgt_combined_v23))
        results, src_only, tgt_only = run_comparison(
            cfg_src, cfg_tgt,
            "Original ACES 1.3", "Combined v2.3 (ACES 1.3 views)",
            restrict_views=['ACES 1.']
        )
        p, t = print_results(results, src_only, tgt_only,
                             "Original ACES 1.3", "Combined v2.3")
        total_pass += p; total_tests += t
    else:
        print(f"  SKIP")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # FINAL SUMMARY
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n" + "=" * 120)
    print("FINAL SUMMARY")
    print("=" * 120)
    print(f"\n  Total: {total_pass}/{total_tests} display+view pairs match across all tests")
    if total_pass == total_tests:
        print("  ALL TESTS PASSED")
    else:
        print(f"  {total_tests - total_pass} FAILURES — see details above")

    return 0 if total_pass == total_tests else 1


if __name__ == '__main__':
    sys.exit(main())
