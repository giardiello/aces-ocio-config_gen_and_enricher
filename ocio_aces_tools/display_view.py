"""Display+View parsing and output transform URN helpers."""
from collections import OrderedDict

from ocio_aces_tools.constants import OUTPUT_TRANSFORM_TYPES
from ocio_aces_tools.ocio_utils import get_transform_ids


def is_output_transform_urn(urn):
    """
    Check if a URN is an output transform type (ODT, RRTODT, Output, etc.).
    """
    for transform_type in OUTPUT_TRANSFORM_TYPES:
        if f':{transform_type}.' in urn or urn.startswith(f'{transform_type}.'):
            return True
    return False


def get_transform_type_from_urn(urn):
    """
    Extract the transform type from a URN.
    """
    for transform_type in OUTPUT_TRANSFORM_TYPES:
        if f':{transform_type}.' in urn or urn.startswith(f'{transform_type}.'):
            return transform_type
    return None


def parse_display_view_structure(config):
    """
    Parse the OCIO config to extract all Display+View combinations and their
    associated view transforms and display colorspaces.

    Returns a structure mapping (display, view) to view_transform,
    display_colorspace, view_transform_urns, display_colorspace_urns, all_urns.
    """
    display_view_map = OrderedDict()

    # Build a map of view transform names to their URNs
    view_transform_urns = {}
    for vt in config.getViewTransforms():
        vt_name = vt.getName()
        vt_urns = get_transform_ids(vt)
        view_transform_urns[vt_name] = vt_urns

    # Build a map of colorspace names to their URNs (for display colorspaces)
    colorspace_urns = {}
    for cs in config.getColorSpaces():
        cs_name = cs.getName()
        cs_urns = get_transform_ids(cs)
        colorspace_urns[cs_name] = cs_urns

    # Iterate through all displays
    for display_name in config.getDisplays():
        views = config.getViews(display_name)

        for view_name in views:
            try:
                view_transform_name = config.getDisplayViewTransformName(display_name, view_name)
            except Exception:
                view_transform_name = None

            try:
                display_colorspace_name = config.getDisplayViewColorSpaceName(display_name, view_name)
            except Exception:
                display_colorspace_name = None

            # Handle <USE_DISPLAY_NAME> placeholder
            if display_colorspace_name == '<USE_DISPLAY_NAME>':
                display_colorspace_name = display_name

            # Collect URNs
            vt_urns = view_transform_urns.get(view_transform_name, []) if view_transform_name else []
            dc_urns = colorspace_urns.get(display_colorspace_name, []) if display_colorspace_name else []

            all_urns = list(set(vt_urns + dc_urns))

            display_view_map[(display_name, view_name)] = {
                'view_transform': view_transform_name,
                'display_colorspace': display_colorspace_name,
                'view_transform_urns': vt_urns,
                'display_colorspace_urns': dc_urns,
                'all_urns': all_urns
            }

    return display_view_map
