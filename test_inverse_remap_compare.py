#!/usr/bin/env python3
"""
Compare inverse CMS metrics: ACEScct shaper with Range (default) vs --inv-remap none.

  **range (default):** Log code at AP0 endpoints → Range → [0,1] → 3D LUT → Range⁻¹ → Log decode
  **none:**          Log code → 3D LUT directly (LUT stores raw codes) → Log decode

The OCIO Range here is a **linear** map (cmin..cmax ↔ 0..1); it is not a tone curve.
Replacing it with an equivalent scale+offset would match in float, but CLF cannot express
that Matrix+offset without using Range. So “effect of Range” vs “no Range” is really:
**whether the 3D LUT is indexed in normalized [0,1] or in raw log code space** — different
sampling of the cube, so metrics can differ.

Usage:
  python test_inverse_remap_compare.py [--regenerate] [--max-samples N]
"""

from __future__ import annotations

import argparse
import os
import subprocess
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
REF_V24 = os.path.join(
    BASE, "INPUT_OCIO/STUDIO/studio-config-v3.0.0_aces-v2.0_ocio-v2.4.ocio"
)
BUILTIN_STUDIO = os.path.join(
    BASE, "INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio"
)
OUT = os.path.join(BASE, "OUTPUT", "remap_ab")
GEN = os.path.join(BASE, "generate_lut_based_config.py")

CHUNK = 65536
FWD, INV = 65, 97


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


def cfg_path(tag: str) -> str:
    return os.path.join(OUT, tag, "studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio")


def regenerate() -> int:
    if not os.path.isfile(REF_V24):
        print(f"Missing {REF_V24}", file=sys.stderr)
        return 1
    for tag, remap in (("range", "range"), ("none", "none")):
        odir = os.path.join(OUT, tag)
        os.makedirs(odir, exist_ok=True)
        cmd = [
            sys.executable,
            GEN,
            REF_V24,
            "-o",
            odir,
            "--inv-encoding",
            "acescct",
            "--inv-remap",
            remap,
            "-s",
            str(FWD),
            "--inv-lut-size",
            str(INV),
        ]
        print(" ".join(cmd))
        r = subprocess.run(cmd, cwd=BASE)
        if r.returncode != 0:
            return r.returncode
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regenerate", action="store_true")
    ap.add_argument("--cms", default=os.path.join(BASE, "test_assets", "CMS_32.exr"))
    ap.add_argument("--max-samples", type=int, default=30000)
    ap.add_argument("--display", default="sRGB - Display")
    ap.add_argument("--view", default="ACES 2.0 - SDR 100 nits (Rec.709)")
    args = ap.parse_args()

    if args.regenerate:
        rc = regenerate()
        if rc != 0:
            return rc

    if not os.path.isfile(BUILTIN_STUDIO) or not os.path.isfile(args.cms):
        print("Missing built-in studio or CMS", file=sys.stderr)
        return 1

    cms = load_cms(args.cms, args.max_samples)
    ap1 = ap1_from_cms(cms)
    y = linear_y_ap1(ap1)
    shadow = y < 0.05
    highlight = y >= 2.0

    # Linear equivalence: Range cmin..cmax -> 0..1 equals (x-cmin)/(cmax-cmin)
    cmin, cmax = 0.07290564, 1.46799631  # ACEScct codes @ AP0 1e-8 .. 65504 (neutral)
    x = np.linspace(cmin, cmax, 10000, dtype=np.float64)
    ocio_range_out = (x - cmin) / (cmax - cmin)
    assert np.allclose(ocio_range_out, (x - cmin) / (cmax - cmin))

    print()
    print("ACEScct inverse: Range (norm [0,1] LUT domain) vs none (raw code LUT domain)")
    print(f"  LUT {FWD}³ / {INV}³ | samples={len(cms)} shadow={int(np.sum(shadow))} hi={int(np.sum(highlight))}")
    print(
        f"  Note: Range here is linear ({cmin:.4f}..{cmax:.4f} ↔ 0..1); "
        "difference vs none is **LUT resampling**, not a nonlinear Range curve."
    )
    print()
    hdr = f"{'Case':<42} {'mean CV':>9} {'shadow':>9} {'highlight':>10} {'p99 mx':>8} {'max':>8}"
    print(hdr)
    print("-" * len(hdr))

    cpu_fwd = load_cpu(BUILTIN_STUDIO, args.display, args.view, forward=True)

    rows = [
        ("ACEScct + Range → [0,1] (default)", "range"),
        ("ACEScct + no Range (raw codes in LUT)", "none"),
    ]
    for label, tag in rows:
        path = cfg_path(tag)
        if not os.path.isfile(path):
            print(f"{label:<42}  (missing; run --regenerate)")
            continue
        cpu_inv = load_cpu(path, args.display, args.view, forward=False)
        disp = cms.copy()
        apply_chunked(cpu_fwd, disp)
        back = dpx16_q(disp).copy()
        apply_chunked(cpu_inv, back)
        err = np.abs(back - cms) * 100.0
        per = np.max(err, axis=1)
        print(
            f"{label:<42} {float(np.mean(err)):9.2f} "
            f"{float(np.mean(err[shadow])) if np.any(shadow) else float('nan'):9.2f} "
            f"{float(np.mean(err[highlight])) if np.any(highlight) else float('nan'):10.2f} "
            f"{np.percentile(per, 99):8.2f} {np.max(per):8.2f}"
        )

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
