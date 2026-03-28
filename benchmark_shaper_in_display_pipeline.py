#!/usr/bin/env python3
"""
Benchmark alternative shapers inside the display-shaper CLF pipeline.

Keeps the display-shaper bake structure (domain probing, normalization,
analytical XYZ<->AP1 ops) but swaps the shaper that distributes values
across the 3D LUT grid.

Shapers tested:
  - gamma22      : x^(1/2.2) encode (SDR default)
  - pq           : PQ ST-2084 encode (HDR default)
  - acescct      : ACEScct LogCamera encode
  - acescc       : ACEScc LogCamera encode
  - extended-log : LogAffine [2^-12 .. 65504]
  - camera-log   : LogCamera with toe at 0.015625
  - jplog2       : pseudo-log 1D LUT

For each shaper, bakes a forward+inverse cube pair for one SDR and one HDR
view transform, then measures roundtrip precision per scene-linear band.

Usage:
    python benchmark_shaper_in_display_pipeline.py [--inv-lut-size 97] [--csv results.csv]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile

import numpy as np
import PyOpenColorIO as ocio

from generate_lut_based_config import (
    ACESCT_M_AP0_AP1,
    ACESCT_M_AP1_AP0,
    BUILTIN_BAKE_CONFIG,
    _get_vt_builtin_style,
    _make_domain_denormalize,
    _make_domain_normalize,
    _remove_cs_if_exists,
    get_acescct_decode_ops,
    get_acescct_encode_ops,
    get_acescc_clf_ops,
    get_camera_log_clf_ops,
    get_extended_log_clf_ops,
    get_gamma22_decode_op,
    get_gamma22_encode_op,
    get_pq_decode_op,
    get_pq_encode_op,
    get_untm_ops,
)
from inverse_pseudolog import (
    PseudoLogParams,
    build_decode_lut1d,
    build_encode_lut1d,
    make_range_lin_to_unit,
)

BANDS = [
    ("Shadow (0.001-0.01)",    0.001,  0.01,   40),
    ("Low-mid (0.01-0.1)",     0.01,   0.1,    60),
    ("Upper (0.1-0.5)",        0.1,    0.5,    80),
    ("Bright (0.5-1)",         0.5,    1.0,    50),
    ("Super bright (1-2)",     1.0,    2.0,    40),
    ("Very bright (2-10)",     2.0,    10.0,   50),
    ("High (10-50)",           10.0,   50.0,   60),
    ("Very high (50-100)",     50.0,   100.0,  50),
    ("ACEScct top (100-222)",  100.0,  222.0,  60),
]

VT_SDR = "ACES 2.0 - SDR 100 nits (Rec.709)"
VT_HDR = "ACES 2.0 - HDR 1000 nits (Rec.2020)"

TEMP_FWD_CS = "__shaper_bench_fwd__"
TEMP_INV_CS = "__shaper_bench_inv__"


def _make_shaper_ops(name: str, config) -> tuple[list, list, str]:
    """Return (encode_ops, decode_ops, label) for a named shaper.

    All shapers operate on AP1 linear and produce [0,1] encoded values.
    The AP0<->AP1 matrix is NOT included here (handled by the pipeline).
    """
    if name == "gamma22":
        return [get_gamma22_encode_op()], [get_gamma22_decode_op()], "Gamma 2.2"
    if name == "pq":
        return [get_pq_encode_op()], [get_pq_decode_op()], "PQ (ST 2084)"
    if name == "acescct":
        _, log_enc = get_acescct_encode_ops(config)
        log_dec, _ = get_acescct_decode_ops(config)
        return [log_enc], [log_dec], "ACEScct LogCamera"
    if name == "acescc":
        enc_ops, dec_ops = get_acescc_clf_ops(config, "range")
        return enc_ops[1:], dec_ops[:-1], "ACEScc LogCamera+Range"
    if name == "extended-log":
        enc_ops, dec_ops = get_extended_log_clf_ops(config, 2.0**-12, 65504.0)
        return enc_ops[1:], dec_ops[:-1], "Extended Log [2^-12..65504]"
    if name == "camera-log":
        enc_ops, dec_ops = get_camera_log_clf_ops(
            config, 2.0**-12, 65504.0, lin_break=0.015625
        )
        return enc_ops[1:], dec_ops[:-1], "Camera Log (toe=0.015625)"
    if name == "jplog2":
        params = PseudoLogParams()
        lin_min, lin_max = -0.02, 65504.0
        rng = make_range_lin_to_unit(lin_min, lin_max)
        encode_lut, _, _ = build_encode_lut1d(4096, params, lin_min, lin_max)
        decode_lut = build_decode_lut1d(4096, params)
        return [rng, encode_lut], [decode_lut], "JPlog2 pseudo-log"
    raise ValueError(f"Unknown shaper: {name}")


def _probe_shaper_range(
    config, vt_name: str, shaper_enc_ops: list, grid_res: int = 65, margin: float = 0.01
) -> tuple[float, float]:
    """Probe the output range of a shaper for a given VT."""
    builtin_style = _get_vt_builtin_style(config, vt_name)
    _, untm_inv_ops = get_untm_ops(config)
    log_dec, _ = get_acescct_decode_ops()

    g = ocio.GroupTransform()
    g.appendTransform(log_dec)
    g.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0))
    g.appendTransform(ocio.BuiltinTransform(style=builtin_style))
    for op in untm_inv_ops:
        g.appendTransform(op)
    g.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1))
    for op in shaper_enc_ops:
        g.appendTransform(op)

    cpu = config.getProcessor(g).getDefaultCPUProcessor()

    vals_1d = np.linspace(0.0, 1.0, grid_res, dtype=np.float32)
    grid = np.array(
        np.meshgrid(vals_1d, vals_1d, vals_1d), dtype=np.float32
    ).T.reshape(-1, 3).copy()
    cpu.apply(ocio.PackedImageDesc(grid.ravel(), len(grid), 1, 3))

    raw_min = float(grid.min())
    raw_max = float(grid.max())
    span = raw_max - raw_min
    domain_min = max(0.0, raw_min - span * margin)
    domain_max = min(1.0, raw_max + span * margin)
    return domain_min, domain_max


def _bake_cube(
    config, vt_name: str, shaper_enc_ops: list, shaper_dec_ops: list,
    cube_path: str, lut_size: int, domain_min: float, domain_max: float,
    *, forward: bool,
):
    """Bake a .cube file using the display-shaper pipeline with a custom shaper."""
    builtin_style = _get_vt_builtin_style(config, vt_name)
    untm_fwd_ops, untm_inv_ops = get_untm_ops(config)

    cs_name = TEMP_FWD_CS if forward else TEMP_INV_CS
    _remove_cs_if_exists(config, cs_name)
    cs = ocio.ColorSpace(ocio.REFERENCE_SPACE_SCENE, cs_name)

    g_from = ocio.GroupTransform()
    g_from.appendTransform(ocio.BuiltinTransform(style=builtin_style))
    for op in untm_inv_ops:
        g_from.appendTransform(op)
    g_from.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP0_AP1))
    for op in shaper_enc_ops:
        g_from.appendTransform(op)
    if domain_min is not None and domain_max is not None:
        g_from.appendTransform(_make_domain_normalize(domain_min, domain_max))
    cs.setTransform(g_from, ocio.COLORSPACE_DIR_FROM_REFERENCE)

    g_to = ocio.GroupTransform()
    if domain_min is not None and domain_max is not None:
        g_to.appendTransform(_make_domain_denormalize(domain_min, domain_max))
    for op in shaper_dec_ops:
        g_to.appendTransform(op)
    g_to.appendTransform(ocio.MatrixTransform(matrix=ACESCT_M_AP1_AP0))
    for op in untm_fwd_ops:
        g_to.appendTransform(op)
    g_to.appendTransform(
        ocio.BuiltinTransform(style=builtin_style, direction=ocio.TRANSFORM_DIR_INVERSE)
    )
    cs.setTransform(g_to, ocio.COLORSPACE_DIR_TO_REFERENCE)

    config.addColorSpace(cs)

    baker = ocio.Baker()
    baker.setConfig(config)
    baker.setFormat("iridas_cube")
    baker.setCubeSize(lut_size)
    if forward:
        baker.setInputSpace("ACEScct")
        baker.setTargetSpace(cs_name)
    else:
        baker.setInputSpace(cs_name)
        baker.setTargetSpace("ACEScct")
    baker.bake(cube_path)
    config.removeColorSpace(cs_name)



def _roundtrip_via_baked_cubes(
    config, vt_name: str,
    shaper_enc_ops: list, shaper_dec_ops: list,
    domain_min: float, domain_max: float,
    fwd_cube: str, inv_cube: str,
    lut_size: int,
) -> list[tuple[str, float, float]]:
    """Roundtrip through actually baked .cube files.

    The Baker produces:
      fwd_cube: ACEScct(scene) -> normalized_shaper_display [0,1]
      inv_cube: normalized_shaper_display [0,1] -> ACEScct(scene)

    Roundtrip: ACEScct -> fwd_cube -> inv_cube -> ACEScct.
    Error = pure 3D LUT interpolation error of the inverse cube.

    Input values are scene-linear gray ramps (not ACEScct-encoded).
    We encode to ACEScct first, then roundtrip through the cubes.
    """
    fwd_lut = ocio.FileTransform(src=os.path.abspath(fwd_cube), interpolation=ocio.INTERP_BEST)
    inv_lut = ocio.FileTransform(src=os.path.abspath(inv_cube), interpolation=ocio.INTERP_BEST)

    g_roundtrip = ocio.GroupTransform()
    g_roundtrip.appendTransform(fwd_lut)
    g_roundtrip.appendTransform(inv_lut)

    cpu = config.getProcessor(g_roundtrip).getDefaultCPUProcessor()

    ap0_to_ap1, log_enc = get_acescct_encode_ops()
    g_to_cct = ocio.GroupTransform()
    g_to_cct.appendTransform(ap0_to_ap1)
    g_to_cct.appendTransform(log_enc)
    cpu_to_cct = config.getProcessor(g_to_cct).getDefaultCPUProcessor()

    log_dec, ap1_to_ap0 = get_acescct_decode_ops()
    g_from_cct = ocio.GroupTransform()
    g_from_cct.appendTransform(log_dec)
    g_from_cct.appendTransform(ap1_to_ap0)
    cpu_from_cct = config.getProcessor(g_from_cct).getDefaultCPUProcessor()

    band_errors = []
    for name, lo, hi, n in BANDS:
        vals = np.linspace(lo, hi, n, dtype=np.float32)
        pixels = np.stack([vals, vals, vals], axis=1)

        cpu_to_cct.apply(ocio.PackedImageDesc(pixels.ravel(), len(pixels), 1, 3))
        orig_cct = pixels.copy()

        cpu.apply(ocio.PackedImageDesc(pixels.ravel(), len(pixels), 1, 3))

        err_cct = np.abs(pixels.ravel().reshape(-1, 3) - orig_cct)

        result = pixels.copy()
        cpu_from_cct.apply(ocio.PackedImageDesc(result.ravel(), len(result), 1, 3))
        orig_lin = np.linspace(lo, hi, n, dtype=np.float32)
        orig_lin_3 = np.stack([orig_lin, orig_lin, orig_lin], axis=1)
        err_lin = np.abs(result.ravel().reshape(-1, 3) - orig_lin_3)

        max_lin = float(np.max(err_lin))
        band_errors.append((name, max_lin * 100.0, max_lin))

    return band_errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark shapers in display-shaper pipeline")
    ap.add_argument("--inv-lut-size", type=int, default=97, help="Inverse 3D LUT grid size")
    ap.add_argument("--fwd-lut-size", type=int, default=65, help="Forward 3D LUT grid size")
    ap.add_argument("--csv", default=None, help="Save results to CSV")
    args = ap.parse_args()

    config = ocio.Config.CreateFromBuiltinConfig(BUILTIN_BAKE_CONFIG)

    shapers = ["gamma22", "pq", "acescct", "acescc", "extended-log", "camera-log", "jplog2"]
    vts = [
        (VT_SDR, "SDR"),
        (VT_HDR, "HDR"),
    ]

    csv_rows: list[list[str]] = []

    for vt_name, vt_type in vts:
        print(f"\n{'='*80}")
        print(f"View Transform: {vt_name} ({vt_type})")
        print(f"{'='*80}")

        for shaper_name in shapers:
            enc_ops, dec_ops, label = _make_shaper_ops(shaper_name, config)

            try:
                domain_min, domain_max = _probe_shaper_range(
                    config, vt_name, enc_ops,
                    grid_res=max(args.fwd_lut_size, args.inv_lut_size),
                )
            except Exception as e:
                print(f"\n  {shaper_name:16} ({label}): PROBE FAILED - {e}")
                continue

            print(f"\n  {shaper_name:16} ({label})")
            print(f"  Domain: [{domain_min:.6f}, {domain_max:.6f}]")

            with tempfile.TemporaryDirectory() as tmpdir:
                fwd_cube = os.path.join(tmpdir, "fwd.cube")
                inv_cube = os.path.join(tmpdir, "inv.cube")

                try:
                    _bake_cube(
                        config, vt_name, enc_ops, dec_ops,
                        fwd_cube, args.fwd_lut_size, domain_min, domain_max,
                        forward=True,
                    )
                    _bake_cube(
                        config, vt_name, enc_ops, dec_ops,
                        inv_cube, args.inv_lut_size, domain_min, domain_max,
                        forward=False,
                    )
                except Exception as e:
                    print(f"    BAKE FAILED: {e}")
                    continue

                try:
                    band_errors = _roundtrip_via_baked_cubes(
                        config, vt_name, enc_ops, dec_ops,
                        domain_min, domain_max,
                        fwd_cube, inv_cube, args.inv_lut_size,
                    )
                except Exception as e:
                    print(f"    ROUNDTRIP FAILED: {e}")
                    continue

            print(f"  {'Band':<28} {'Max CV':>10} {'Max linear':>14}")
            print(f"  {'-'*54}")
            for bname, cv_err, lin_err in band_errors:
                print(f"  {bname:<28} {cv_err:>10.4f} {lin_err:>14.8f}")
                csv_rows.append([
                    shaper_name, label, vt_name, vt_type,
                    bname, f"{cv_err:.6f}", f"{lin_err:.10f}",
                    str(args.inv_lut_size),
                    f"{domain_min:.6f}", f"{domain_max:.6f}",
                ])

            upper_cv = next((cv for (n, cv, _) in band_errors if "Upper (0.1-0.5)" in n), None)
            bright_cv = next((cv for (n, cv, _) in band_errors if "Bright (0.5-1)" in n), None)
            if upper_cv is not None:
                print(f"  >> Upper (0.1-0.5): {upper_cv:.4f} CV | Bright (0.5-1): {bright_cv:.4f} CV")

    if args.csv:
        os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "Shaper", "Label", "ViewTransform", "Type",
                "Band", "Max CV", "Max Linear",
                "Grid Size", "Domain Min", "Domain Max",
            ])
            w.writerows(csv_rows)
        print(f"\nResults saved to {args.csv}")

    print("\n\nSummary — Upper (0.1-0.5) band Max CV:")
    print(f"  {'Shaper':<16} {'SDR':>10} {'HDR':>10}")
    print(f"  {'-'*38}")
    for shaper_name in shapers:
        sdr_cv = next(
            (cv for row in csv_rows
             if row[0] == shaper_name and row[3] == "SDR" and "Upper (0.1-0.5)" in row[4]
             for cv in [float(row[5])]),
            None,
        )
        hdr_cv = next(
            (cv for row in csv_rows
             if row[0] == shaper_name and row[3] == "HDR" and "Upper (0.1-0.5)" in row[4]
             for cv in [float(row[5])]),
            None,
        )
        sdr_s = f"{sdr_cv:.4f}" if sdr_cv is not None else "N/A"
        hdr_s = f"{hdr_cv:.4f}" if hdr_cv is not None else "N/A"
        print(f"  {shaper_name:<16} {sdr_s:>10} {hdr_s:>10}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
