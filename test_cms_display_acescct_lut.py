#!/usr/bin/env python3
"""
CMS (ACEScct) -> display -> 16-bit DPX round-trip -> ACEScct via:
  (a) **Built-in reference:** inverse Display+View + ACES2065-1→ACEScct (explicit group;
      see ``ocio_builtins_display.group_inverse_display_view_to_acescct``)
  (b) Baked 3D LUT (Display -> ACEScct) with INTERP_BEST

**Forward:** ACEScct→ACES2065-1→Display+View forward (``group_forward_acescct_to_display_view``).

**Config** (--builtin-config): studio all-views v2.5 for bake + same transforms as built-in.

Requires: numpy, PyOpenColorIO, OpenImageIO (for EXR/DPX).

Usage:
  python test_cms_display_acescct_lut.py [--cms PATH] [--builtin-config PATH] [--lut-size 65] ...
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

import numpy as np
import PyOpenColorIO as ocio

from ocio_builtins_display import (
    group_forward_acescct_to_display_view,
    group_inverse_display_view_to_acescct,
)

try:
    import OpenImageIO as oiio
except ImportError:
    print("Error: pip install OpenImageIO (needed for EXR/DPX).", file=sys.stderr)
    sys.exit(1)

TEMP_VIEW_DISPLAY_CS = "__VIEW_DISPLAY_RGB__"
DEFAULT_BUILTIN_STUDIO = (
    "INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio"
)


def add_view_display_colorspace(
    config: ocio.Config, display: str, view: str
) -> None:
    """Scene-referred CS: values are display RGB from this display+view."""
    if config.getColorSpace(TEMP_VIEW_DISPLAY_CS):
        config.removeColorSpace(TEMP_VIEW_DISPLAY_CS)
    cs = ocio.ColorSpace()
    cs.setName(TEMP_VIEW_DISPLAY_CS)
    fwd = ocio.DisplayViewTransform(
        src="ACES2065-1",
        display=display,
        view=view,
        direction=ocio.TRANSFORM_DIR_FORWARD,
    )
    cs.setTransform(fwd, ocio.COLORSPACE_DIR_FROM_REFERENCE)
    config.addColorSpace(cs)


def bake_display_to_acescct_cube(
    config: ocio.Config, lut_size: int, cube_path: str
) -> None:
    """Bake 3D LUT: view display RGB -> ACEScct (OCIO Baker)."""
    baker = ocio.Baker()
    baker.setConfig(config)
    baker.setFormat("iridas_cube")
    baker.setCubeSize(lut_size)
    baker.setInputSpace(TEMP_VIEW_DISPLAY_CS)
    baker.setTargetSpace("ACEScct")
    baker.bake(cube_path)


def load_cms_acescct(path: str) -> np.ndarray:
    """Load EXR (or image) as Nx3 float32 ACEScct samples."""
    inp = oiio.ImageInput.open(path)
    if inp is None:
        raise RuntimeError(f"Cannot open {path}: {oiio.geterror()}")
    spec = inp.spec()
    pixels = np.array(inp.read_image(format=oiio.FLOAT), dtype=np.float32)
    inp.close()
    if pixels.ndim == 3:
        pixels = pixels.reshape(-1, pixels.shape[-1])
    if pixels.shape[1] > 3:
        pixels = pixels[:, :3]
    return pixels


def display_to_dpx16_roundtrip(
    display_rgb: np.ndarray, dpx_out: str | None
) -> np.ndarray:
    """
    Quantize display linear 0..1 to uint16, optional write/read DPX (2D layout), return float.
    """
    n = len(display_rgb)
    d = np.clip(display_rgb, 0.0, 1.0)
    u16 = np.round(d * 65535.0).astype(np.uint16)
    if dpx_out:
        w = min(4096, max(64, int(np.ceil(np.sqrt(n)))))
        h = (n + w - 1) // w
        pad = h * w - n
        if pad:
            u16 = np.vstack([u16, np.zeros((pad, 3), dtype=np.uint16)])
        spec = oiio.ImageSpec(w, h, 3, oiio.UINT16)
        spec.attribute("oiio:BitsPerSample", 16)
        out = oiio.ImageOutput.create(dpx_out)
        if out is None:
            raise RuntimeError(oiio.geterror())
        if not out.open(dpx_out, spec):
            raise RuntimeError(oiio.geterror())
        img = u16.reshape(h, w, 3)
        out.write_image(img)
        out.close()
        inp = oiio.ImageInput.open(dpx_out)
        if inp is None:
            raise RuntimeError(f"DPX read failed: {oiio.geterror()}")
        u16 = np.array(inp.read_image(format=oiio.UINT16), dtype=np.uint16).reshape(-1, 3)[:n]
        inp.close()
    return u16.astype(np.float32) / 65535.0


def main() -> int:
    base = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        description="CMS ACEScct -> DPX16 display -> ACEScct: built-in vs baked LUT (INTERP_BEST)"
    )
    ap.add_argument(
        "--builtin-config",
        default=os.path.join(base, DEFAULT_BUILTIN_STUDIO),
        metavar="PATH",
        help="ACES 2.5 built-in studio config (forward + bake + built-in inverse); default: all-views v2.5",
    )
    ap.add_argument("--display", default="sRGB - Display")
    ap.add_argument("--view", default="ACES 2.0 - SDR 100 nits (Rec.709)")
    ap.add_argument(
        "--cms",
        default=os.path.join(base, "test_assets", "CMS_32.exr"),
        help="CMS image (interpreted as ACEScct)",
    )
    ap.add_argument("--lut-size", type=int, default=65)
    ap.add_argument(
        "--dpx-out",
        default=None,
        help="If set, write/read this DPX path (else in-memory quantize only)",
    )
    ap.add_argument(
        "--keep-cube",
        default=None,
        help="If set, copy baked .cube to this path",
    )
    args = ap.parse_args()

    cfg_path = os.path.abspath(args.builtin_config)
    if not os.path.isfile(cfg_path):
        print(f"Built-in config not found: {cfg_path}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.cms):
        print(f"CMS not found: {args.cms}", file=sys.stderr)
        return 1

    os.chdir(os.path.dirname(cfg_path))
    config = ocio.Config.CreateFromFile(os.path.basename(cfg_path))
    add_view_display_colorspace(config, args.display, args.view)

    fd, cube_path = tempfile.mkstemp(suffix=".cube", prefix="dtac_")
    os.close(fd)
    try:
        print(f"Built-in config (forward + bake + ref inverse): {cfg_path}")
        print(f"Baking {args.lut_size}³ LUT: {TEMP_VIEW_DISPLAY_CS} -> ACEScct ...")
        bake_display_to_acescct_cube(config, args.lut_size, cube_path)
        if args.keep_cube:
            import shutil

            shutil.copy(cube_path, args.keep_cube)
            print(f"Cube saved: {args.keep_cube}")

        cms = load_cms_acescct(args.cms)
        n = cms.shape[0]
        print(f"CMS samples: {n} (ACEScct)")

        # ACEScct -> display: explicit built-in forward chain
        p_fwd = config.getProcessor(
            group_forward_acescct_to_display_view(args.display, args.view)
        )
        cpu_fwd = p_fwd.getDefaultCPUProcessor()
        disp = cms.copy()
        buf = ocio.PackedImageDesc(disp.ravel(), n, 1, 3)
        cpu_fwd.apply(buf)

        dpx_f = display_to_dpx16_roundtrip(disp, args.dpx_out)
        if args.dpx_out:
            print(f"DPX 16-bit round-trip: {args.dpx_out}")

        # (a) Built-in: inverse Display+View + ACES2065-1 -> ACEScct
        p_builtin = config.getProcessor(
            group_inverse_display_view_to_acescct(args.display, args.view)
        )
        cpu_b = p_builtin.getDefaultCPUProcessor()
        acescct_builtin = dpx_f.copy()
        cpu_b.apply(ocio.PackedImageDesc(acescct_builtin.ravel(), n, 1, 3))

        # (b) LUT INTERP_BEST
        ft = ocio.FileTransform(
            os.path.abspath(cube_path),
            interpolation=ocio.INTERP_BEST,
            direction=ocio.TRANSFORM_DIR_FORWARD,
        )
        p_lut = ocio.Config.CreateRaw().getProcessor(ft)
        cpu_lut = p_lut.getDefaultCPUProcessor()
        acescct_lut = dpx_f.copy()
        cpu_lut.apply(ocio.PackedImageDesc(acescct_lut.ravel(), n, 1, 3))

        diff_ab = np.abs(acescct_builtin - acescct_lut) * 100.0
        max_cv_ab = float(np.max(diff_ab))
        mean_cv_ab = float(np.mean(diff_ab))

        # vs original CMS (full chain error)
        err_a = np.abs(acescct_builtin - cms) * 100.0
        err_b = np.abs(acescct_lut - cms) * 100.0

        p99 = float(np.percentile(diff_ab, 99))
        p95 = float(np.percentile(diff_ab, 95))
        print()
        print("=== Built-in vs LUT (after DPX16 display round-trip) ===")
        print(f"  Max |A-B| (CV):  {max_cv_ab:.4f}")
        print(f"  p99 |A-B| (CV): {p99:.4f}   p95: {p95:.4f}")
        print(f"  Mean |A-B| (CV): {mean_cv_ab:.6f}")
        print(f"  Per-channel max (CV): R={np.max(diff_ab[:,0]):.4f} G={np.max(diff_ab[:,1]):.4f} B={np.max(diff_ab[:,2]):.4f}")
        print()
        print("=== vs original CMS (ACEScct) ===")
        print(f"  Built-in max CV error: {float(np.max(err_a)):.4f}  mean: {float(np.mean(err_a)):.6f}")
        print(f"  LUT max CV error:      {float(np.max(err_b)):.4f}  mean: {float(np.mean(err_b)):.6f}")
        print()
        print("A = inverse Display+View + ACES2065-1→ACEScct (built-in reference)")
        print("B = baked Display->ACEScct LUT + INTERP_BEST")
    finally:
        try:
            os.unlink(cube_path)
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
