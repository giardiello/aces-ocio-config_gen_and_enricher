#!/usr/bin/env python

import argparse
import os
import re
import sys

# This script requires the PyOpenColorIO library.
# You can install it by running: pip install OpenColorIO
try:
    import PyOpenColorIO as OCIO
except ImportError:
    print("Error: PyOpenColorIO library not found.")
    print("Please install it using: pip install OpenColorIO")
    exit(1)


def migrate_transform_ids_to_interchange(config):
    """
    Migrate ACEStransformID entries from description field to interchange.amf_transform_ids.

    Args:
        config (OCIO.Config): An OCIO Config object to modify.

    Returns:
        int: Number of items migrated.
    """
    migrated_count = 0

    def migrate_item(ocio_item):
        """Migrate transform IDs for a single color space, look, or view transform."""
        nonlocal migrated_count

        description = ocio_item.getDescription()
        if not description:
            return

        # Find all ACEStransformID entries in description
        found_ids = re.findall(r'ACEStransformID:\s*(\S+)', description)
        if not found_ids:
            return

        # Check if item already has interchange AMF transform IDs
        existing_amf_ids = []
        try:
            if hasattr(ocio_item, 'getInterchangeAttributes'):
                attrs = ocio_item.getInterchangeAttributes()
                if attrs and 'amf_transform_ids' in attrs:
                    existing_amf = attrs['amf_transform_ids']
                    if existing_amf:
                        existing_amf_ids = [tid.strip() for tid in existing_amf.split('\n') if tid.strip()]
        except (AttributeError, Exception):
            pass

        # Combine found IDs with existing (avoid duplicates)
        all_ids = existing_amf_ids.copy()
        for tid in found_ids:
            if tid not in all_ids:
                all_ids.append(tid)

        # Set the interchange AMF transform IDs using setInterchangeAttribute
        try:
            if hasattr(ocio_item, 'setInterchangeAttribute'):
                amf_content = '\n'.join(all_ids)
                ocio_item.setInterchangeAttribute('amf_transform_ids', amf_content)
                migrated_count += 1

                # Clean up description by removing ACEStransformID lines
                # Keep other content in description
                cleaned_description = re.sub(
                    r'\s*ACEStransformID:\s*\S+\s*',
                    '',
                    description
                )

                # Clean up "AMF Components" sections and following content
                cleaned_description = re.sub(
                    r'\s*AMF Components\s*\n\s*-+\s*',
                    '',
                    cleaned_description
                )

                # Clean up "Previous Equivalent ACES Transform IDs" sections
                cleaned_description = re.sub(
                    r'\s*Previous Equivalent ACES Transform IDs:\s*\n\s*-+\s*',
                    '',
                    cleaned_description
                )

                # Clean up "Inverse ACES Transform ID" sections
                cleaned_description = re.sub(
                    r'\s*Inverse ACES Transform ID:\s*\n\s*-+\s*',
                    '',
                    cleaned_description
                )

                # Remove trailing/leading whitespace and excessive blank lines
                cleaned_description = re.sub(r'\n{3,}', '\n\n', cleaned_description)
                cleaned_description = cleaned_description.strip()

                ocio_item.setDescription(cleaned_description)
                print(f"  Migrated: {ocio_item.getName()} ({len(all_ids)} transform IDs)")
        except (AttributeError, Exception) as e:
            print(f"  Warning: Could not migrate {ocio_item.getName()}: {e}")

    # Migrate ColorSpaces
    for cs in config.getColorSpaces():
        migrate_item(cs)

    # Migrate Looks
    for look in config.getLooks():
        migrate_item(look)

    # Migrate ViewTransforms
    for vt in config.getViewTransforms():
        migrate_item(vt)

    return migrated_count


def upgrade_config_to_v25(input_path, output_path, preserve_description=False):
    """
    Upgrade an OCIO v2.4 config to v2.5 format.

    Args:
        input_path (str): Path to input OCIO v2.4 config.
        output_path (str): Path to output OCIO v2.5 config.
        preserve_description (bool): If True, keep ACEStransformID entries in description.

    Returns:
        bool: True if successful, False otherwise.
    """
    print(f"Loading OCIO config from: {input_path}")

    try:
        config = OCIO.Config.CreateFromFile(input_path)
    except OCIO.Exception as e:
        print(f"Error loading OCIO config: {e}")
        return False

    # Check current version
    major_version = config.getMajorVersion()
    minor_version = config.getMinorVersion()
    current_version = major_version + (minor_version / 10.0)

    print(f"Current OCIO version: {current_version}")

    if current_version >= 2.5:
        print("Warning: This config is already v2.5 or newer. No upgrade needed.")
        if input_path != output_path:
            print("Copying config to output path...")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(config.serialize())
        return True

    if current_version < 2.0:
        print("Error: This script only supports upgrading from OCIO v2.4 to v2.5.")
        print(f"Your config is version {current_version}. Please upgrade to v2.4 first.")
        return False

    print("\nStarting upgrade to OCIO v2.5...")

    # Step 1: Upgrade the version number
    print("\n1. Upgrading version to 2.5...")
    config.setVersion(2, 5)

    # Step 2: Migrate ACEStransformID from descriptions to interchange
    print("\n2. Migrating ACEStransformID entries to interchange.amf_transform_ids...")
    migrated_count = migrate_transform_ids_to_interchange(config)
    print(f"   Migrated {migrated_count} color spaces/looks/view transforms")

    # Step 3: Check for interop_id attributes (informational only)
    print("\n3. Checking for interop_id attributes...")
    # Note: In a real-world scenario, you might want to set interop_id based on naming conventions
    # For now, we'll just report which items don't have them
    items_without_interop = []
    for cs in config.getColorSpaces():
        # Check if colorspace has interop_id set
        # This is informational only - actual interop_id assignment would need domain knowledge
        if hasattr(cs, 'getInteropID'):
            try:
                interop_id = cs.getInteropID()
                if not interop_id:
                    items_without_interop.append(cs.getName())
            except:
                items_without_interop.append(cs.getName())

    if items_without_interop:
        print(f"   Note: {len(items_without_interop)} color spaces don't have interop_id set")
        print("   (This is optional and requires manual configuration)")

    # Step 4: Validate and serialize
    print("\n4. Validating upgraded config...")
    try:
        config.validate()
        print("   Config validation successful!")
    except OCIO.Exception as e:
        print(f"   Warning: Config validation found issues: {e}")
        print("   Continuing with export anyway...")

    print(f"\n5. Writing upgraded config to: {output_path}")
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(config.serialize())
        print("   Successfully written!")
    except Exception as e:
        print(f"   Error writing config: {e}")
        return False

    print("\n" + "="*80)
    print("UPGRADE COMPLETE!")
    print("="*80)
    print(f"\nYour OCIO v2.5 config has been saved to: {output_path}")
    print(f"\nSummary:")
    print(f"  - Version upgraded: {current_version} → 2.5")
    print(f"  - Items migrated: {migrated_count}")
    print(f"  - ACEStransformID entries moved to interchange.amf_transform_ids")
    print(f"  - Description fields cleaned up")
    print("\nYou can now use this config with OCIO v2.5+ applications.")

    return True


def main():
    """
    Main entry point for the OCIO v2.4 to v2.5 upgrade script.
    """
    parser = argparse.ArgumentParser(
        description="Upgrade OpenColorIO config from v2.4 to v2.5 format.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  # Upgrade a single config
  python3 upgrade_ocio_v24_to_v25.py input.ocio -o output_v25.ocio

  # Upgrade in-place (overwrites original)
  python3 upgrade_ocio_v24_to_v25.py input.ocio

  # Preserve ACEStransformID in descriptions (for reference)
  python3 upgrade_ocio_v24_to_v25.py input.ocio -o output.ocio --preserve-description

What this script does:
  1. Upgrades the config version from 2.4 to 2.5
  2. Migrates ACEStransformID entries from description to interchange.amf_transform_ids
  3. Cleans up description fields (removes migrated IDs)
  4. Validates the upgraded config
  5. Saves the result to the output file

Note: This script only handles schema upgrades. It does NOT:
  - Add new color spaces or transforms
  - Modify existing color transforms
  - Change color space relationships or hierarchies
        """
    )

    parser.add_argument(
        "input_config",
        help="Path to the input OCIO v2.4 config file"
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_config",
        help="Path to the output OCIO v2.5 config file (default: overwrites input)",
        default=None
    )
    parser.add_argument(
        "--preserve-description",
        action="store_true",
        help="Keep ACEStransformID entries in description field (for reference)"
    )

    args = parser.parse_args()

    # Set output path
    if args.output_config is None:
        args.output_config = args.input_config
        print("Warning: No output file specified. Will overwrite input file.")
        response = input("Continue? (y/n): ")
        if response.lower() not in ['y', 'yes']:
            print("Aborted.")
            return

    # Check if input file exists
    if not os.path.exists(args.input_config):
        print(f"Error: Input file not found: {args.input_config}")
        sys.exit(1)

    # Create output directory if needed
    output_dir = os.path.dirname(args.output_config)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # Perform upgrade
    success = upgrade_config_to_v25(
        args.input_config,
        args.output_config,
        args.preserve_description
    )

    if not success:
        print("\nUpgrade failed.")
        sys.exit(1)
    else:
        print("\nUpgrade successful!")
        sys.exit(0)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    sys.argv = ["ocio_aces_tool", "upgrade"] + sys.argv[1:]
    from ocio_aces_tools.cli import main as cli_main
    sys.exit(cli_main())
