#!/usr/bin/env python3
"""
Split an OCIO config into ACES version-specific configs.
Filters transform IDs in interchange.amf_transform_ids based on ACES version.
"""

import PyOpenColorIO as OCIO
import sys
import re
from pathlib import Path


def get_aces_version_from_transform_id(transform_id):
    """Extract ACES version from transform ID URN."""
    # Pattern: urn:ampas:aces:transformId:vX.Y:...
    match = re.search(r':transformId:(v[\d.]+):', transform_id)
    if match:
        return match.group(1)
    return None


def filter_transform_ids_by_version(transform_ids_str, target_versions):
    """
    Filter transform IDs to only include specified ACES versions.

    Args:
        transform_ids_str: Newline-separated transform ID string
        target_versions: List of version prefixes to keep (e.g., ['v1.', 'v2.0'])

    Returns:
        Filtered newline-separated string, or None if no IDs match
    """
    if not transform_ids_str:
        return None

    ids = [tid.strip() for tid in transform_ids_str.split('\n') if tid.strip()]
    filtered_ids = []

    for tid in ids:
        version = get_aces_version_from_transform_id(tid)
        if version:
            # Check if version matches any target version prefix
            for target in target_versions:
                if version.startswith(target):
                    filtered_ids.append(tid)
                    break

    if filtered_ids:
        return '\n'.join(filtered_ids)
    return None


def split_config_by_aces_version(input_config_path, output_v1_path, output_v2_path):
    """
    Split OCIO config into ACES 1.x and 2.0 versions.

    Processes all color spaces, filtering their interchange.amf_transform_ids
    to only include version-appropriate IDs.
    """
    print(f"Loading config: {input_config_path}")
    config = OCIO.Config.CreateFromFile(str(input_config_path))

    # ACES version filters
    v1_versions = ['v1.']  # Matches v1.0, v1.0.1, v1.0.3, v1.1, v1.2, v1.3, v1.3.1, v1.5
    v2_versions = ['v2.0']  # Matches v2.0 only

    stats = {
        'v1': {'color_spaces': 0, 'total_ids': 0},
        'v2': {'color_spaces': 0, 'total_ids': 0},
        'both': 0,
        'neither': 0
    }

    # We'll load the config twice for modification
    config_v1 = OCIO.Config.CreateFromFile(str(input_config_path))
    config_v2 = OCIO.Config.CreateFromFile(str(input_config_path))

    print("\nProcessing color spaces...")

    # Track which color spaces to keep in each config
    color_spaces_to_remove_v1 = []
    color_spaces_to_remove_v2 = []

    # Iterate through all color spaces
    for cs in config.getColorSpaces():
        cs_name = cs.getName()

        # Get current transform IDs
        has_interchange = hasattr(cs, 'getInterchangeAttributes')
        if not has_interchange:
            # No interchange attributes - keep in both
            continue

        attrs = cs.getInterchangeAttributes()
        if not attrs or 'amf_transform_ids' not in attrs:
            # No transform IDs - keep in both
            continue

        original_ids = attrs['amf_transform_ids']

        # Filter for each version
        v1_ids = filter_transform_ids_by_version(original_ids, v1_versions)
        v2_ids = filter_transform_ids_by_version(original_ids, v2_versions)

        # Update stats and prepare modifications
        if v1_ids and v2_ids:
            stats['both'] += 1
            # Update both configs with filtered IDs
            cs_v1 = config_v1.getColorSpace(cs_name)
            cs_v1.setInterchangeAttribute('amf_transform_ids', v1_ids)
            stats['v1']['total_ids'] += len(v1_ids.split('\n'))

            cs_v2 = config_v2.getColorSpace(cs_name)
            cs_v2.setInterchangeAttribute('amf_transform_ids', v2_ids)
            stats['v2']['total_ids'] += len(v2_ids.split('\n'))

            stats['v1']['color_spaces'] += 1
            stats['v2']['color_spaces'] += 1
            print(f"  {cs_name}: Both versions (v1: {len(v1_ids.split())} IDs, v2: {len(v2_ids.split())} IDs)")

        elif v1_ids:
            stats['v1']['color_spaces'] += 1
            stats['v1']['total_ids'] += len(v1_ids.split('\n'))
            # Keep in v1, remove from v2
            color_spaces_to_remove_v2.append(cs_name)
            cs_v1 = config_v1.getColorSpace(cs_name)
            cs_v1.setInterchangeAttribute('amf_transform_ids', v1_ids)
            print(f"  {cs_name}: ACES 1.x only ({len(v1_ids.split())} IDs)")

        elif v2_ids:
            stats['v2']['color_spaces'] += 1
            stats['v2']['total_ids'] += len(v2_ids.split('\n'))
            # Keep in v2, remove from v1
            color_spaces_to_remove_v1.append(cs_name)
            cs_v2 = config_v2.getColorSpace(cs_name)
            cs_v2.setInterchangeAttribute('amf_transform_ids', v2_ids)
            print(f"  {cs_name}: ACES 2.0 only ({len(v2_ids.split())} IDs)")

        else:
            stats['neither'] += 1
            # No version-specific IDs - keep in both

    # Remove version-inappropriate color spaces
    print(f"\nRemoving {len(color_spaces_to_remove_v1)} color spaces from ACES 1.x config...")
    for cs_name in color_spaces_to_remove_v1:
        try:
            config_v1.removeColorSpace(cs_name)
        except Exception as e:
            print(f"  Warning: Could not remove {cs_name} from v1: {e}")

    print(f"Removing {len(color_spaces_to_remove_v2)} color spaces from ACES 2.0 config...")
    for cs_name in color_spaces_to_remove_v2:
        try:
            config_v2.removeColorSpace(cs_name)
        except Exception as e:
            print(f"  Warning: Could not remove {cs_name} from v2: {e}")

    # Write output files
    print(f"\nWriting ACES 1.x config to: {output_v1_path}")
    with open(output_v1_path, 'w') as f:
        f.write(config_v1.serialize())

    print(f"Writing ACES 2.0 config to: {output_v2_path}")
    with open(output_v2_path, 'w') as f:
        f.write(config_v2.serialize())

    # Print summary
    print("\n" + "="*80)
    print("SPLIT COMPLETE")
    print("="*80)
    print(f"\nACES 1.x Config ({output_v1_path}):")
    print(f"  Color spaces: {stats['v1']['color_spaces']}")
    print(f"  Transform IDs: {stats['v1']['total_ids']}")

    print(f"\nACES 2.0 Config ({output_v2_path}):")
    print(f"  Color spaces: {stats['v2']['color_spaces']}")
    print(f"  Transform IDs: {stats['v2']['total_ids']}")

    print(f"\nShared across both: {stats['both']} color spaces")
    print(f"No version-specific IDs: {stats['neither']} color spaces (kept in both)")


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.argv = ["ocio_aces_tool", "split"] + sys.argv[1:]
    from ocio_aces_tools.cli import main as cli_main
    sys.exit(cli_main())
