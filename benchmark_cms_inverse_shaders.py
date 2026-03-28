#!/usr/bin/env python3
"""
CMS (ACEScct) -> forward display/view -> uint16 display quantize -> inverse -> ACEScct.

**Built-in forward:** ACEScct→ACES2065-1→Display+View (forward).
**Built-in inverse (reference):** inverse Display+View + ACES2065-1→ACEScct
(``ocio_builtins_display``).

Forward uses studio all-views v2.5 unless ``--paired``. LUT inverses are judged vs that reference.

--paired: same OCIO file for forward+inverse (CLF forward + CLF inverse) — not recommended
when you care about matching real built-in display renders.

Targets: sRGB SDR, PQ 1000/2000/4000 nits Rec.2020 and P3-D65 (Rec.2100-PQ display).

Usage:
  python benchmark_cms_inverse_shaders.py [--cms PATH] [--max-samples N] [--targets all]
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import PyOpenColorIO as ocio

from ocio_builtins_display import (
    group_forward_acescct_to_display_view,
    group_inverse_display_view_to_acescct,
)

try:
    import OpenImageIO as oiio
except ImportError:
    print("pip install OpenImageIO", file=sys.stderr)
    sys.exit(1)

BUILTIN_FWD = "INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio"

# (short_name, display, view)
DISPLAY_VIEWS: list[tuple[str, str, str]] = [
    ("sRGB_SDR", "sRGB - Display", "ACES 2.0 - SDR 100 nits (Rec.709)"),
    ("PQ1000_Rec2020", "Rec.2100-PQ - Display", "ACES 2.0 - HDR 1000 nits (Rec.2020)"),
    ("PQ2000_Rec2020", "Rec.2100-PQ - Display", "ACES 2.0 - HDR 2000 nits (Rec.2020)"),
    ("PQ4000_Rec2020", "Rec.2100-PQ - Display", "ACES 2.0 - HDR 4000 nits (Rec.2020)"),
    ("PQ1000_P3", "Rec.2100-PQ - Display", "ACES 2.0 - HDR 1000 nits (P3 D65)"),
    ("PQ2000_P3", "Rec.2100-PQ - Display", "ACES 2.0 - HDR 2000 nits (P3 D65)"),
    ("PQ4000_P3", "Rec.2100-PQ - Display", "ACES 2.0 - HDR 4000 nits (P3 D65)"),
]

_CLF_NAME = "studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.3-clf.ocio"

CONFIGS: list[tuple[str, str]] = [
    ("builtin inv (OCIO 2.5)", BUILTIN_FWD),
    ("display-shaper (default)", f"OUTPUT/benchmark_display_shaper/{_CLF_NAME}"),
    ("acescct-domain",          f"OUTPUT/benchmark_acescct_domain/{_CLF_NAME}"),
    ("acescct",                 f"OUTPUT/benchmark_acescct/{_CLF_NAME}"),
    ("acescc",                  f"OUTPUT/benchmark_acescc/{_CLF_NAME}"),
    ("extended-log",            f"OUTPUT/benchmark_extended_log/{_CLF_NAME}"),
    ("camera-log",              f"OUTPUT/benchmark_camera_log/{_CLF_NAME}"),
    ("jplog2",                  f"OUTPUT/benchmark_jplog2/{_CLF_NAME}"),
]

CHUNK = 65536


def load_cms(path: str) -> np.ndarray:
    inp = oiio.ImageInput.open(path)
    if inp is None:
        raise RuntimeError(oiio.geterror())
    pix = np.array(inp.read_image(format=oiio.FLOAT), dtype=np.float32)
    inp.close()
    if pix.ndim == 3:
        pix = pix.reshape(-1, pix.shape[-1])
    return pix[:, :3].copy()


def dpx16_quantize(display_rgb: np.ndarray) -> np.ndarray:
    d = np.clip(display_rgb, 0.0, 1.0)
    return (np.round(d * 65535.0).astype(np.float32) / 65535.0).astype(np.float32)


def load_cpu_for_group(repo: str, relpath: str, display: str, view: str, *, forward: bool) -> object:
    path = os.path.join(repo, relpath)
    cfg_dir = os.path.dirname(path)
    old = os.getcwd()
    os.chdir(cfg_dir)
    try:
        config = ocio.Config.CreateFromFile(os.path.basename(path))
        g = (
            group_forward_acescct_to_display_view(display, view)
            if forward
            else group_inverse_display_view_to_acescct(display, view)
        )
        return config.getProcessor(g).getDefaultCPUProcessor()
    finally:
        os.chdir(old)


def apply_chunked(cpu, arr: np.ndarray) -> None:
    n = len(arr)
    for i in range(0, n, CHUNK):
        sl = slice(i, min(i + CHUNK, n))
        buf = ocio.PackedImageDesc(arr[sl].ravel(), sl.stop - sl.start, 1, 3)
        cpu.apply(buf)


def run_one(
    base: str,
    fwd_relpath: str,
    inv_relpath: str,
    cms: np.ndarray,
    display: str,
    view: str,
) -> dict | str:
    try:
        cpu_fwd = load_cpu_for_group(base, fwd_relpath, display, view, forward=True)
        cpu_inv = load_cpu_for_group(base, inv_relpath, display, view, forward=False)
    except Exception as e:
        return str(e)

    disp = cms.copy()
    apply_chunked(cpu_fwd, disp)
    back = dpx16_quantize(disp).copy()
    apply_chunked(cpu_inv, back)

    err = np.abs(back - cms) * 100.0
    return {
        "mean_cv": float(np.mean(err)),
        "max_cv": float(np.max(err)),
        "p99_cv": float(np.percentile(err, 99)),
        "p95_cv": float(np.percentile(err, 95)),
        "median_cv": float(np.median(err)),
    }


def main() -> int:
    import csv as _csv

    base = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--cms", default=os.path.join(base, "test_assets", "CMS_32.exr"))
    ap.add_argument("--max-samples", type=int, default=80000, help="0 = all pixels (slow)")
    ap.add_argument(
        "--paired",
        action="store_true",
        help="Use CLF forward from each row (lower quality than built-in); default is built-in forward only",
    )
    ap.add_argument(
        "--targets",
        default="all",
        help="Comma-separated short names from DISPLAY_VIEWS, or 'all'",
    )
    ap.add_argument("--csv", default=None, help="Save results to CSV file")
    args = ap.parse_args()

    cms = load_cms(args.cms)
    if args.max_samples > 0 and len(cms) > args.max_samples:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(cms), size=args.max_samples, replace=False)
        cms = cms[idx]

    if args.targets.strip().lower() == "all":
        targets = DISPLAY_VIEWS
    else:
        want = {x.strip() for x in args.targets.split(",")}
        targets = [t for t in DISPLAY_VIEWS if t[0] in want]
        if not targets:
            print("No matching targets. Choices:", [t[0] for t in DISPLAY_VIEWS])
            return 1

    mode = "paired (same config fwd+inv)" if args.paired else "forward=BUILT-IN OCIO 2.5 only, inv=row config"
    print(f"CMS samples: {len(cms)} (ACEScct)")
    print(f"Mode: {mode}\n")

    csv_rows: list[list[str]] = []
    fwd_path = BUILTIN_FWD
    for tname, display, view in targets:
        print("=" * 72)
        print(f"Target: {tname}  |  {display} / {view}")
        print("-" * 72)
        rows = []
        for label, rel in CONFIGS:
            fpath = rel if args.paired else fwd_path
            r = run_one(base, fpath, rel, cms, display, view)
            if isinstance(r, str):
                print(f"  [FAIL] {label}: {r}")
                continue
            rows.append((label, r))
            print(
                f"  {label:32}  mean={r['mean_cv']:7.3f}  "
                f"med={r['median_cv']:6.2f}  p95={r['p95_cv']:6.2f}  "
                f"p99={r['p99_cv']:6.2f}  max={r['max_cv']:7.2f}"
            )
            csv_rows.append([
                label, tname,
                f"{r['mean_cv']:.3f}", f"{r['median_cv']:.3f}",
                f"{r['p95_cv']:.3f}", f"{r['p99_cv']:.3f}", f"{r['max_cv']:.3f}",
            ])
        if rows:
            best = min(rows, key=lambda x: x[1]["mean_cv"])
            print(f"  -> best mean CV: {best[0]} ({best[1]['mean_cv']:.3f})")
        print()

    if args.csv:
        os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
        with open(args.csv, "w", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["Config", "Target", "Mean CV", "Median CV", "P95 CV", "P99 CV", "Max CV"])
            w.writerows(csv_rows)
        print(f"Results saved to {args.csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
