#!/usr/bin/env python3
"""
CMS pipeline (built-in forward, uint16 display quantize, LUT inverse) with errors
split by **scene-linear luma** band (AP1 after ACEScct decode).

Compares shadow vs mid vs highlight recovery for:
  - SDR: sRGB / Rec.709 100 nits
  - HDR: PQ 4000 nits Rec.2020 (and optionally more)

Built-in inverse reference: inverse Display+View + ACES2065-1→ACEScct.
Inverse configs: built-in, ACEScc, extended-log, camera-log (no jplog2).

Usage:
  python test_shaper_sdr_hdr_bands.py [--max-samples 120000]
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

BUILTIN = "INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio"
CHUNK = 65536

TARGETS = [
    ("SDR_sRGB", "sRGB - Display", "ACES 2.0 - SDR 100 nits (Rec.709)"),
    ("HDR_PQ4k_Rec2020", "Rec.2100-PQ - Display", "ACES 2.0 - HDR 4000 nits (Rec.2020)"),
    ("HDR_PQ1k_Rec2020", "Rec.2100-PQ - Display", "ACES 2.0 - HDR 1000 nits (Rec.2020)"),
]

INVERSES = [
    ("builtin", BUILTIN),
    ("ACEScc", "OUTPUT/clf_v2_no_hl/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
    ("extended-log", "OUTPUT/extended_log_test/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
    ("camera-log", "OUTPUT/camera_log_test/studio-config-v3.0.0_aces-v2.0_ocio-v2.3-clf.ocio"),
]

# AP1 / ACEScg luma (same weights as common AP1 display luma approx)
def linear_Y_ap1(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    return (0.2722287 * r + 0.6740818 * g + 0.0536895 * b).astype(np.float32)


BANDS = [
    ("deep_sh Y<0.005", lambda y: y < 0.005),
    ("shadow 0.005-0.02", lambda y: (y >= 0.005) & (y < 0.02)),
    ("low_mid 0.02-0.1", lambda y: (y >= 0.02) & (y < 0.1)),
    ("mid 0.1-0.5", lambda y: (y >= 0.1) & (y < 0.5)),
    ("upper 0.5-2", lambda y: (y >= 0.5) & (y < 2.0)),
    ("bright Y>=2", lambda y: y >= 2.0),
]


def load_cms(path: str) -> np.ndarray:
    inp = oiio.ImageInput.open(path)
    if inp is None:
        raise RuntimeError(oiio.geterror())
    p = np.array(inp.read_image(format=oiio.FLOAT), dtype=np.float32)
    inp.close()
    if p.ndim == 3:
        p = p.reshape(-1, p.shape[-1])
    return p[:, :3].copy()


def load_cpu(base: str, rel: str, display: str, view: str, forward: bool):
    path = os.path.join(base, rel)
    d = os.path.dirname(path)
    old = os.getcwd()
    os.chdir(d)
    try:
        c = ocio.Config.CreateFromFile(os.path.basename(path))
        g = (
            group_forward_acescct_to_display_view(display, view)
            if forward
            else group_inverse_display_view_to_acescct(display, view)
        )
        return c.getProcessor(g).getDefaultCPUProcessor()
    finally:
        os.chdir(old)


def apply_chunked(cpu, arr: np.ndarray) -> None:
    n = len(arr)
    for i in range(0, n, CHUNK):
        sl = slice(i, min(i + CHUNK, n))
        cpu.apply(ocio.PackedImageDesc(arr[sl].ravel(), sl.stop - sl.start, 1, 3))


def decode_acescct_to_ap1(base: str, cms: np.ndarray) -> np.ndarray:
    path = os.path.join(base, BUILTIN)
    d = os.path.dirname(path)
    old = os.getcwd()
    os.chdir(d)
    try:
        c = ocio.Config.CreateFromFile(os.path.basename(path))
        cpu = c.getProcessor("ACEScct", "ACEScg").getDefaultCPUProcessor()
    finally:
        os.chdir(old)
    ap1 = cms.copy()
    apply_chunked(cpu, ap1)
    return ap1


def main() -> int:
    base = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--cms", default=os.path.join(base, "test_assets", "CMS_32.exr"))
    ap.add_argument("--max-samples", type=int, default=120000)
    args = ap.parse_args()

    cms = load_cms(args.cms)
    if args.max_samples > 0 and len(cms) > args.max_samples:
        rng = np.random.default_rng(42)
        ix = rng.choice(len(cms), size=args.max_samples, replace=False)
        cms = cms[ix]

    ap1 = decode_acescct_to_ap1(base, cms)
    y = linear_Y_ap1(ap1)

    print(f"Samples: {len(cms)} | Forward: built-in ACES 2.5 | Bands: AP1 linear Y from CMS ACEScct\n")

    for tname, display, view in TARGETS:
        print("=" * 76)
        print(f"{tname}  |  {display} / {view}")
        print("-" * 76)
        cpu_fwd = load_cpu(base, BUILTIN, display, view, True)
        for inv_name, inv_rel in INVERSES:
            if not os.path.isfile(os.path.join(base, inv_rel)):
                print(f"  [{inv_name}] SKIP missing")
                continue
            try:
                cpu_inv = load_cpu(base, inv_rel, display, view, False)
            except Exception as e:
                print(f"  [{inv_name}] FAIL {e}")
                continue
            disp = cms.copy()
            apply_chunked(cpu_fwd, disp)
            dpx = np.clip(disp, 0, 1.0)
            dpx = (np.round(dpx * 65535) / 65535.0).astype(np.float32)
            back = dpx.copy()
            apply_chunked(cpu_inv, back)
            err = np.abs(back - cms).max(axis=1) * 100.0
            parts = []
            for bname, mask_fn in BANDS:
                m = mask_fn(y)
                cnt = int(np.sum(m))
                if cnt == 0:
                    parts.append(f"{bname}: n=0")
                else:
                    parts.append(f"{bname}: meanCV={float(np.mean(err[m])):.3f} (n={cnt})")
            print(f"  {inv_name:14} " + " | ".join(parts))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
