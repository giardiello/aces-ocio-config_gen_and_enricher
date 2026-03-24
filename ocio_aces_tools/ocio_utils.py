"""Shared OCIO config and transform ID utilities."""
import re


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
