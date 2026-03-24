#!/usr/bin/env python3
"""
Compare **built-in** inverse (inverse Display+View + ACES2065-1→ACEScct) vs **LUT / log-shader**
inverses on the same CMS path:

  ACEScct → [built-in forward v2.5] → display → uint16 quantize → [inverse] → ACEScct

Reports full-frame stats and **shadow** band (AP1 linear Y < 0.05 from original CMS).

Usage:
  python compare_builtin_vs_log_inverse.py [--cms PATH] [--display ...] [--view ...] [--max-samples N]
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import PyOpenColorIO as ocio

try:
    import OpenImageIO as oiio
except ImportError:
    print("pip install OpenImageIO", file=sys.stderr)
    sys.exit(1)

from ocio_builtins_display import (
    group_forward_acescct_to_display_view,
    group_inverse_display_view_to_acescct,
)

BASE = os.path.dirname(os.path.abspath(__file__))
BUILTIN_STUDIO = os.path.join(
    BASE, "INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio"
)

# (label, inverse_config_relpath) — forward always built-in v2.5
INVERSES = [
    ("Built-in (analytical VT)", BUILTIN_STUDIO),
    ("ACEScc inverse CLF", os.path.join(BASE, "OUTPUT/clf_v2/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio")),
    ("ACEScct shaper inverse CLF", os.path.join(BASE, "OUTPUT/acescct_inverse_test/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio")),
    ("Extended-log inverse CLF", os.path.join(BASE, "OUTPUT/extended_log_test/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio")),
    ("Camera-log inverse CLF", os.path.join(BASE, "OUTPUT/camera_log_test/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio")),
]

CHUNK = 65536


def load_cms(path: str, max_n: int, seed: int = 42) -> np.ndarray:
    inp = oiio.ImageInput.open(path)
    if inp is None:
        raise RuntimeError(oiio.geterror())
    p = np.array(inp.read_image(format=oiio.FLOAT), dtype=np.float32)
    inp.close()
    if p.ndim == 3:
        p = p.reshape(-1, p.shape[-1])
    p = p[:, :3].copy()
    if max_n > 0 and len(p) > max_n:
        rng = np.random.default_rng(seed)
        p = p[rng.choice(len(p), size=max_n, replace=False)]
    return p


def linear_y_ap1_ap1rgb(ap1: np.ndarray) -> np.ndarray:
    r, g, b = ap1[:, 0], ap1[:, 1], ap1[:, 2]
    return (0.2722287 * r + 0.6740818 * g + 0.0536895 * b).astype(np.float32)


def apply_chunked(cpu, arr: np.ndarray) -> None:
    n = len(arr)
    for i in range(0, n, CHUNK):
        sl = slice(i, min(i + CHUNK, n))
        cpu.apply(ocio.PackedImageDesc(arr[sl].ravel(), sl.stop - sl.start, 1, 3))


def dpx16_q(d: np.ndarray) -> np.ndarray:
    d = np.clip(d, 0.0, 1.0)
    return (np.round(d * 65535.0).astype(np.float32) / 65535.0).astype(np.float32)


def load_inv_cpu(cfg_path: str, display: str, view: str):
    cfg_path = os.path.abspath(cfg_path)
    d = os.path.dirname(cfg_path)
    old = os.getcwd()
    os.chdir(d)
    try:
        c = ocio.Config.CreateFromFile(os.path.basename(cfg_path))
        g = group_inverse_display_view_to_acescct(display, view)
        return c.getProcessor(g).getDefaultCPUProcessor()
    finally:
        os.chdir(old)


def load_fwd_cpu(cfg_path: str, display: str, view: str):
    cfg_path = os.path.abspath(cfg_path)
    d = os.path.dirname(cfg_path)
    old = os.getcwd()
    os.chdir(d)
    try:
        c = ocio.Config.CreateFromFile(os.path.basename(cfg_path))
        g = group_forward_acescct_to_display_view(display, view)
        return c.getProcessor(g).getDefaultCPUProcessor()
    finally:
        os.chdir(old)


def ap1_from_acescct(cms: np.ndarray, studio_path: str) -> np.ndarray:
    p = os.path.abspath(studio_path)
    old = os.getcwd()
    os.chdir(os.path.dirname(p))
    try:
        c = ocio.Config.CreateFromFile(os.path.basename(p))
        cpu = c.getProcessor("ACEScct", "ACEScg").getDefaultCPUProcessor()
    finally:
        os.chdir(old)
    out = cms.copy()
    apply_chunked(cpu, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cms", default=os.path.join(BASE, "test_assets", "CMS_32.exr"))
    ap.add_argument("--max-samples", type=int, default=25000)
    ap.add_argument("--display", default="sRGB - Display")
    ap.add_argument("--view", default="ACES 2.0 - SDR 100 nits (Rec.709)")
    args = ap.parse_args()

    if not os.path.isfile(BUILTIN_STUDIO):
        print(f"Missing built-in studio: {BUILTIN_STUDIO}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.cms):
        print(f"Missing CMS: {args.cms}", file=sys.stderr)
        return 1

    cms = load_cms(args.cms, args.max_samples)
    ap1 = ap1_from_acescct(cms, BUILTIN_STUDIO)
    y = linear_y_ap1_ap1rgb(ap1)
    shadow = y < 0.05

    print("Built-in vs log-shader inverse (after uint16 display quantize)")
    print(f"  Forward: always {os.path.basename(BUILTIN_STUDIO)}")
    print(f"  Display: {args.display} / {args.view}")
    print(f"  CMS samples: {len(cms)}  |  shadow band: AP1 Y < 0.05 ({int(np.sum(shadow))} px)\n")

    cpu_fwd = load_fwd_cpu(BUILTIN_STUDIO, args.display, args.view)

    hdr = f"{'Inverse pipeline':<34} {'mean CV*':>10} {'med max':>8} {'p99 mx':>8} {'max':>8} | {'shadow CV*':>12}"
    print(hdr)
    print("-" * len(hdr))

    for label, inv_cfg in INVERSES:
        if not os.path.isfile(inv_cfg):
            print(f"{label:<34}  (config missing: {inv_cfg})")
            continue
        cpu_inv = load_inv_cpu(inv_cfg, args.display, args.view)
        disp = cms.copy()
        apply_chunked(cpu_fwd, disp)
        back = dpx16_q(disp).copy()
        apply_chunked(cpu_inv, back)
        err = np.abs(back - cms) * 100.0
        per = np.max(err, axis=1)
        # Match benchmark_cms_inverse_shaders: mean_cv = mean over all channel samples
        mean_all = float(np.mean(err))
        sh_mean = float(np.mean(err[shadow])) if np.any(shadow) else float("nan")
        print(
            f"{label:<34} {mean_all:10.2f} {np.median(per):8.2f} "
            f"{np.percentile(per, 99):8.2f} {np.max(per):8.2f} | {sh_mean:12.2f}"
        )

    print()
    print(
        "*mean CV / shadow CV = mean of |Δ|×100 over all RGB samples (same as benchmark_cms_inverse_shaders). "
        "med/p99/max = per-pixel max channel. Built-in = analytical VT inv + ACEScct; "
        "CLF = LUT inverse + log decode."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
