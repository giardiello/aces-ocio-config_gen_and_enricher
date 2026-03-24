#!/usr/bin/env python3
"""
Extract individual color spaces from OCIO configs into repository.

This utility extracts color spaces from reference OCIO configs and saves them
as individual .ocio files, organized by ACES version and config type.

When a color space references external LUT files via FileTransform, those files
are copied into a ``luts/`` subdirectory alongside the repository .ocio files.
"""

import shutil
import sys
import argparse
from pathlib import Path
import PyOpenColorIO as OCIO


def _collect_file_refs(transform):
    """Recursively collect all FileTransform ``src`` paths from *transform*."""
    refs: list[str] = []
    if transform is None:
        return refs
    ttype = str(transform.getTransformType())
    if 'FILE' in ttype:
        refs.append(transform.getSrc())
    elif 'GROUP' in ttype:
        for sub in transform:
            refs.extend(_collect_file_refs(sub))
    return refs


def _resolve_lut_file(src: str, config_path: Path, search_paths: list[str]) -> Path | None:
    """Try to locate *src* on disk using the config's search_path entries."""
    config_dir = config_path.parent
    for sp in search_paths:
        candidate = config_dir / sp / src
        if candidate.exists():
            return candidate
    candidate = config_dir / src
    if candidate.exists():
        return candidate
    return None


def extract_colorspaces(config_path, output_dir, aces_version, config_type):
    """
    Extract all color spaces from a config into individual files.

    Args:
        config_path: Path to source OCIO config
        output_dir: Base directory for repository (e.g., colorspace_repository)
        aces_version: 'aces_1.x' or 'aces_2.0'
        config_type: 'studio' or 'reference'
    """
    config_path = Path(config_path)
    config = OCIO.Config.CreateFromFile(str(config_path))

    search_paths = [
        s.strip()
        for s in config.getSearchPath().split(':')
        if s.strip()
    ]

    repo_path = Path(output_dir) / aces_version / config_type
    repo_path.mkdir(parents=True, exist_ok=True)
    luts_dir = repo_path / "luts"

    extracted_count = 0
    skipped_count = 0
    lut_count = 0

    print(f"\n{'='*80}")
    print(f"EXTRACTING COLOR SPACES TO REPOSITORY")
    print(f"{'='*80}")
    print(f"Source:       {config_path}")
    print(f"Repository:   {repo_path}")
    print(f"ACES Version: {aces_version}")
    print(f"Config Type:  {config_type}")
    print(f"{'='*80}\n")

    for cs in config.getColorSpaces():
        cs_name = cs.getName()

        attrs = cs.getInterchangeAttributes()
        has_aces_ids = attrs and 'amf_transform_ids' in attrs and attrs['amf_transform_ids']

        if not has_aces_ids:
            description = cs.getDescription()
            if not description or 'ACEStransformID:' not in description:
                print(f"  ⊘ Skipping {cs_name} (no ACES transform IDs)")
                skipped_count += 1
                continue

        temp_config = OCIO.Config.CreateRaw()
        temp_config.setMajorVersion(config.getMajorVersion())
        temp_config.setMinorVersion(config.getMinorVersion())

        temp_config.addColorSpace(cs)

        try:
            temp_config.setRole(OCIO.ROLE_SCENE_LINEAR, cs_name)
        except Exception:
            pass

        # Collect and copy any referenced LUT files.
        file_refs: list[str] = []
        for direction in [OCIO.COLORSPACE_DIR_TO_REFERENCE, OCIO.COLORSPACE_DIR_FROM_REFERENCE]:
            t = cs.getTransform(direction)
            if t:
                file_refs.extend(_collect_file_refs(t))

        for src in file_refs:
            resolved = _resolve_lut_file(src, config_path, search_paths)
            if resolved:
                luts_dir.mkdir(exist_ok=True)
                dst = luts_dir / resolved.name
                if not dst.exists():
                    shutil.copy2(resolved, dst)
                    lut_count += 1
                    print(f"    + LUT: {resolved.name}")
            else:
                print(f"    ! LUT not found: {src}")

        safe_name = cs_name.replace('/', '_').replace(' ', '_').replace(':', '_')
        output_file = repo_path / f"{safe_name}.ocio"

        try:
            with open(output_file, 'w') as f:
                f.write(temp_config.serialize())

            lut_note = f"  (+{len(file_refs)} LUTs)" if file_refs else ""
            print(f"  ✓ Extracted: {cs_name}{lut_note}")
            extracted_count += 1

        except Exception as e:
            print(f"  ✗ Error extracting {cs_name}: {e}")

    print(f"\n{'='*80}")
    print(f"EXTRACTION COMPLETE")
    print(f"{'='*80}")
    print(f"Extracted:  {extracted_count} color spaces")
    print(f"LUT files:  {lut_count} copied to {luts_dir}")
    print(f"Skipped:    {skipped_count} color spaces")
    print(f"Location:   {repo_path}")
    print(f"{'='*80}\n")

    return extracted_count


def main():
    parser = argparse.ArgumentParser(
        description="Extract color spaces from OCIO config into repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract from ACES 2.0 reference config
  python3 extract_colorspaces.py -i reference-v2.0.ocio \\
      --aces-version aces_2.0 --config-type reference \\
      -o ../colorspace_repository

  # Extract from ACES 1.x studio config
  python3 extract_colorspaces.py -i studio-v1.x.ocio \\
      --aces-version aces_1.x --config-type studio \\
      -o ../colorspace_repository
        """
    )

    parser.add_argument('-i', '--input', required=True, type=Path,
                        help='Input OCIO config file (.ocio)')
    parser.add_argument('-o', '--output', required=True, type=Path,
                        help='Output directory for repository')
    parser.add_argument('--aces-version', required=True,
                        choices=['aces_1.x', 'aces_2.0'],
                        help='ACES version category')
    parser.add_argument('--config-type', required=True,
                        choices=['studio', 'reference'],
                        help='Config type: studio or reference')

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input config not found: {args.input}")
        return 1

    try:
        extracted = extract_colorspaces(
            args.input,
            args.output,
            args.aces_version,
            args.config_type
        )

        if extracted == 0:
            print("Warning: No color spaces were extracted!")
            return 1

        return 0

    except Exception as e:
        print(f"\nError during extraction: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
