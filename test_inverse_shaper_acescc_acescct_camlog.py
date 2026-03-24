#!/usr/bin/env python3
"""
Regenerate (optional) and compare inverse CLF shapers on CMS:

  - **ACEScc** (LogCamera toe 2^-15 + log, Range on code)
  - **ACEScct** (ACEScct LogCamera + Range on code)
  - **Camera-log balanced**: wide linear range [1e-7, 65504] with toe at 2^-15 so the
    normalized LUT domain gets resolution in **shadows** (low lin_min + toe) and **highlights** (high lin_max).

Pipeline: ACEScct → built-in v2.5 forward → DPX16 quantize → inverse → ACEScct vs CMS.

Usage:
  python test_inverse_shaper_acescc_acescct_camlog.py [--regenerate] [--max-samples N]
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
OUT_ROOT = os.path.join(BASE, "OUTPUT", "shaper_compare")

SHAPERS = [
    (
        "ACEScc",
        os.path.join(OUT_ROOT, "acescc", "studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
        ["acescc"],
    ),
    (
        "ACEScct",
        os.path.join(OUT_ROOT, "acescct", "studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
        ["acescct"],
    ),
    (
        "Camera-log (balanced shadow+HL)",
        os.path.join(
            OUT_ROOT,
            "camlog_balanced",
            "studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio",
        ),
        [
            "camera-log",
            "--inv-log-lin-min",
            "1e-7",
            "--inv-log-lin-max",
            "65504",
            "--inv-camera-log-lin-break",
            str(2.0**-15),
        ],
    ),
]

CHUNK = 65536
FWD_LUT = 65
INV_LUT = 97


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


def regenerate_all() -> int:
    if not os.path.isfile(REF_V24):
        print(f"Missing reference config: {REF_V24}", file=sys.stderr)
        return 1
    gen = os.path.join(BASE, "generate_lut_based_config.py")
    for name, out_sub, extra in SHAPERS:
        odir = os.path.dirname(out_sub)
        os.makedirs(odir, exist_ok=True)
        cmd = [
            sys.executable,
            gen,
            REF_V24,
            "-o",
            odir,
            "--inv-encoding",
            extra[0],
            "-s",
            str(FWD_LUT),
            "--inv-lut-size",
            str(INV_LUT),
        ]
        if len(extra) > 1:
            cmd.extend(extra[1:])
        print(" ".join(cmd))
        r = subprocess.run(cmd, cwd=BASE)
        if r.returncode != 0:
            print(f"FAILED: {name}", file=sys.stderr)
            return r.returncode
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regenerate", action="store_true", help="Run generate_lut_based_config for all three shapers")
    ap.add_argument("--cms", default=os.path.join(BASE, "test_assets", "CMS_32.exr"))
    ap.add_argument("--max-samples", type=int, default=30000)
    ap.add_argument("--display", default="sRGB - Display")
    ap.add_argument("--view", default="ACES 2.0 - SDR 100 nits (Rec.709)")
    args = ap.parse_args()

    if args.regenerate:
        rc = regenerate_all()
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

    print()
    print("Inverse shaper comparison (forward = built-in v2.5, DPX16, SDR Rec.709)")
    print(f"  LUT sizes: forward {FWD_LUT}³, inverse {INV_LUT}³")
    print(f"  Camera-log balanced: AP1 lin [{1e-7:g}, 65504], toe break 2^-15")
    print(f"  Samples: {len(cms)} | shadow Y<0.05: {int(np.sum(shadow))} | highlight Y≥2: {int(np.sum(highlight))}")
    print()

    hdr = (
        f"{'Shaper':<36} {'mean CV':>9} {'shadow':>9} {'highlight':>10} "
        f"{'p99 mx':>8} {'max':>8}"
    )
    print(hdr)
    print("-" * len(hdr))

    cpu_fwd = load_cpu(BUILTIN_STUDIO, args.display, args.view, forward=True)

    rows = [("Built-in (analytical)", BUILTIN_STUDIO)]
    for label, path, _ in SHAPERS:
        rows.append((label, path))

    for label, cfg in rows:
        if not os.path.isfile(cfg):
            print(f"{label:<36}  (missing {cfg})")
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
        print(
            f"{label:<36} {mean_all:9.2f} {sh:9.2f} {hi:10.2f} "
            f"{np.percentile(per, 99):8.2f} {np.max(per):8.2f}"
        )

    print()
    print(
        "mean/shadow/highlight CV = mean |ΔACEScct|×100 over RGB in band. "
        "Lower is better. Built-in has no inverse LUT quantization."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
