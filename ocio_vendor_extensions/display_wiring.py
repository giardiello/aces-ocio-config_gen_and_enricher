"""Wire vendor views to OCIO config displays."""
import sys

import PyOpenColorIO as OCIO


def get_existing_displays(config) -> set[str]:
    """Return set of display names in the config."""
    return set(config.getDisplaysAll())


def _display_defined_views(config, display_name: str) -> list[str]:
    """All display-defined views (not filtered by active_views)."""
    return list(config.getViews(OCIO.VIEW_DISPLAY_DEFINED, display_name))


def wire_views_to_displays(
    config,
    display_mappings: dict[str, list[str]],
    missing_policy: str = "skip",
) -> tuple[list[tuple[str, str]], set[str]]:
    """Wire vendor view color spaces to displays.

    Args:
        config: PyOpenColorIO Config object (mutated in place)
        display_mappings: {colorspace_name: [display_name, ...]}
        missing_policy: "skip", "create", or "prompt"

    Returns:
        (wired, missing_displays) where wired is list of (display, view) tuples
        and missing_displays is set of display names that were not found.
    """
    existing_displays = get_existing_displays(config)
    wired: list[tuple[str, str]] = []
    missing_displays: set[str] = set()

    for cs_name, target_displays in display_mappings.items():
        for display_name in target_displays:
            if display_name not in existing_displays:
                if missing_policy == "skip":
                    missing_displays.add(display_name)
                    continue
                elif missing_policy == "create":
                    _create_display(config, display_name)
                    existing_displays.add(display_name)
                elif missing_policy == "prompt":
                    if _prompt_create_display(display_name, cs_name):
                        _create_display(config, display_name)
                        existing_displays.add(display_name)
                    else:
                        missing_displays.add(display_name)
                        continue

            existing_views = set(_display_defined_views(config, display_name))
            if cs_name in existing_views:
                continue

            config.addDisplayView(display_name, cs_name, cs_name, "")
            update_active_views(config, [cs_name])
            wired.append((display_name, cs_name))

    return wired, missing_displays


def reorder_views_for_display(config, display_name: str, vendor_views: list[str]) -> None:
    """Reorder views so vendor views appear before shared ACES views.

    PyOpenColorIO's addDisplayView always appends. To place vendor views
    before shared ACES views (but after Raw), we snapshot all view metadata,
    remove all views, then re-add in desired order.
    """
    views = _display_defined_views(config, display_name)
    vendor_set = set(vendor_views)
    raw_views = [v for v in views if v == "Raw"]
    vendor_ordered = [v for v in views if v in vendor_set]
    aces_views = [v for v in views if v not in vendor_set and v != "Raw"]
    desired = raw_views + vendor_ordered + aces_views
    if desired == views:
        return
    # Snapshot view metadata BEFORE removal
    snapshots: dict[str, tuple[str, str]] = {}
    for v in views:
        cs = config.getDisplayViewColorSpaceName(display_name, v)
        looks = ""
        try:
            looks = config.getDisplayViewLooks(display_name, v)
        except Exception:
            pass
        snapshots[v] = (cs if cs else v, looks if looks else "")
    # Remove all views
    for v in views:
        config.removeDisplayView(display_name, v)
    # Re-add in desired order using snapshotted metadata
    for v in desired:
        cs, looks = snapshots[v]
        config.addDisplayView(display_name, v, cs, looks)
    update_active_views(config, [v for v in desired if v != "Raw"])


def update_active_views(config, new_view_names: list[str]) -> None:
    """Add new view names to active_views if the config already has an active list."""
    try:
        current = config.getActiveViews()
        if current:
            current_set = {v.strip() for v in current.split(",")} if isinstance(current, str) else set(current)
            for name in new_view_names:
                if name not in current_set:
                    config.addActiveView(name)
    except Exception:
        pass


def _create_display(config, display_name: str) -> None:
    """Create a new display with a Raw view.

    Uses CIE XYZ-D65 - Display-referred as the display colorspace
    if it exists in the config (per spec), otherwise falls back to Raw.
    """
    display_cs = "CIE XYZ-D65 - Display-referred"
    if config.getColorSpace(display_cs) is None:
        display_cs = "Raw"
    config.addDisplayView(display_name, "Raw", display_cs, "")
    config.addActiveDisplay(display_name)


def _prompt_create_display(display_name: str, cs_name: str) -> bool:
    """Prompt user whether to create a missing display. Returns True if yes."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(
            f"Display '{display_name}' not found (needed by '{cs_name}'). "
            "Use --create-missing-displays or --skip-missing-displays.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    answer = input(
        f"Display '{display_name}' not found. Create it? [y/N] "
    ).strip().lower()
    return answer in ("y", "yes")
