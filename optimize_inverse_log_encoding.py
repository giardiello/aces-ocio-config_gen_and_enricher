#!/usr/bin/env python3
"""
Grid-search inverse log encoding by baking inverse cubes and scoring recovery vs AP0.

Pipeline per sample: ACEScct -> AP0 -> VT forward -> display d -> [LUT + decode] -> AP0'
Inverse cube maps **display linear** (same as forward VT output) into the remapped log
domain; encode-before-LUT was removed (old Un-tone-mapped + inv VT chain was wrong).

Requires: PyOpenColorIO, numpy, OpenImageIO. Reference config must support bake (Un-tone-mapped + VT).

Usage:
  python optimize_inverse_log_encoding.py [--ref CONFIG] [--vt NAME] [--lut-size 40] [--max-samples 25000]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

import numpy as np
import PyOpenColorIO as ocio

try:
    import OpenImageIO as oiio
except ImportError:
    print("pip install OpenImageIO", file=sys.stderr)
    sys.exit(1)

# Import bake helpers from generator (same reference workflow)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_lut_based_config as glc  # noqa: E402

CHUNK = 32768
DEFAULT_VT = "ACES 2.0 - SDR 100 nits (Rec.709)"
# Same config for bake + VT forward (avoid v2.4 vs v2.5 ODT mismatch).
DEFAULT_REF = "INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio"


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


def apply_chunked(cpu, arr: np.ndarray) -> None:
    n = len(arr)
    for i in range(0, n, CHUNK):
        sl = slice(i, min(i + CHUNK, n))
        cpu.apply(ocio.PackedImageDesc(arr[sl].ravel(), sl.stop - sl.start, 1, 3))


def linear_y_ap1(ap1: np.ndarray) -> np.ndarray:
    r, g, b = ap1[:, 0], ap1[:, 1], ap1[:, 2]
    return 0.2722287 * r + 0.6740818 * g + 0.0536895 * b


def score_candidate(
    ref_path: str,
    vt_name: str,
    lut_size: int,
    cms_acescct: np.ndarray,
    ap1_ref: np.ndarray,
    y_ref: np.ndarray,
    shadow_mask: np.ndarray,
    encoding: str,
    lin_min: float,
    lin_max: float,
    lin_break: float | None,
) -> dict | None:
    cfg_dir = os.path.dirname(os.path.abspath(ref_path))
    old = os.getcwd()
    os.chdir(cfg_dir)
    try:
        config = ocio.Config.CreateFromFile(os.path.basename(ref_path))
        glc.setup_bake_display(config)
        if encoding == "acescc":
            glc.setup_acescc_remap_cs(config)
            _, dec_ops = glc.get_acescc_clf_ops(config)
        elif encoding == "extended":
            glc.setup_extended_log_remap_cs(config, lin_min, lin_max)
            _, dec_ops = glc.get_extended_log_clf_ops(config, lin_min, lin_max)
        elif encoding == "camera":
            glc.setup_camera_log_remap_cs(config, lin_min, lin_max, lin_break or 0.0078125)
            _, dec_ops = glc.get_camera_log_clf_ops(
                config, lin_min, lin_max, lin_break or 0.0078125
            )
        else:
            return None

        view_short = glc.sanitize_lut_filename(vt_name)
        existing_views = list(config.getViews(glc.TEMP_DISPLAY))
        if view_short not in existing_views:
            config.addDisplayView(
                display=glc.TEMP_DISPLAY,
                view=view_short,
                viewTransform=vt_name,
                displayColorSpaceName=glc.TEMP_PASSTHROUGH_CS,
            )
        fd, cube = tempfile.mkstemp(suffix=".cube")
        os.close(fd)
        try:
            glc.bake_inverse_cube(config, vt_name, cube, lut_size)
        except Exception as e:
            os.unlink(cube)
            return {"error": str(e)}

        gt = ocio.GroupTransform()
        gt.appendTransform(
            ocio.FileTransform(os.path.abspath(cube), interpolation=ocio.INTERP_BEST)
        )
        for op in dec_ops:
            gt.appendTransform(op)

        try:
            p_lut = config.getProcessor(gt).getDefaultCPUProcessor()
        except Exception as e:
            os.unlink(cube)
            return {"error": str(e)}

        dvt = ocio.DisplayViewTransform(
            src="ACES2065-1",
            display=glc.TEMP_DISPLAY,
            view=view_short,
            direction=ocio.TRANSFORM_DIR_FORWARD,
        )
        p_disp = config.getProcessor(dvt).getDefaultCPUProcessor()

        ap0 = cms_acescct.copy()
        config.getProcessor("ACEScct", "ACES2065-1").getDefaultCPUProcessor().apply(
            ocio.PackedImageDesc(ap0.ravel(), len(ap0), 1, 3)
        )
        d = ap0.copy()
        apply_chunked(p_disp, d)
        rec = d.copy()
        apply_chunked(p_lut, rec)

        err = np.abs(rec - ap0).max(axis=1) * 100.0
        os.unlink(cube)

        return {
            "mean": float(np.mean(err)),
            "p95": float(np.percentile(err, 95)),
            "p99": float(np.percentile(err, 99)),
            "max": float(np.max(err)),
            "shadow_mean": float(np.mean(err[shadow_mask])) if np.any(shadow_mask) else 0.0,
            "highlight_mean": float(np.mean(err[~shadow_mask])) if np.any(~shadow_mask) else 0.0,
            "composite": float(0.45 * np.mean(err[shadow_mask]) + 0.55 * np.mean(err))
            if np.any(shadow_mask)
            else float(np.mean(err)),
        }
    finally:
        os.chdir(old)


def main() -> int:
    base = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=os.path.join(base, DEFAULT_REF))
    ap.add_argument("--vt", default=DEFAULT_VT)
    ap.add_argument("--cms", default=os.path.join(base, "test_assets", "CMS_32.exr"))
    ap.add_argument("--lut-size", type=int, default=40)
    ap.add_argument("--max-samples", type=int, default=25000)
    ap.add_argument(
        "--ap1-y-max",
        type=float,
        default=1.5,
        help="Keep CMS pixels with AP1 linear Y <= this (SDR view is ill-defined far above ~1–2; default 1.5)",
    )
    ap.add_argument(
        "--ap1-y-min",
        type=float,
        default=1e-6,
        help="Minimum AP1 Y (drops black-floor junk)",
    )
    args = ap.parse_args()

    if not os.path.isfile(args.ref):
        print(f"Reference not found: {args.ref}", file=sys.stderr)
        return 1

    cms = load_cms(args.cms, args.max_samples)
    cfg_s = os.path.join(base, "INPUT_OCIO", "STUDIO", "studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio")
    os.chdir(os.path.dirname(cfg_s))
    c = ocio.Config.CreateFromFile(os.path.basename(cfg_s))
    ap1 = cms.copy()
    c.getProcessor("ACEScct", "ACEScg").getDefaultCPUProcessor().apply(
        ocio.PackedImageDesc(ap1.ravel(), len(ap1), 1, 3)
    )
    y = linear_y_ap1(ap1)
    m = (y >= args.ap1_y_min) & (y <= args.ap1_y_max)
    cms = cms[m]
    ap1 = ap1[m]
    y = y[m]
    shadow = y < 0.05
    if len(cms) < 100:
        print(
            f"Warning: only {len(cms)} samples after AP1 Y filter "
            f"[{args.ap1_y_min}, {args.ap1_y_max}] — widen range if needed.",
            file=sys.stderr,
        )

    candidates: list[tuple[str, dict]] = []

    # ACEScc baseline
    candidates.append(("acescc default", {"encoding": "acescc", "lin_min": 0, "lin_max": 0, "lin_break": None}))

    lin_mins = [1e-6, 2.0**-15, 2.0**-12, 0.001]
    lin_maxs = [48.0, 229.0, 2000.0, 65504.0]
    for a in lin_mins:
        for b in lin_maxs:
            if b <= a * 100:
                continue
            candidates.append(
                (f"ext-log min={a:g} max={b:g}", {"encoding": "extended", "lin_min": a, "lin_max": b, "lin_break": None})
            )

    breaks = [2.0**-15, 0.001, 0.005, 0.0078125, 0.01, 0.015625]
    for a in [2.0**-12, 2.0**-15]:
        for b in [229.0, 2000.0, 65504.0]:
            for br in breaks:
                if br >= b * 0.5:  # need headroom above toe
                    continue
                candidates.append(
                    (
                        f"cam-log min={a:g} max={b:g} break={br:g}",
                        {
                            "encoding": "camera",
                            "lin_min": a,
                            "lin_max": b,
                            "lin_break": br,
                        },
                    )
                )

    print(
        f"VT: {args.vt}  |  LUT³={args.lut_size}  |  samples={len(cms)} "
        f"(AP1 Y in [{args.ap1_y_min:g}, {args.ap1_y_max:g}])"
    )
    print(
        "Composite score = 0.45*shadow_mean_CV + 0.55*overall_mean_CV (shadow: AP1 Y<0.05)\n"
    )

    ref_full = args.ref if os.path.isabs(args.ref) else os.path.join(base, args.ref)
    results: list[tuple[str, dict]] = []
    for label, kw in candidates:
        r = score_candidate(
            ref_full,
            args.vt,
            args.lut_size,
            cms,
            ap1,
            y,
            shadow,
            kw["encoding"],
            kw["lin_min"],
            kw["lin_max"],
            kw["lin_break"],
        )
        if r is None or r.get("error"):
            print(f"  FAIL {label}: {r.get('error') if r else 'None'}")
            continue
        results.append((label, r))
        print(
            f"  {label[:50]:50}  comp={r['composite']:6.3f}  mean={r['mean']:6.3f}  "
            f"sh={r['shadow_mean']:6.3f}  p99={r['p99']:6.2f}  max={r['max']:7.2f}"
        )

    if not results:
        return 1
    results.sort(key=lambda x: x[1]["composite"])
    print("\n--- Top 5 by composite (shadow-weighted) ---")
    for label, r in results[:5]:
        print(f"  {r['composite']:.3f}  {label}")
        print(f"      mean CV={r['mean']:.3f}  shadow={r['shadow_mean']:.3f}  highlight~={r['highlight_mean']:.3f}")

    best = results[0]
    b = best[1]
    print(
        f"\nRecommended (this grid, {args.vt}): {best[0]}\n"
        f"  mean_CV={b['mean']:.2f}  shadow_CV={b['shadow_mean']:.2f}  p99_CV={b['p99']:.2f}\n"
        "  generate_lut_based_config.py:\n"
        "    --inv-encoding camera-log|extended-log|acescc\n"
        "    --inv-log-lin-min / --inv-log-lin-max / --inv-camera-log-lin-break (camera-log)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
