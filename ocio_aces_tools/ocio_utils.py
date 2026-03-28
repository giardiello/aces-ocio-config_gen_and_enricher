"""Shared OCIO config and transform ID utilities."""
import re

try:
    import PyOpenColorIO as OCIO
    _HAS_OCIO = True
except ImportError:
    _HAS_OCIO = False


def get_transform_ids(ocio_item):
    """
    Extract all transform IDs from an OCIO item (ColorSpace, Look, ViewTransform).
    Supports both OCIO v2.5+ interchange and v2.4 description formats.
    """
    found_ids = []
    try:
        if hasattr(ocio_item, 'getInterchangeAttributes'):
            attrs = ocio_item.getInterchangeAttributes()
            if attrs and attrs.get('amf_transform_ids'):
                amf_ids = attrs['amf_transform_ids']
                found_ids.extend([tid.strip() for tid in amf_ids.split('\n') if tid.strip()])
    except (AttributeError, Exception):
        pass
    try:
        desc = ocio_item.getDescription()
        if desc:
            found_ids.extend(re.findall(r'ACEStransformID:\s*(\S+)', desc))
    except (AttributeError, Exception):
        pass
    seen = set()
    return [tid for tid in found_ids if tid not in seen and not seen.add(tid)]


def _collect_builtin_styles(transform):
    """Recursively collect BuiltinTransform styles from a transform tree."""
    if not _HAS_OCIO:
        return []
    styles = []
    if isinstance(transform, OCIO.BuiltinTransform):
        styles.append(transform.getStyle())
    elif isinstance(transform, OCIO.GroupTransform):
        for i in range(transform.getNumTransforms()):
            styles.extend(_collect_builtin_styles(transform.getTransform(i)))
    return styles


def get_builtin_styles(ocio_item):
    """
    Extract BuiltinTransform style strings from an OCIO item's transforms.

    Handles ColorSpace (ColorSpaceDirection), ViewTransform
    (ViewTransformDirection), and Look (TransformDirection).

    Returns:
        list[str]: BuiltinTransform style strings found (deduplicated).
    """
    if not _HAS_OCIO:
        return []
    styles = []

    if isinstance(ocio_item, OCIO.ColorSpace):
        for direction in (OCIO.COLORSPACE_DIR_TO_REFERENCE,
                          OCIO.COLORSPACE_DIR_FROM_REFERENCE):
            try:
                t = ocio_item.getTransform(direction)
                if t:
                    styles.extend(_collect_builtin_styles(t))
            except Exception:
                pass
    elif isinstance(ocio_item, OCIO.ViewTransform):
        for direction in (OCIO.VIEWTRANSFORM_DIR_TO_REFERENCE,
                          OCIO.VIEWTRANSFORM_DIR_FROM_REFERENCE):
            try:
                t = ocio_item.getTransform(direction)
                if t:
                    styles.extend(_collect_builtin_styles(t))
            except Exception:
                pass
    elif isinstance(ocio_item, OCIO.Look):
        for direction in (OCIO.TRANSFORM_DIR_FORWARD,
                          OCIO.TRANSFORM_DIR_INVERSE):
            try:
                t = ocio_item.getTransform(direction)
                if t:
                    styles.extend(_collect_builtin_styles(t))
            except Exception:
                pass

    seen = set()
    return [s for s in styles if s not in seen and not seen.add(s)]


def build_builtin_style_urn_map(config):
    """
    Build a mapping from BuiltinTransform style to the set of URNs found
    on all OCIO items that use that style.

    This enables cross-version URN correlation: if two color spaces (one from
    ACES 1.3, one from ACES 2.0) share the same BuiltinTransform style, their
    URNs can be merged even when transforms.json lacks equivalence links.

    Args:
        config: OCIO.Config object

    Returns:
        dict[str, set[str]]: {builtin_style: {urn1, urn2, ...}}
    """
    style_to_urns = {}
    for cs in config.getColorSpaces():
        styles = get_builtin_styles(cs)
        urns = get_transform_ids(cs)
        for style in styles:
            if style not in style_to_urns:
                style_to_urns[style] = set()
            style_to_urns[style].update(urns)
    for look in config.getLooks():
        styles = get_builtin_styles(look)
        urns = get_transform_ids(look)
        for style in styles:
            if style not in style_to_urns:
                style_to_urns[style] = set()
            style_to_urns[style].update(urns)
    for vt in config.getViewTransforms():
        styles = get_builtin_styles(vt)
        urns = get_transform_ids(vt)
        for style in styles:
            if style not in style_to_urns:
                style_to_urns[style] = set()
            style_to_urns[style].update(urns)
    return style_to_urns
