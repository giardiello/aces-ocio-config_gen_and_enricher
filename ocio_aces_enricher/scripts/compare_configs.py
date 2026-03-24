#!/usr/bin/env python3
"""
Compare OCIO configs to identify missing color spaces.

This utility compares a source config against a reference/repository
to identify which color spaces are missing and could be added.
"""

import sys
import argparse
from pathlib import Path
import PyOpenColorIO as OCIO
import re
from collections import defaultdict


def get_transform_ids_from_colorspace(cs):
    """Extract all ACES transform IDs from a color space."""
    transform_ids = set()

    # Try interchange attribute (v2.5+)
    attrs = cs.getInterchangeAttributes()
    if attrs and 'amf_transform_ids' in attrs:
        amf_ids = attrs['amf_transform_ids']
        if amf_ids:
            for tid in amf_ids.split('\n'):
                tid = tid.strip()
                if tid:
                    transform_ids.add(tid)

    # Try description (v2.4)
    description = cs.getDescription()
    if description:
        for match in re.finditer(r'ACEStransformID:\s*(\S+)', description):
            transform_ids.add(match.group(1))

    return transform_ids


def analyze_config(config_path):
    """Analyze a config and return mapping of transform IDs to color spaces."""
    config = OCIO.Config.CreateFromFile(str(config_path))

    # Map transform ID -> list of color space names
    transform_to_colorspaces = defaultdict(list)
    colorspace_to_transforms = {}

    for cs in config.getColorSpaces():
        cs_name = cs.getName()
        transform_ids = get_transform_ids_from_colorspace(cs)

        if transform_ids:
            colorspace_to_transforms[cs_name] = transform_ids
            for tid in transform_ids:
                transform_to_colorspaces[tid].append(cs_name)

    return {
        'config': config,
        'transform_to_colorspaces': dict(transform_to_colorspaces),
        'colorspace_to_transforms': colorspace_to_transforms,
        'all_transforms': set(transform_to_colorspaces.keys()),
        'all_colorspaces': set(colorspace_to_transforms.keys())
    }


def compare_configs(source_path, reference_path):
    """
    Compare source config against reference to find missing color spaces.

    Args:
        source_path: Config being analyzed (what we want to enrich)
        reference_path: Reference config (what we want to match)

    Returns:
        Dictionary with analysis results
    """
    print(f"\n{'='*80}")
    print("ANALYZING CONFIGS")
    print(f"{'='*80}")
    print(f"Source:    {source_path}")
    print(f"Reference: {reference_path}")
    print(f"{'='*80}\n")

    source = analyze_config(source_path)
    reference = analyze_config(reference_path)

    # Find missing transforms
    missing_transforms = reference['all_transforms'] - source['all_transforms']
    common_transforms = reference['all_transforms'] & source['all_transforms']

    # Find which reference color spaces have the missing transforms
    missing_colorspaces = {}
    for tid in missing_transforms:
        cs_names = reference['transform_to_colorspaces'][tid]
        for cs_name in cs_names:
            if cs_name not in missing_colorspaces:
                missing_colorspaces[cs_name] = set()
            missing_colorspaces[cs_name].add(tid)

    print(f"SOURCE CONFIG:")
    print(f"  Color spaces:  {len(source['all_colorspaces'])}")
    print(f"  Transform IDs: {len(source['all_transforms'])}")
    print(f"\nREFERENCE CONFIG:")
    print(f"  Color spaces:  {len(reference['all_colorspaces'])}")
    print(f"  Transform IDs: {len(reference['all_transforms'])}")
    print(f"\nCOMPARISON:")
    print(f"  Common transforms: {len(common_transforms)}")
    print(f"  Missing transforms: {len(missing_transforms)}")
    print(f"  Missing color spaces: {len(missing_colorspaces)}")

    if missing_colorspaces:
        print(f"\n{'='*80}")
        print("MISSING COLOR SPACES")
        print(f"{'='*80}\n")

        for cs_name in sorted(missing_colorspaces.keys()):
            transform_ids = missing_colorspaces[cs_name]
            print(f"\n{cs_name}")
            print(f"  Transform IDs ({len(transform_ids)}):")
            for tid in sorted(transform_ids):
                print(f"    - {tid}")

    return {
        'source': source,
        'reference': reference,
        'missing_transforms': missing_transforms,
        'common_transforms': common_transforms,
        'missing_colorspaces': missing_colorspaces
    }


def main():
    parser = argparse.ArgumentParser(
        description="Compare OCIO configs to identify missing color spaces",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare a config against reference
  python3 compare_configs.py \\
      --source my_config.ocio \\
      --reference reference_config.ocio

  # Save analysis to file
  python3 compare_configs.py \\
      --source my_config.ocio \\
      --reference reference_config.ocio \\
      --output analysis.txt
        """
    )

    parser.add_argument('-s', '--source', required=True, type=Path,
                        help='Source OCIO config to analyze')
    parser.add_argument('-r', '--reference', required=True, type=Path,
                        help='Reference OCIO config to compare against')
    parser.add_argument('-o', '--output', type=Path,
                        help='Output file for analysis (optional)')

    args = parser.parse_args()

    if not args.source.exists():
        print(f"Error: Source config not found: {args.source}")
        return 1

    if not args.reference.exists():
        print(f"Error: Reference config not found: {args.reference}")
        return 1

    try:
        # Redirect stdout to file if requested
        if args.output:
            original_stdout = sys.stdout
            with open(args.output, 'w') as f:
                sys.stdout = f
                compare_configs(args.source, args.reference)
            sys.stdout = original_stdout
            print(f"\nAnalysis saved to: {args.output}")
        else:
            compare_configs(args.source, args.reference)

        return 0

    except Exception as e:
        print(f"\nError during comparison: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
