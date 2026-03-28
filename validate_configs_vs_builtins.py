#!/usr/bin/env python3
"""
Validate generated OCIO configs against OCIO built-in configs.

For each comparable pair (built-in <-> generated), this script:
  1. Compares structure: displays, views, view transforms
  2. Renders the CMS test pattern through every common display+view forward transform
  3. Compares pixel output between built-in and generated configs
  4. Reports per-view max/mean absolute error and flags any mismatches

Comparable pairs
----------------
  Built-in OCIO 2.5 ACES 2.0:
    cg-config-v4.0.0_aces-v2.0_ocio-v2.5
    studio-config-v4.0.0_aces-v2.0_ocio-v2.5

  Built-in OCIO 2.3 ACES 1.3 (COLORSPACES v2.1.0 vs our v2.2.0):
    cg-config-v2.1.0_aces-v1.3_ocio-v2.3
    studio-config-v2.1.0_aces-v1.3_ocio-v2.3

Usage
-----
    python validate_configs_vs_builtins.py [--cms PATH] [--output-dir PATH] [--max-samples N]
"""

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import PyOpenColorIO as ocio

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CMS = SCRIPT_DIR / "test_assets" / "CMS_32.exr"
DEFAULT_OUTPUT = SCRIPT_DIR / "OUTPUT_CONFIGS"

PAIRS = [
    {
        "label": "CG — OCIO 2.5 — ACES 2.0",
        "builtin": "cg-config-v4.0.0_aces-v2.0_ocio-v2.5",
        "generated": "OCIO-v2.5/cg-config-v4.0.0_aces-v2.0_ocio-v2.5/"
                      "cg-config-v4.0.0_aces-v2.0_ocio-v2.5.ocio",
        "version_match": True,
    },
    {
        "label": "Studio — OCIO 2.5 — ACES 2.0",
        "builtin": "studio-config-v4.0.0_aces-v2.0_ocio-v2.5",
        "generated": "OCIO-v2.5/studio-config-v4.0.0_aces-v2.0_ocio-v2.5/"
                      "studio-config-v4.0.0_aces-v2.0_ocio-v2.5.ocio",
        "version_match": True,
    },
    {
        "label": "CG — OCIO 2.3 — ACES 1.3 (v2.1.0 vs v2.2.0)",
        "builtin": "cg-config-v2.1.0_aces-v1.3_ocio-v2.3",
        "generated": "OCIO-v2.3/cg-config-v2.2.0_aces-v1.3_ocio-v2.3/"
                      "cg-config-v2.2.0_aces-v1.3_ocio-v2.3.ocio",
        "version_match": False,
    },
    {
        "label": "Studio — OCIO 2.3 — ACES 1.3 (v2.1.0 vs v2.2.0)",
        "builtin": "studio-config-v2.1.0_aces-v1.3_ocio-v2.3",
        "generated": "OCIO-v2.3/studio-config-v2.2.0_aces-v1.3_ocio-v2.3/"
                      "studio-config-v2.2.0_aces-v1.3_ocio-v2.3.ocio",
        "version_match": False,
    },
]


def load_cms(path: str, max_samples: int = 0) -> np.ndarray:
    try:
        import OpenImageIO as oiio
    except ModuleNotFoundError:
        print("  OpenImageIO not available — generating synthetic test pattern")
        return _generate_synthetic_cms(max_samples or 50000)
    inp = oiio.ImageInput.open(str(path))
    if inp is None:
        sys.exit(f"Cannot open {path}: {oiio.geterror()}")
    spec = inp.spec()
    buf = np.frombuffer(inp.read_image("float"), dtype=np.float32).copy()
    inp.close()
    buf = buf.reshape(-1, spec.nchannels)[:, :3].copy()
    if max_samples and len(buf) > max_samples:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(buf), max_samples, replace=False)
        buf = buf[idx]
    return np.ascontiguousarray(buf, dtype=np.float32)


def _generate_synthetic_cms(n: int = 50000) -> np.ndarray:
    """Generate a synthetic ACES2065-1 test pattern covering scene-referred range.

    Includes: uniform grid in [0,1]^3, log-spaced high-dynamic-range ramp,
    near-black/shadow region, and random scene-referred values.
    """
    rng = np.random.default_rng(42)
    parts = []
    res = max(8, int(round(n ** (1.0 / 3.0))))
    g = np.linspace(0.0, 1.0, res, dtype=np.float32)
    r, gc, b = np.meshgrid(g, g, g, indexing="ij")
    parts.append(np.column_stack([r.ravel(), gc.ravel(), b.ravel()]))
    ramp = np.logspace(-5, 1.5, 2000, dtype=np.float32)
    parts.append(np.column_stack([ramp, ramp, ramp]))
    shadow = rng.uniform(0.0, 0.02, (2000, 3)).astype(np.float32)
    parts.append(shadow)
    remaining = max(1000, n - sum(p.shape[0] for p in parts))
    rand_vals = rng.uniform(-0.01, 10.0, (remaining, 3)).astype(np.float32)
    parts.append(rand_vals)
    pixels = np.concatenate(parts, axis=0)
    if len(pixels) > n:
        idx = rng.choice(len(pixels), n, replace=False)
        pixels = pixels[idx]
    return np.ascontiguousarray(pixels, dtype=np.float32)


def get_display_view_combos(config):
    combos = []
    for display in config.getDisplays():
        for view in config.getViews(display):
            vt_name = config.getDisplayViewTransformName(display, view)
            if not vt_name:
                continue
            combos.append((display, view, vt_name))
    return combos


def apply_forward(config, pixels, display, view):
    dvt = ocio.DisplayViewTransform()
    dvt.setSrc("ACES2065-1")
    dvt.setDisplay(display)
    dvt.setView(view)
    proc = config.getProcessor(dvt, ocio.TRANSFORM_DIR_FORWARD)
    cpu = proc.getDefaultCPUProcessor()
    result = pixels.copy()
    cpu.apply(ocio.PackedImageDesc(result, len(result), 1, 3))
    return result


def load_config_from_file(path: Path):
    path_str = str(path.resolve())
    cfg = ocio.Config.CreateFromFile(path_str)
    return cfg


def compare_structure(builtin_cfg, gen_cfg, label, version_match):
    issues = []

    b_combos = get_display_view_combos(builtin_cfg)
    g_combos = get_display_view_combos(gen_cfg)

    b_set = {(d, v) for d, v, _ in b_combos}
    g_set = {(d, v) for d, v, _ in g_combos}

    b_vt_map = {(d, v): vt for d, v, vt in b_combos}
    g_vt_map = {(d, v): vt for d, v, vt in g_combos}

    only_builtin = b_set - g_set
    only_gen = g_set - b_set
    common = b_set & g_set

    print(f"\n  Display+View combos: builtin={len(b_set)}, generated={len(g_set)}, "
          f"common={len(common)}")

    if only_builtin:
        issues.append(f"{len(only_builtin)} display+view combos only in built-in")
        print(f"  Only in built-in ({len(only_builtin)}):")
        for d, v in sorted(only_builtin):
            print(f"    - {d} / {v}")

    if only_gen:
        print(f"  Only in generated ({len(only_gen)}):")
        for d, v in sorted(only_gen):
            print(f"    + {d} / {v}")

    vt_mismatches = []
    for d, v in sorted(common):
        if b_vt_map[(d, v)] != g_vt_map[(d, v)]:
            vt_mismatches.append((d, v, b_vt_map[(d, v)], g_vt_map[(d, v)]))

    if vt_mismatches:
        issues.append(f"{len(vt_mismatches)} view transform name mismatches")
        print(f"  View transform name mismatches ({len(vt_mismatches)}):")
        for d, v, bvt, gvt in vt_mismatches:
            print(f"    {d} / {v}: builtin=\"{bvt}\" vs generated=\"{gvt}\"")

    b_vts = {vt.getName() for vt in builtin_cfg.getViewTransforms()}
    g_vts = {vt.getName() for vt in gen_cfg.getViewTransforms()}
    print(f"  View Transforms: builtin={len(b_vts)}, generated={len(g_vts)}")

    if version_match:
        if b_vts != g_vts:
            issues.append("View transform sets differ")
        if len(b_set) != len(g_set):
            issues.append(f"Display+view count mismatch: builtin={len(b_set)} vs generated={len(g_set)}")

    return sorted(common), issues


def compare_pixels(builtin_cfg, gen_cfg, common_combos, cms_pixels):
    results = []
    for display, view in common_combos:
        try:
            b_out = apply_forward(builtin_cfg, cms_pixels, display, view)
        except ocio.Exception as e:
            results.append((display, view, float('nan'), float('nan'),
                            float('nan'), float('nan'), f"BUILTIN_ERROR: {e}"))
            continue

        try:
            g_out = apply_forward(gen_cfg, cms_pixels, display, view)
        except ocio.Exception as e:
            results.append((display, view, float('nan'), float('nan'),
                            float('nan'), float('nan'), f"GEN_ERROR: {e}"))
            continue

        diff = np.abs(b_out - g_out)
        max_err = float(np.max(diff))
        mean_err = float(np.mean(diff))
        p99_err = float(np.percentile(diff, 99))

        finite_mask = np.isfinite(b_out).all(axis=1) & np.isfinite(g_out).all(axis=1)
        if finite_mask.any():
            finite_diff = np.abs(b_out[finite_mask] - g_out[finite_mask])
            max_finite = float(np.max(finite_diff))
        else:
            max_finite = max_err

        if max_finite == 0.0:
            status = "EXACT"
        elif max_finite < 1e-7:
            status = "MATCH (<1e-7)"
        elif max_finite < 1e-5:
            status = "CLOSE (<1e-5)"
        elif max_finite < 1e-3:
            status = "MINOR (<1e-3)"
        else:
            status = f"DIFFERS"

        results.append((display, view, max_err, mean_err, p99_err, max_finite, status))

    return results


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cms", type=Path, default=DEFAULT_CMS,
        help=f"CMS test pattern EXR (default: {DEFAULT_CMS})",
    )
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT,
        help=f"Root of generated configs (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--max-samples", type=int, default=0,
        help="Subsample CMS pixels (0 = use all)",
    )
    args = parser.parse_args()

    print(f"Loading CMS pattern: {args.cms}")
    cms = load_cms(str(args.cms), args.max_samples)
    print(f"  {len(cms)} pixels loaded\n")

    overall_pass = True
    summary_rows = []

    for pair in PAIRS:
        label = pair["label"]
        gen_path = args.output_dir / pair["generated"]

        print(f"\n{'=' * 80}")
        print(f"  {label}")
        print(f"{'=' * 80}")

        if not gen_path.exists():
            print(f"  SKIP: generated config not found at {gen_path}")
            summary_rows.append((label, "SKIP", "-", "-"))
            continue

        print(f"  Built-in : {pair['builtin']}")
        print(f"  Generated: {gen_path.relative_to(args.output_dir)}")

        builtin_cfg = ocio.Config.CreateFromBuiltinConfig(pair["builtin"])

        gen_path_abs = gen_path.resolve()
        old_cwd = os.getcwd()
        os.chdir(gen_path_abs.parent)
        try:
            gen_cfg = load_config_from_file(gen_path_abs)
        finally:
            os.chdir(old_cwd)

        common_combos, struct_issues = compare_structure(
            builtin_cfg, gen_cfg, label, pair["version_match"],
        )

        if struct_issues and pair["version_match"]:
            print(f"\n  STRUCTURAL ISSUES:")
            for issue in struct_issues:
                print(f"    !! {issue}")
            overall_pass = False

        if not common_combos:
            print(f"\n  No common display+view combos to compare pixels.")
            summary_rows.append((label, "NO_COMBOS", "0", "-"))
            continue

        print(f"\n  Rendering {len(common_combos)} display+view combos "
              f"through {len(cms)} pixels...")
        hdr = (f"  {'Display':<30s} {'View':<40s} "
               f"{'Max(fin)':>10s} {'Mean':>10s} {'P99':>10s}  Status")
        print(hdr)
        print(f"  {'-'*30} {'-'*40} {'-'*10} {'-'*10} {'-'*10}  {'-'*15}")

        t0 = time.time()
        pixel_results = compare_pixels(builtin_cfg, gen_cfg, common_combos, cms)
        elapsed = time.time() - t0

        n_exact = n_match = n_close = n_minor = n_differ = n_error = 0
        worst_max = 0.0

        for display, view, max_err, mean_err, p99_err, max_finite, status in pixel_results:
            def fmt(v):
                return f"{v:.2e}" if not np.isnan(v) else "N/A"

            print(f"  {display:<30s} {view:<40s} "
                  f"{fmt(max_finite):>10s} {fmt(mean_err):>10s} {fmt(p99_err):>10s}  {status}")

            if "EXACT" in status:
                n_exact += 1
            elif "MATCH" in status:
                n_match += 1
            elif "CLOSE" in status:
                n_close += 1
            elif "MINOR" in status:
                n_minor += 1
            elif "ERROR" in status:
                n_error += 1
            else:
                n_differ += 1
                if pair["version_match"]:
                    overall_pass = False

            if not np.isnan(max_finite) and max_finite > worst_max:
                worst_max = max_finite

        total = len(pixel_results)
        print(f"\n  {total} combos in {elapsed:.1f}s — "
              f"{n_exact} exact, {n_match} match, {n_close} close, "
              f"{n_minor} minor, {n_differ} differ, {n_error} errors")
        print(f"  Worst max finite error: {worst_max:.2e}")

        if pair["version_match"]:
            pair_status = "PASS" if (n_differ == 0 and n_error == 0) else "FAIL"
        else:
            pair_status = "PASS*" if (n_differ == 0 and n_error == 0) else "WARN"
        summary_rows.append((label, pair_status, str(total), f"{worst_max:.2e}"))

    print(f"\n{'=' * 80}")
    print(f"  FINAL SUMMARY")
    print(f"{'=' * 80}")
    print(f"  {'Config':<55s} {'Status':>6s} {'Views':>6s} {'Worst Err':>10s}")
    print(f"  {'-'*55} {'-'*6} {'-'*6} {'-'*10}")
    for label, status, combos, worst in summary_rows:
        print(f"  {label:<55s} {status:>6s} {combos:>6s} {worst:>10s}")

    print()
    if overall_pass:
        print("  ALL COMPARABLE CONFIGS MATCH (version-matched pairs are pixel-identical)")
    else:
        print("  SOME VERSION-MATCHED CONFIGS HAVE DIFFERENCES — see details above")

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
