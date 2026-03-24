#!/usr/bin/env python3
"""Test whether LogCameraTransform can represent FilmLight T-Log within tolerance.

Per docs/superpowers/specs/2026-03-23-clf-migration-design.md §3.2: compare
LogCameraTransform vs colour-science reference. Threshold: max error < 1e-5
in CODE VALUE space (not scene-linear, which is affected by float32 precision
at large values).

Requires: pip install colour-science opencolorio numpy
"""
from __future__ import annotations

import math
import sys

import numpy as np

try:
    from colour.models import log_encoding_FilmLightTLog as _log_enc
    from colour.models import log_decoding_FilmLightTLog as _log_dec
except ImportError:
    try:
        from colour.models import log_encoding_TLog as _log_enc  # type: ignore[attr-defined]
        from colour.models import log_decoding_TLog as _log_dec  # type: ignore[attr-defined]
    except ImportError:
        try:
            from colour import log_encoding_TLog as _log_enc  # type: ignore[attr-defined]
            from colour import log_decoding_TLog as _log_dec  # type: ignore[attr-defined]
        except ImportError:
            print(
                "ERROR: colour-science T-Log not found. pip install colour-science.",
                file=sys.stderr,
            )
            sys.exit(1)


def ref_encode(L: float) -> float:
    return float(_log_enc(L))


def ref_decode(V: float) -> float:
    return float(_log_dec(V))


def derive_tlog_constants(
    w: float = 128.0, g: float = 16.0, o: float = 0.075
) -> dict[str, float]:
    """Derive LogCameraTransform parameters from T-Log constants."""
    b = 1.0 / (0.7107 + 1.2359 * math.log(w * g))
    gs = g / (1.0 - o)
    c = b / gs
    a = 1.0 - b * math.log(w + c)
    y0 = a + b * math.log(c)
    s = (1.0 - o) / (1.0 - y0)
    big_a = 1.0 + (a - 1.0) * s
    big_b = b * s
    big_g = gs * s
    return {"A": big_a, "B": big_b, "C": c, "G": big_g, "o": o}


def main() -> int:
    const = derive_tlog_constants()
    A, B, C, G, o = const["A"], const["B"], const["C"], const["G"], const["o"]

    lct_params = {
        "base": math.e,
        "log_side_slope": B,
        "log_side_offset": A,
        "lin_side_slope": 1.0,
        "lin_side_offset": C,
        "lin_side_break": 0.0,
        "linear_slope": G,
    }

    print("LogCameraTransform parameters:")
    for k, v in lct_params.items():
        print(f"  {k}: {v!r}")

    # Verify continuity at break point
    log_at_zero = A + B * math.log(C)
    print(f"\nContinuity check at L=0: log branch={log_at_zero:.15f}, linear branch={o}")
    print(f"  Continuity error: {abs(log_at_zero - o):.2e}")

    # Verify hand-derived encode matches colour-science
    test_linear = np.linspace(-0.01, 10.0, 10_000)
    hand_enc = np.array([A + B * math.log(L + C) if L >= 0 else G * L + o for L in test_linear])
    cs_enc = np.array([ref_encode(float(L)) for L in test_linear])
    hand_vs_cs = float(np.max(np.abs(hand_enc - cs_enc)))
    print(f"\nHand-derived vs colour-science encode: {hand_vs_cs:.2e}")

    try:
        import PyOpenColorIO as OCIO
    except ImportError:
        print("\nPyOpenColorIO not available.")
        return 1

    config = OCIO.Config.CreateRaw()

    lct_fwd = OCIO.LogCameraTransform(
        base=lct_params["base"],
        logSideSlope=[B] * 3,
        logSideOffset=[A] * 3,
        linSideSlope=[1.0] * 3,
        linSideOffset=[C] * 3,
        linSideBreak=[0.0] * 3,
        linearSlope=[G] * 3,
    )
    lct_inv = OCIO.LogCameraTransform(
        base=lct_params["base"],
        logSideSlope=[B] * 3,
        logSideOffset=[A] * 3,
        linSideSlope=[1.0] * 3,
        linSideOffset=[C] * 3,
        linSideBreak=[0.0] * 3,
        linearSlope=[G] * 3,
        direction=OCIO.TRANSFORM_DIR_INVERSE,
    )
    cpu_enc = config.getProcessor(lct_fwd).getDefaultCPUProcessor()
    cpu_dec = config.getProcessor(lct_inv).getDefaultCPUProcessor()

    # Test 1: Encode in code value space (scene-linear → code value)
    max_enc_err = 0.0
    for L in test_linear:
        ref_V = ref_encode(float(L))
        ocio_V = cpu_enc.applyRGB([float(L)] * 3)[0]
        max_enc_err = max(max_enc_err, abs(ref_V - ocio_V))

    # Test 2: Decode — compare in code value space (re-encode decoded value)
    test_codes = np.linspace(0.0, 1.0, 10_000)
    max_dec_err_cv = 0.0
    for V in test_codes:
        ref_L = ref_decode(float(V))
        ocio_L = cpu_dec.applyRGB([float(V)] * 3)[0]
        ref_V_back = ref_encode(ref_L)
        ocio_V_back = ref_encode(float(ocio_L))
        max_dec_err_cv = max(max_dec_err_cv, abs(ref_V_back - ocio_V_back))

    # Test 3: OCIO round-trip (encode → decode)
    max_rt_err = 0.0
    for L in test_linear:
        encoded = cpu_enc.applyRGB([float(L)] * 3)
        decoded = cpu_dec.applyRGB(list(encoded))
        max_rt_err = max(max_rt_err, abs(float(L) - decoded[0]))

    print(f"\nOCIO LogCameraTransform vs colour-science T-Log:")
    print(f"  Encode error (code value space):            {max_enc_err:.2e}")
    print(f"  Decode error (re-encoded to code values):   {max_dec_err_cv:.2e}")
    print(f"  OCIO round-trip error (scene-linear):       {max_rt_err:.2e}")

    threshold = 1e-5
    ok = max_enc_err < threshold and max_dec_err_cv < threshold
    print(f"\nThreshold: {threshold:g} (code value space)")
    if ok:
        print(f"PASS: LogCameraTransform is analytically correct for T-Log.")
        print(f"      (Round-trip error {max_rt_err:.2e} is float32 precision, not formula error)")
        print(f"\nYAML for to_scene_reference (T-Log decode + E-Gamut 2 → ACES matrix):")
        print(f"  - !<LogCameraTransform> {{base: {math.e}, "
              f"log_side_slope: {B}, log_side_offset: {A}, "
              f"lin_side_slope: 1.0, lin_side_offset: {C}, "
              f"lin_side_break: 0.0, linear_slope: {G}, "
              f"direction: inverse}}")
        return 0

    print(f"FAIL: LogCameraTransform fit exceeds {threshold:g}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
