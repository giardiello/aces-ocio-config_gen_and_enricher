"""Minimal tests for display_view module."""
import os

import pytest

# Optional: use existing OCIO config under INPUT_OCIO if present
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURE_CONFIG = os.path.join(
    REPO_ROOT, "INPUT_OCIO", "STUDIO", "studio-config-v3.0.0_aces-v2.0_ocio-v2.4.ocio"
)


def test_parse_display_view_structure_returns_dict_with_expected_keys():
    """parse_display_view_structure(config) returns a dict with (display, view) keys and expected value keys."""
    from ocio_aces_tools.display_view import parse_display_view_structure

    try:
        import PyOpenColorIO as OCIO
    except ImportError:
        pytest.skip("PyOpenColorIO not installed")

    if not os.path.isfile(FIXTURE_CONFIG):
        pytest.skip(f"Fixture config not found: {FIXTURE_CONFIG}")

    config = OCIO.Config.CreateFromFile(FIXTURE_CONFIG)
    result = parse_display_view_structure(config)

    assert isinstance(result, dict)
    assert len(result) >= 1, "at least one (display, view) entry"
    for key, info in result.items():
        display, view = key
        assert isinstance(display, str)
        assert isinstance(view, str)
        assert "view_transform" in info
        assert "display_colorspace" in info
        assert "view_transform_urns" in info
        assert "display_colorspace_urns" in info
        assert "all_urns" in info
