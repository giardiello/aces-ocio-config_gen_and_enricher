#!/usr/bin/env python3
"""
Canonical **built-in** display I/O as explicit OCIO groups (no Display colorspace shortcuts).

- **Forward:** ACEScct → ACES2065-1 → Display+View (forward)
- **Inverse:** Display+View (inverse) → ACES2065-1 → ACEScct

Use these when comparing LUT/CLF paths to “what OCIO built-in display processing does.”
"""

from __future__ import annotations

import PyOpenColorIO as ocio


def group_forward_acescct_to_display_view(display: str, view: str) -> ocio.GroupTransform:
    """ACEScct → scene (AP0) → display linear for this display+view."""
    g = ocio.GroupTransform()
    g.appendTransform(ocio.ColorSpaceTransform("ACEScct", "ACES2065-1"))
    g.appendTransform(
        ocio.DisplayViewTransform(
            src="ACES2065-1",
            display=display,
            view=view,
            direction=ocio.TRANSFORM_DIR_FORWARD,
        )
    )
    return g


def group_inverse_display_view_to_acescct(display: str, view: str) -> ocio.GroupTransform:
    """Display linear (this view’s output) → ACES2065-1 → ACEScct."""
    g = ocio.GroupTransform()
    g.appendTransform(
        ocio.DisplayViewTransform(
            src="ACES2065-1",
            display=display,
            view=view,
            direction=ocio.TRANSFORM_DIR_INVERSE,
        )
    )
    g.appendTransform(ocio.ColorSpaceTransform("ACES2065-1", "ACEScct"))
    return g
