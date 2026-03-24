#!/usr/bin/env python3
"""
Validate AMF Output Transform URN to Display+View Mappings.

This script validates that every ACES output transform URN in an OCIO config
maps to exactly ONE Display+View combination. This is critical for AMF importers
that need to select the correct display rendering based on the transform ID.

The validation checks:
1. Each output transform URN maps to exactly ONE Display+View combination
2. No conflicting URNs exist (same URN leading to multiple Display+View combos)
3. Reports which output transform URNs from transforms.json are missing

Usage:
    python3 validate_amf_output_transforms.py <ocio_config> [transforms_json] [-o output_folder]
"""

import argparse
import json
import csv
import os
from collections import defaultdict, OrderedDict

try:
    import PyOpenColorIO as OCIO
except ImportError:
    print("Error: PyOpenColorIO library not found.")
    print("Please install it using: pip install OpenColorIO")
    exit(1)

from ocio_aces_tools.ocio_utils import get_transform_ids
from ocio_aces_tools.constants import OUTPUT_TRANSFORM_TYPES
from ocio_aces_tools.display_view import (
    parse_display_view_structure,
    is_output_transform_urn,
    get_transform_type_from_urn,
)


def build_urn_to_display_view_map(display_view_map, filter_output_transforms=True,
                                   require_both_sources=False):
    """
    Build a reverse mapping from URN to list of (Display, View) combinations.

    Args:
        display_view_map: Output from parse_display_view_structure()
        filter_output_transforms: If True, only include output transform URNs
        require_both_sources: If True, only include URNs that appear in BOTH
                              view_transform AND display_colorspace (strict matching)

    Returns:
        dict: {urn: [(display, view, source), ...]}
              source is 'view_transform', 'display_colorspace', or 'both'
    """
    urn_to_display_view = defaultdict(list)

    for (display, view), info in display_view_map.items():
        # Track which URNs come from view_transform vs display_colorspace
        vt_urns = set(info['view_transform_urns'])
        dc_urns = set(info['display_colorspace_urns'])

        for urn in info['all_urns']:
            if filter_output_transforms and not is_output_transform_urn(urn):
                continue

            # Determine source
            in_vt = urn in vt_urns
            in_dc = urn in dc_urns

            if require_both_sources and not (in_vt and in_dc):
                # Skip URNs that don't appear in both sources
                continue

            if in_vt and in_dc:
                source = 'both'
            elif in_vt:
                source = 'view_transform'
            else:
                source = 'display_colorspace'

            urn_to_display_view[urn].append({
                'display': display,
                'view': view,
                'source': source,
                'view_transform': info['view_transform'],
                'display_colorspace': info['display_colorspace']
            })

    return urn_to_display_view


def load_output_transforms_from_json(transforms_json_path, versions_to_process=None):
    """
    Load output transform URNs from transforms.json.

    Returns:
        dict: {urn: transform_info}
    """
    output_transforms = {}

    with open(transforms_json_path, 'r', encoding='utf-8') as f:
        full_json_data = json.load(f, object_pairs_hook=OrderedDict)

    all_aces_data = full_json_data.get('transformsData', {})

    for version, data in all_aces_data.items():
        if versions_to_process and version not in versions_to_process:
            continue

        if 'transforms' in data:
            for transform in data['transforms']:
                transform_type = transform.get('transformType', '')
                transform_id = transform.get('transformId', '')

                if transform_type in OUTPUT_TRANSFORM_TYPES and transform_id:
                    output_transforms[transform_id] = {
                        'version': version,
                        'type': transform_type,
                        'name': transform.get('transformUserName', ''),
                        'description': transform.get('description', '')
                    }

    return output_transforms


def validate_display_view_mappings(config_path, transforms_json_path=None, output_folder='.',
                                    versions_to_process=None, strict_mode=False):
    """
    Main validation function.

    Args:
        config_path: Path to OCIO config file
        transforms_json_path: Optional path to transforms.json for missing transform check
        output_folder: Where to write CSV reports
        versions_to_process: List of ACES versions to check
        strict_mode: If True, only match URNs that appear in BOTH view_transform
                     AND display_colorspace (recommended for AMF importing)

    Returns:
        dict: Validation results with statistics and issues
    """
    print(f"Loading OCIO config: {config_path}")
    config = OCIO.Config.CreateFromFile(config_path)

    ocio_version = config.getMajorVersion() + (config.getMinorVersion() / 10.0)
    print(f"OCIO profile version: {ocio_version}")

    # Parse the display/view structure
    print("\nParsing Display+View structure...")
    display_view_map = parse_display_view_structure(config)
    print(f"Found {len(display_view_map)} Display+View combinations")

    # Build URN to Display+View mapping - RELAXED mode (any source)
    print("\nBuilding URN to Display+View mapping (relaxed mode - any source)...")
    urn_to_dv_relaxed = build_urn_to_display_view_map(display_view_map, filter_output_transforms=True,
                                                       require_both_sources=False)
    print(f"Found {len(urn_to_dv_relaxed)} unique output transform URNs (relaxed)")

    # Build URN to Display+View mapping - STRICT mode (requires both sources)
    print("Building URN to Display+View mapping (strict mode - both sources required)...")
    urn_to_dv_strict = build_urn_to_display_view_map(display_view_map, filter_output_transforms=True,
                                                      require_both_sources=True)
    print(f"Found {len(urn_to_dv_strict)} unique output transform URNs (strict)")

    # Use the mode specified
    urn_to_dv = urn_to_dv_strict if strict_mode else urn_to_dv_relaxed

    # Categorize URNs by number of mappings
    unique_mappings = {}    # URN -> exactly 1 Display+View
    conflicting_mappings = {}  # URN -> multiple Display+View combinations

    for urn, mappings in urn_to_dv.items():
        # Count unique (display, view) combinations
        unique_combos = set((m['display'], m['view']) for m in mappings)

        if len(unique_combos) == 1:
            unique_mappings[urn] = mappings[0]
        else:
            conflicting_mappings[urn] = mappings

    # Also categorize the strict mode results for reporting
    strict_unique = {}
    strict_conflicting = {}
    for urn, mappings in urn_to_dv_strict.items():
        unique_combos = set((m['display'], m['view']) for m in mappings)
        if len(unique_combos) == 1:
            strict_unique[urn] = mappings[0]
        else:
            strict_conflicting[urn] = mappings

    # URNs only in view_transform (missing from display colorspace)
    vt_only_urns = set(urn_to_dv_relaxed.keys()) - set(urn_to_dv_strict.keys())

    # Load reference transforms if available
    missing_transforms = {}
    reference_transforms = {}
    if transforms_json_path and os.path.exists(transforms_json_path):
        print(f"\nLoading reference transforms from: {transforms_json_path}")
        reference_transforms = load_output_transforms_from_json(transforms_json_path, versions_to_process)
        print(f"Found {len(reference_transforms)} output transforms in reference JSON")

        # Find missing transforms
        for urn, info in reference_transforms.items():
            if urn not in urn_to_dv_relaxed:
                missing_transforms[urn] = info

    # Generate reports
    print("\n" + "="*80)
    print("VALIDATION RESULTS")
    print("="*80)

    mode_str = "STRICT (URN must be in BOTH view_transform AND display_colorspace)" if strict_mode else \
               "RELAXED (URN can be in EITHER source)"
    print(f"\nMode: {mode_str}")

    print(f"\n{'='*80}")
    print("STRICT MODE ANALYSIS (Recommended for AMF Importing)")
    print("="*80)
    print(f"\nIn strict mode, a URN only matches if it appears in BOTH:")
    print(f"  - The View Transform (defines image intent/tone mapping)")
    print(f"  - The Display Colorspace (defines container encoding)")
    print(f"\nThis ensures the URN uniquely identifies the exact rendering.")

    print(f"\n  Total URNs with strict matching: {len(urn_to_dv_strict)}")
    print(f"  - Unique mappings (1:1): {len(strict_unique)}")
    print(f"  - Conflicting mappings: {len(strict_conflicting)}")
    print(f"\n  URNs in relaxed but NOT in strict: {len(vt_only_urns)}")
    print(f"  (These URNs are only in view_transform OR display_colorspace, not both)")

    if strict_conflicting:
        print(f"\n  STRICT MODE CONFLICTS ({len(strict_conflicting)}):")
        for urn, mappings in list(strict_conflicting.items())[:5]:
            print(f"\n   URN: {urn}")
            unique_combos = set((m['display'], m['view']) for m in mappings)
            for display, view in sorted(unique_combos):
                print(f"      -> Display: '{display}' / View: '{view}'")
        if len(strict_conflicting) > 5:
            print(f"\n   ... and {len(strict_conflicting) - 5} more")

    print(f"\n{'='*80}")
    print("RELAXED MODE ANALYSIS")
    print("="*80)
    print(f"\nIn relaxed mode, a URN matches if it appears in EITHER source.")
    print(f"This shows all potential Display+View combinations for each URN.")

    print(f"\n  Total URNs: {len(urn_to_dv_relaxed)}")
    print(f"  - Unique mappings (1:1): {len(unique_mappings) if not strict_mode else len([u for u,m in urn_to_dv_relaxed.items() if len(set((x['display'],x['view']) for x in m))==1])}")
    print(f"  - Conflicting mappings: {len(conflicting_mappings) if not strict_mode else len([u for u,m in urn_to_dv_relaxed.items() if len(set((x['display'],x['view']) for x in m))>1])}")

    if missing_transforms:
        print(f"\n{'='*80}")
        print(f"MISSING FROM OCIO: {len(missing_transforms)} URNs")
        print("="*80)
        print("These output transform URNs from transforms.json are not in the OCIO config:")
        by_type = defaultdict(list)
        for urn, info in missing_transforms.items():
            by_type[info['type']].append(urn)
        for t_type, urns in sorted(by_type.items()):
            print(f"\n   {t_type}: {len(urns)} missing")
            for urn in urns[:3]:
                print(f"      - {urn}")
            if len(urns) > 3:
                print(f"      ... and {len(urns) - 3} more")

    # Write detailed CSV reports
    os.makedirs(output_folder, exist_ok=True)

    # Report 1: STRICT mode mappings (recommended for AMF)
    strict_mappings_path = os.path.join(output_folder, 'urn_strict_mappings.csv')
    with open(strict_mappings_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['URN', 'Transform Type', 'Display', 'View', 'View Transform',
                        'Display Colorspace', 'Status', 'Num Combos'])

        for urn, mappings in sorted(urn_to_dv_strict.items()):
            unique_combos = set((m['display'], m['view']) for m in mappings)
            status = 'UNIQUE' if len(unique_combos) == 1 else 'CONFLICT'
            transform_type = get_transform_type_from_urn(urn) or ''

            for m in mappings:
                writer.writerow([
                    urn, transform_type, m['display'], m['view'],
                    m['view_transform'], m['display_colorspace'], status, len(unique_combos)
                ])
    print(f"\n  Wrote: {strict_mappings_path}")

    # Report 2: All URN mappings (relaxed mode)
    all_mappings_path = os.path.join(output_folder, 'urn_relaxed_mappings.csv')
    with open(all_mappings_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['URN', 'Transform Type', 'Display', 'View', 'Source',
                        'View Transform', 'Display Colorspace', 'Status', 'Strict Match'])

        for urn, mappings in sorted(urn_to_dv_relaxed.items()):
            unique_combos = set((m['display'], m['view']) for m in mappings)
            status = 'OK' if len(unique_combos) == 1 else f'CONFLICT ({len(unique_combos)} combos)'
            transform_type = get_transform_type_from_urn(urn) or ''
            has_strict = urn in urn_to_dv_strict

            for m in mappings:
                writer.writerow([
                    urn, transform_type, m['display'], m['view'], m['source'],
                    m['view_transform'], m['display_colorspace'], status,
                    'Yes' if has_strict else 'No'
                ])
    print(f"  Wrote: {all_mappings_path}")

    # Report 3: Strict mode conflicts only
    if strict_conflicting:
        conflicts_path = os.path.join(output_folder, 'urn_strict_conflicts.csv')
        with open(conflicts_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['URN', 'Transform Type', 'Num Combos', 'Display', 'View',
                            'View Transform', 'Display Colorspace'])

            for urn, mappings in sorted(strict_conflicting.items()):
                unique_combos = set((m['display'], m['view']) for m in mappings)
                transform_type = get_transform_type_from_urn(urn) or ''

                for m in mappings:
                    writer.writerow([
                        urn, transform_type, len(unique_combos), m['display'], m['view'],
                        m['view_transform'], m['display_colorspace']
                    ])
        print(f"  Wrote: {conflicts_path}")

    # Report 4: URNs only in view_transform (not in both)
    if vt_only_urns:
        vt_only_path = os.path.join(output_folder, 'urn_missing_from_display_colorspace.csv')
        with open(vt_only_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['URN', 'Transform Type', 'View Transform(s) Containing URN',
                            'Suggested Display Colorspace(s)', 'Notes'])

            for urn in sorted(vt_only_urns):
                transform_type = get_transform_type_from_urn(urn) or ''
                mappings = urn_to_dv_relaxed[urn]
                vt_names = set(m['view_transform'] for m in mappings if m['source'] in ['view_transform', 'both'])
                dc_names = set(m['display_colorspace'] for m in mappings)

                # Try to suggest which display colorspace should have this URN
                notes = "URN is in view_transform but not display_colorspace - add to appropriate display colorspace"

                writer.writerow([
                    urn, transform_type, '; '.join(sorted(vt_names)),
                    '; '.join(sorted(dc_names)), notes
                ])
        print(f"  Wrote: {vt_only_path}")

    # Report 5: Missing transforms
    if missing_transforms:
        missing_path = os.path.join(output_folder, 'missing_output_transforms.csv')
        with open(missing_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['URN', 'Transform Type', 'ACES Version', 'User Name', 'Description'])

            for urn, info in sorted(missing_transforms.items()):
                writer.writerow([
                    urn, info['type'], info['version'], info['name'], info['description']
                ])
        print(f"  Wrote: {missing_path}")

    # Report 6: Display+View summary
    dv_summary_path = os.path.join(output_folder, 'display_view_summary.csv')
    with open(dv_summary_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Display', 'View', 'View Transform', 'Display Colorspace',
                        'Num Output URNs (Any)', 'Num Output URNs (Strict)', 'Output URNs'])

        for (display, view), info in display_view_map.items():
            output_urns = [urn for urn in info['all_urns'] if is_output_transform_urn(urn)]
            vt_urns = set(info['view_transform_urns'])
            dc_urns = set(info['display_colorspace_urns'])
            strict_urns = [u for u in output_urns if u in vt_urns and u in dc_urns]
            writer.writerow([
                display, view, info['view_transform'], info['display_colorspace'],
                len(output_urns), len(strict_urns), '\n'.join(output_urns)
            ])
    print(f"  Wrote: {dv_summary_path}")

    # Summary statistics
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    print(f"\nTotal Display+View combinations: {len(display_view_map)}")

    print(f"\nSTRICT MODE (Recommended for AMF):")
    print(f"  URNs with exact match (in both sources): {len(urn_to_dv_strict)}")
    print(f"    - Unique mappings (1:1): {len(strict_unique)} ✓")
    print(f"    - Conflicting mappings: {len(strict_conflicting)} {'✗' if strict_conflicting else '✓'}")

    print(f"\nRELAXED MODE (All occurrences):")
    print(f"  URNs found in config: {len(urn_to_dv_relaxed)}")
    relaxed_unique_count = len([u for u,m in urn_to_dv_relaxed.items()
                                if len(set((x['display'],x['view']) for x in m))==1])
    relaxed_conflict_count = len(urn_to_dv_relaxed) - relaxed_unique_count
    print(f"    - Unique mappings (1:1): {relaxed_unique_count}")
    print(f"    - Conflicting mappings: {relaxed_conflict_count}")

    print(f"\nCOVERAGE GAP:")
    print(f"  URNs in view_transform but NOT in display_colorspace: {len(vt_only_urns)}")
    print(f"  (These need to be added to appropriate display_colorspaces for strict matching)")

    if missing_transforms:
        print(f"\nMISSING FROM OCIO: {len(missing_transforms)} URNs (from transforms.json)")

    # Final verdict based on strict mode
    print("\n" + "="*80)
    if strict_conflicting:
        print("*** STRICT MODE: VALIDATION FAILED ***")
        print(f"    {len(strict_conflicting)} URNs map to multiple Display+View combinations")
        print("    even when requiring URN in both view_transform AND display_colorspace.")
        print("    These conflicts should be resolved in the OCIO config.")
    elif len(urn_to_dv_strict) == 0:
        print("*** STRICT MODE: NO MATCHES ***")
        print("    No URNs appear in both view_transform AND display_colorspace.")
        print("    The config needs URNs added to display_colorspaces.")
    else:
        print("*** STRICT MODE: VALIDATION PASSED ***")
        print(f"    {len(strict_unique)} URNs uniquely map to one Display+View combination")
        print("    when requiring URN in both sources (recommended for AMF importing).")

    if vt_only_urns:
        print(f"\n    NOTE: {len(vt_only_urns)} additional URNs are only in view_transforms.")
        print("    Add them to display_colorspaces for complete strict coverage.")

    return {
        'strict_unique': strict_unique,
        'strict_conflicting': strict_conflicting,
        'relaxed_urn_map': urn_to_dv_relaxed,
        'strict_urn_map': urn_to_dv_strict,
        'vt_only_urns': vt_only_urns,
        'missing_transforms': missing_transforms,
        'display_view_map': display_view_map,
        'reference_transforms': reference_transforms
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate AMF output transform URN to Display+View mappings.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  # Validate an OCIO config (runs both strict and relaxed analysis)
  python3 validate_amf_output_transforms.py config.ocio

  # Validate and check against transforms.json for missing transforms
  python3 validate_amf_output_transforms.py config.ocio transforms.json

  # Specify output folder for reports
  python3 validate_amf_output_transforms.py config.ocio transforms.json -o reports/

  # Filter by ACES versions
  python3 validate_amf_output_transforms.py config.ocio transforms.json -v v1.3 v2.0.0+2025.04.04

What this script validates:
  1. STRICT MODE: Checks URNs that appear in BOTH view_transform AND display_colorspace
     - This is the recommended mode for AMF importing
     - Each URN should map to exactly ONE Display+View combination

  2. RELAXED MODE: Checks all URNs (in either source)
     - Shows all possible Display+View combinations for each URN
     - Useful for understanding the full URN coverage

  3. Reports which output transform URNs from transforms.json are missing

Output reports:
  - urn_strict_mappings.csv: URNs that appear in BOTH sources (use for AMF)
  - urn_relaxed_mappings.csv: All URN occurrences (for analysis)
  - urn_strict_conflicts.csv: Strict mode conflicts
  - urn_missing_from_display_colorspace.csv: URNs only in view_transform
  - missing_output_transforms.csv: URNs from transforms.json not in OCIO
  - display_view_summary.csv: Summary of each Display+View combination
        """
    )

    parser.add_argument("ocio_config", help="Path to the OCIO configuration file")
    parser.add_argument("transforms_json", nargs='?', default=None,
                       help="Path to transforms.json for checking missing transforms (optional)")
    parser.add_argument("-v", "--versions", nargs='+',
                       help="ACES versions to check for missing transforms (e.g., 'v1.3' 'v2.0.0+2025.04.04')")
    parser.add_argument("-o", "--output_folder", default=".",
                       help="Path to output folder for reports (default: current directory)")
    parser.add_argument("-s", "--strict", action="store_true",
                       help="Exit with error code based on strict mode results (default)")

    args = parser.parse_args()

    if not os.path.exists(args.ocio_config):
        print(f"Error: OCIO config not found: {args.ocio_config}")
        exit(1)

    if args.transforms_json and not os.path.exists(args.transforms_json):
        print(f"Error: transforms.json not found: {args.transforms_json}")
        exit(1)

    results = validate_display_view_mappings(
        args.ocio_config,
        args.transforms_json,
        args.output_folder,
        args.versions,
        strict_mode=True  # Always use strict for final verdict
    )

    # Exit with error code if strict mode has conflicts
    if results['strict_conflicting']:
        exit(1)
    exit(0)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    sys.argv = ["ocio_aces_tool", "validate-amf"] + sys.argv[1:]
    from ocio_aces_tools.cli import main as cli_main
    sys.exit(cli_main())
