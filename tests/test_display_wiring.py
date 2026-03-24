from pathlib import Path
import PyOpenColorIO as OCIO

from ocio_vendor_extensions.display_wiring import (
    wire_views_to_displays,
    get_existing_displays,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestGetExistingDisplays:
    def test_returns_display_names(self):
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        displays = get_existing_displays(config)
        assert "sRGB - Display" in displays


class TestWireViewsToDisplays:
    def test_wires_view_to_existing_display(self):
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        cs = OCIO.ColorSpace(name="Test View")
        cs.setFamily("Test/display_referred")
        config.addColorSpace(cs)
        mappings = {"Test View": ["sRGB - Display"]}
        wired, missing = wire_views_to_displays(
            config, mappings, missing_policy="skip"
        )
        assert ("sRGB - Display", "Test View") in wired
        views = list(config.getViews("sRGB - Display"))
        assert "Test View" in views

    def test_skip_missing_display(self):
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        mappings = {"Test View": ["NonExistent - Display"]}
        wired, missing = wire_views_to_displays(
            config, mappings, missing_policy="skip"
        )
        assert len(wired) == 0
        assert "NonExistent - Display" in missing

    def test_create_missing_display(self):
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        cs = OCIO.ColorSpace(name="Test View")
        cs.setFamily("Test/display_referred")
        config.addColorSpace(cs)
        mappings = {"Test View": ["NewDisplay - Display"]}
        wired, missing = wire_views_to_displays(
            config, mappings, missing_policy="create"
        )
        assert ("NewDisplay - Display", "Test View") in wired
        assert "NewDisplay - Display" in list(config.getDisplays())

    def test_skips_duplicate_view(self):
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        mappings = {"Raw": ["sRGB - Display"]}
        wired, missing = wire_views_to_displays(
            config, mappings, missing_policy="skip"
        )
        assert len(wired) == 0


class TestReorderViews:
    def test_vendor_views_before_aces(self):
        from ocio_vendor_extensions.display_wiring import reorder_views_for_display
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        cs_aces = OCIO.ColorSpace(name="ACES View")
        config.addColorSpace(cs_aces)
        cs_vendor = OCIO.ColorSpace(name="Vendor View")
        config.addColorSpace(cs_vendor)
        config.addDisplayView("sRGB - Display", "ACES View", "ACES View", "")
        config.addDisplayView("sRGB - Display", "Vendor View", "Vendor View", "")
        # Before reorder: Raw, ACES View, Vendor View
        reorder_views_for_display(config, "sRGB - Display", ["Vendor View"])
        views = list(config.getViews("sRGB - Display"))
        assert views.index("Vendor View") < views.index("ACES View")
        assert views[0] == "Raw"
