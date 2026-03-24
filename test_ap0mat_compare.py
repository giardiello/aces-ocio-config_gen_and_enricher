#!/usr/bin/env python3
"""
Compare inverse accuracy of 3 AP0-matrix-extracted configs against built-in.

Configs tested:
  1. ACEScct classic 97³  (no gamma shaper, AP0 matrix extracted)
  2. ACEScct + shaper 97³ (gamma-2 shaper, AP0 matrix extracted)
  3. ACEScct + shaper 120³ (gamma-2 shaper, AP0 matrix extracted)

Pipeline: ACEScct -> built-in v2.5 forward -> DPX16 quantize -> inverse -> ACEScct vs CMS.

Usage:
  python test_ap0mat_compare.py [--cms PATH] [--max-samples N]
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

CONFIGS = [
    ("Built-in (analytical)", BUILTIN_STUDIO),
    # --- Previous (no AP0 matrix extraction) ---
    (
        "[OLD] ACEScct classic 97³",
        os.path.join(BASE, "OUTPUT/acescct_range_65_97/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
    ),
    (
        "[OLD] ACEScct γ2 shaper 97³",
        os.path.join(BASE, "OUTPUT/acescct_range_65_97_shaper/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
    ),
    (
        "[OLD] ACEScct γ2 shaper 129³",
        os.path.join(BASE, "OUTPUT/acescct_g2_65_129/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
    ),
    # --- New (with AP0 matrix extraction) ---
    (
        "[NEW] ACEScct classic 97³ + AP0 mat",
        os.path.join(BASE, "OUTPUT/acescct_ap0mat_classic_97/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
    ),
    (
        "[NEW] ACEScct γ2 shaper 97³ + AP0 mat",
        os.path.join(BASE, "OUTPUT/acescct_ap0mat_shaper_97/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
    ),
    (
        "[NEW] ACEScct γ2 shaper 120³ + AP0 mat",
        os.path.join(BASE, "OUTPUT/acescct_ap0mat_shaper_120/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
    ),
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


def linear_y_ap1(ap1: np.ndarray) -> np.ndarray:
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


def load_cpu(cfg_path: str, display: str, view: str, forward: bool):
    cfg_path = os.path.abspath(cfg_path)
    d = os.path.dirname(cfg_path)
    old = os.getcwd()
    os.chdir(d)
    try:
        c = ocio.Config.CreateFromFile(os.path.basename(cfg_path))
        g = (
            group_forward_acescct_to_display_view(display, view)
            if forward
            else group_inverse_display_view_to_acescct(display, view)
        )
        return c.getProcessor(g).getDefaultCPUProcessor()
    finally:
        os.chdir(old)


def ap1_from_cms(cms: np.ndarray) -> np.ndarray:
    p = os.path.abspath(BUILTIN_STUDIO)
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
    ap.add_argument("--max-samples", type=int, default=50000)
    ap.add_argument("--display", default="sRGB - Display")
    ap.add_argument("--view", default="ACES 2.0 - SDR 100 nits (Rec.709)")
    args = ap.parse_args()

    if not os.path.isfile(BUILTIN_STUDIO) or not os.path.isfile(args.cms):
        print("Missing built-in studio config or CMS test image", file=sys.stderr)
        return 1

    cms = load_cms(args.cms, args.max_samples)
    ap1 = ap1_from_cms(cms)
    y = linear_y_ap1(ap1)
    shadow = y < 0.05
    highlight = y >= 2.0

    print()
    print("AP0 matrix extraction comparison (forward = built-in v2.5, DPX16, SDR Rec.709)")
    print(f"  All inverse CLFs use XYZ->AP0 analytical matrix extraction")
    print(f"  Samples: {len(cms)} | shadow Y<0.05: {int(np.sum(shadow))} | highlight Y≥2: {int(np.sum(highlight))}")
    print()

    hdr = (
        f"{'Config':<40} {'mean CV':>9} {'shadow':>9} {'highlight':>10} "
        f"{'p99 mx':>8} {'max':>8} {'R-G':>7} {'G-B':>7}"
    )
    print(hdr)
    print("-" * len(hdr))

    cpu_fwd = load_cpu(BUILTIN_STUDIO, args.display, args.view, forward=True)

    for label, cfg in CONFIGS:
        if not os.path.isfile(cfg):
            print(f"{label:<40}  (missing)")
            continue
        cpu_inv = load_cpu(cfg, args.display, args.view, forward=False)
        disp = cms.copy()
        apply_chunked(cpu_fwd, disp)
        back = dpx16_q(disp).copy()
        apply_chunked(cpu_inv, back)
        err = np.abs(back - cms) * 100.0
        per = np.max(err, axis=1)
        mean_all = float(np.mean(err))
        sh = float(np.mean(err[shadow])) if np.any(shadow) else float("nan")
        hi = float(np.mean(err[highlight])) if np.any(highlight) else float("nan")

        rg = float(np.mean(np.abs(back[:, 0] - back[:, 1]) * 100.0))
        gb = float(np.mean(np.abs(back[:, 1] - back[:, 2]) * 100.0))
        ref_rg = float(np.mean(np.abs(cms[:, 0] - cms[:, 1]) * 100.0))
        ref_gb = float(np.mean(np.abs(cms[:, 1] - cms[:, 2]) * 100.0))
        rg_shift = rg - ref_rg
        gb_shift = gb - ref_gb

        print(
            f"{label:<40} {mean_all:9.4f} {sh:9.4f} {hi:10.4f} "
            f"{np.percentile(per, 99):8.4f} {np.max(per):8.4f} {rg_shift:+7.4f} {gb_shift:+7.4f}"
        )

    print()
    print(
        "mean/shadow/highlight CV = mean |ΔACEScct|×100 over RGB in band. "
        "R-G/G-B = neutrality shift (lower = better). All lower is better."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
