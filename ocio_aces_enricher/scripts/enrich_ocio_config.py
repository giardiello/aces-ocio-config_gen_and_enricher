#!/usr/bin/env python3
"""
OCIO ACES Config Enricher

Automatically upgrade and enrich OpenColorIO configs with ACES transform IDs
and missing color spaces.

Features:
- Upgrades OCIO v2.4 to v2.5 format
- Adds ACES transform IDs to color spaces
- Enriches with equivalent/inverse transform IDs
- Adds missing color spaces from repository
- Filters by ACES version (1.x or 2.0)
"""

import sys
import argparse
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime
import shutil

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT
REPOSITORY_DIR = PROJECT_ROOT / "ocio_aces_enricher" / "colorspace_repository"

# Official ACES transform registry (main branch). Fetched by default so enrichment
# always uses the published registry unless --transforms points to a local file.
DEFAULT_TRANSFORMS_JSON_URL = (
    "https://raw.githubusercontent.com/aces-aswf/aces/main/transforms.json"
)
TRANSFORMS_FETCH_TIMEOUT_SEC = 300.0
TRANSFORMS_USER_AGENT = "ocio-aces-enricher (Python urllib; ACES transforms.json fetch)"


def fetch_transforms_json(dest_path: Path, url: str) -> None:
    """
    Download transforms JSON from ``url`` to ``dest_path`` and validate it is JSON.

    Raises:
        urllib.error.URLError: network or HTTP errors
        ValueError: response is not valid JSON
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": TRANSFORMS_USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=TRANSFORMS_FETCH_TIMEOUT_SEC) as resp:
        data = resp.read()
    dest_path.write_bytes(data)
    try:
        json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Downloaded file from {url} is not valid JSON ({e}). "
            "Try --transforms with a local transforms.json or check --transforms-url."
        ) from e


def _load_config_permissive(config_path):
    """Load an OCIO config, falling back to a version-bumped copy if needed.

    Some configs (e.g. CLF-based v2.3 with DISPLAY BuiltinTransforms) declare
    a version lower than what their transforms require.  When PyOpenColorIO
    refuses to load them we retry after bumping the declared version to 2.5.
    """
    import PyOpenColorIO as OCIO
    import re as _re, tempfile, os

    try:
        return OCIO.Config.CreateFromFile(str(config_path))
    except OCIO.Exception:
        txt = open(config_path).read()
        txt = _re.sub(r'^(ocio_profile_version:\s*)[\d.]+',
                       r'\g<1>2.5', txt, count=1, flags=_re.MULTILINE)
        fd, tmp = tempfile.mkstemp(suffix='.ocio')
        try:
            os.write(fd, txt.encode()); os.close(fd)
            cfg = OCIO.Config.CreateFromFile(tmp)
            return cfg
        finally:
            os.unlink(tmp)


def detect_ocio_version(config_path):
    """Detect OCIO version from config file."""
    import PyOpenColorIO as OCIO
    config = _load_config_permissive(config_path)
    major = config.getMajorVersion()
    minor = config.getMinorVersion()
    version = major + (minor / 10.0)
    return version, config


def upgrade_to_v25(input_config, output_config):
    """Upgrade OCIO v2.4 config to v2.5 format."""
    upgrade_script = SCRIPTS_DIR / "upgrade_ocio_v24_to_v25.py"

    if not upgrade_script.exists():
        raise FileNotFoundError(f"Upgrade script not found: {upgrade_script}")

    print(f"\n{'='*80}")
    print("UPGRADING CONFIG TO OCIO v2.5")
    print(f"{'='*80}\n")

    cmd = [
        sys.executable,
        str(upgrade_script),
        str(input_config),
        "-o", str(output_config)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("ERROR during upgrade:")
        print(result.stderr)
        return False

    print(result.stdout)
    return True


def enrich_with_aces_ids(config_path, transforms_json, aces_versions, output_dir,
                         report_only=False, prune=False):
    """
    Enrich config with ACES transform IDs using the mapping script.

    Args:
        config_path: Path to OCIO config
        transforms_json: Path to ACES transforms.json
        aces_versions: List of ACES versions to include
        output_dir: Directory for output files
        report_only: Pass --report-only to the mapping script
        prune: Pass --prune to the mapping script
    """
    mapping_script = SCRIPTS_DIR / "ACES_json_to_OCIOmapping.py"

    if not mapping_script.exists():
        raise FileNotFoundError(f"Mapping script not found: {mapping_script}")

    if report_only:
        print(f"\n{'='*80}")
        print("AUDIT / REPORT-ONLY MODE")
        print(f"{'='*80}\n")
    else:
        print(f"\n{'='*80}")
        print("ENRICHING WITH ACES TRANSFORM IDs")
        print(f"{'='*80}\n")

    cmd = [
        sys.executable,
        str(mapping_script),
        str(transforms_json),
        str(config_path),
        "-v"
    ] + aces_versions + [
        "-t", "ACEScsc", "CSC", "IDT", "InvLMT", "InvLook", "InvODT",
        "InvOutput", "InvRRT", "InvRRTODT", "LMT", "Look", "ODT",
        "Output", "RRT", "RRTODT",
        "-o", str(output_dir)
    ]

    if report_only:
        cmd.append("--report-only")
    if prune:
        cmd.append("--prune")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("ERROR during enrichment:")
        print(result.stderr)
        return False, None

    print(result.stdout)

    if report_only:
        return True, None

    enriched_config = output_dir / "config_updated.ocio"
    return enriched_config.exists(), enriched_config


def _collect_file_refs(transform):
    """Recursively collect FileTransform ``src`` paths from *transform*."""
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


def _resolve_search_path(config_path: Path, config) -> Path:
    """Return the first search_path directory that exists on disk.

    Falls back to the directory containing *config_path* itself.
    """
    config_dir = config_path.parent
    for sp in config.getSearchPath().split(':'):
        sp = sp.strip()
        if sp:
            candidate = config_dir / sp
            if candidate.is_dir():
                return candidate
    return config_dir


def add_missing_colorspaces(config_path, aces_version_type, config_type, output_path):
    """
    Add missing color spaces from repository.

    When a repository color space references external LUT files via
    FileTransform, those files are copied from the repository's ``luts/``
    directory into the target config's search_path so the config remains
    self-contained.

    Args:
        config_path: Path to current config
        aces_version_type: 'aces_1.x' or 'aces_2.0'
        config_type: 'studio' or 'reference'
        output_path: Path for final output config
    """
    import PyOpenColorIO as OCIO
    import re

    config_path = Path(config_path)
    output_path = Path(output_path)
    repository_path = REPOSITORY_DIR / aces_version_type / config_type
    repo_luts_dir = repository_path / "luts"

    if not repository_path.exists():
        print(f"\nWarning: Repository not found at {repository_path}")
        print("Skipping color space addition from repository.")
        print("You can populate the repository using extract_colorspaces.py")
        shutil.copy(config_path, output_path)
        return True

    print(f"\n{'='*80}")
    print(f"ADDING MISSING COLOR SPACES FROM REPOSITORY")
    print(f"Repository: {repository_path}")
    print(f"{'='*80}\n")

    # Read the declared version from the YAML before loading.  The permissive
    # loader may bump it to 2.5 to work around incompatible BuiltinTransforms.
    import re as _re
    with open(config_path) as _f:
        _header = _f.read(512)
    _ver_match = _re.search(r'ocio_profile_version:\s*([\d.]+)', _header)
    declared_major, declared_minor = 2, 3
    if _ver_match:
        parts = _ver_match.group(1).split('.')
        declared_major = int(parts[0])
        declared_minor = int(parts[1]) if len(parts) > 1 else 0

    config = _load_config_permissive(config_path)

    # Determine where LUT files should be copied for the target config.
    # If the config has no search_path, we'll create a "luts" directory
    # alongside the output and set the search_path accordingly.
    target_luts_dir = _resolve_search_path(output_path, config)
    needs_search_path = not config.getSearchPath().strip()

    existing_transforms = set()
    existing_colorspace_names = set()

    for cs in config.getColorSpaces():
        existing_colorspace_names.add(cs.getName())

        attrs = cs.getInterchangeAttributes()
        if attrs and 'amf_transform_ids' in attrs:
            amf_ids = attrs['amf_transform_ids']
            if amf_ids:
                for tid in amf_ids.split('\n'):
                    tid = tid.strip()
                    if tid:
                        existing_transforms.add(tid)

        description = cs.getDescription()
        if description:
            for match in re.finditer(r'ACEStransformID:\s*(\S+)', description):
                existing_transforms.add(match.group(1))

    print(f"Current config has:")
    print(f"  Color spaces:  {len(existing_colorspace_names)}")
    print(f"  Transform IDs: {len(existing_transforms)}\n")

    repo_files = list(repository_path.glob("*.ocio"))

    if not repo_files:
        print(f"Warning: No .ocio files found in repository at {repository_path}")
        shutil.copy(config_path, output_path)
        return True

    print(f"Found {len(repo_files)} color space files in repository\n")

    added_count = 0
    skipped_count = 0
    lut_copied_count = 0

    for repo_file in sorted(repo_files):
        try:
            repo_config = OCIO.Config.CreateFromFile(str(repo_file))

            repo_colorspaces = list(repo_config.getColorSpaces())
            if not repo_colorspaces:
                continue

            repo_cs = None
            for cs in repo_colorspaces:
                if cs.getName() != 'raw':
                    repo_cs = cs
                    break

            if not repo_cs:
                continue

            repo_cs_name = repo_cs.getName()

            repo_transforms = set()
            attrs = repo_cs.getInterchangeAttributes()
            if attrs and 'amf_transform_ids' in attrs:
                amf_ids = attrs['amf_transform_ids']
                if amf_ids:
                    for tid in amf_ids.split('\n'):
                        tid = tid.strip()
                        if tid:
                            repo_transforms.add(tid)

            description = repo_cs.getDescription()
            if description:
                for match in re.finditer(r'ACEStransformID:\s*(\S+)', description):
                    repo_transforms.add(match.group(1))

            if not repo_transforms:
                print(f"  ⊘ Skipping {repo_cs_name} (no transform IDs)")
                skipped_count += 1
                continue

            if repo_transforms.issubset(existing_transforms):
                print(f"  ○ Already have: {repo_cs_name}")
                skipped_count += 1
                continue

            if repo_cs_name in existing_colorspace_names:
                print(f"  ! Name conflict: {repo_cs_name} (exists with different transforms)")
                skipped_count += 1
                continue

            # Collect FileTransform references and copy LUTs.
            file_refs: list[str] = []
            for direction in [OCIO.COLORSPACE_DIR_TO_REFERENCE, OCIO.COLORSPACE_DIR_FROM_REFERENCE]:
                t = repo_cs.getTransform(direction)
                if t:
                    file_refs.extend(_collect_file_refs(t))

            lut_ok = True
            for src in file_refs:
                src_path = repo_luts_dir / src
                if not src_path.exists():
                    src_path = repo_file.parent / src
                if src_path.exists():
                    # If the config had no search_path, create a "luts" dir
                    # alongside the output and set search_path once.
                    if needs_search_path:
                        target_luts_dir = output_path.parent / "luts"
                        config.setSearchPath("luts")
                        needs_search_path = False
                    target_luts_dir.mkdir(parents=True, exist_ok=True)
                    dst = target_luts_dir / src_path.name
                    if not dst.exists():
                        shutil.copy2(src_path, dst)
                        lut_copied_count += 1
                        print(f"    + LUT: {src_path.name} -> {target_luts_dir}")
                else:
                    print(f"    ! LUT not found: {src} (required by {repo_cs_name})")
                    lut_ok = False

            if not lut_ok:
                print(f"  ⊘ Skipping {repo_cs_name} (missing LUT files)")
                skipped_count += 1
                continue

            # Verify BuiltinTransform compatibility with the target config's
            # *declared* version. E.g. DISPLAY-* styles require OCIO 2.4+.
            builtin_ok = True
            for direction in [OCIO.COLORSPACE_DIR_TO_REFERENCE, OCIO.COLORSPACE_DIR_FROM_REFERENCE]:
                t = repo_cs.getTransform(direction)
                if t is None:
                    continue
                subs = list(t) if 'GROUP' in str(t.getTransformType()) else [t]
                for sub in subs:
                    if 'BUILTIN' in str(sub.getTransformType()):
                        try:
                            test_cfg = OCIO.Config.CreateRaw()
                            test_cfg.setMajorVersion(declared_major)
                            test_cfg.setMinorVersion(declared_minor)
                            test_cs = OCIO.ColorSpace(name='__test__')
                            grp = OCIO.GroupTransform([sub])
                            test_cs.setTransform(grp, OCIO.COLORSPACE_DIR_TO_REFERENCE)
                            test_cfg.addColorSpace(test_cs)
                            test_cfg.serialize()
                        except OCIO.Exception:
                            print(f"  ⊘ Skipping {repo_cs_name} "
                                  f"(BuiltinTransform '{sub.getStyle()}' "
                                  f"requires newer OCIO version)")
                            builtin_ok = False
                            break
                if not builtin_ok:
                    break

            if not builtin_ok:
                skipped_count += 1
                continue

            # For configs < v2.5, strip interchange attributes (they're
            # a v2.5+ feature and would cause serialization to fail).
            if declared_major <= 2 and declared_minor < 5:
                attrs = repo_cs.getInterchangeAttributes()
                if attrs:
                    for key in list(attrs.keys()):
                        repo_cs.setInterchangeAttribute(key, '')

            config.addColorSpace(repo_cs)
            existing_colorspace_names.add(repo_cs_name)
            existing_transforms.update(repo_transforms)

            lut_note = f" (+{len(file_refs)} LUTs)" if file_refs else ""
            print(f"  ✓ Added: {repo_cs_name} ({len(repo_transforms)} transforms){lut_note}")
            added_count += 1

        except Exception as e:
            print(f"  ✗ Error loading {repo_file.name}: {e}")
            skipped_count += 1

    # Serialize and restore the declared version if we had to bump it.
    serialized = config.serialize()
    if (config.getMajorVersion(), config.getMinorVersion()) != (declared_major, declared_minor):
        serialized = _re.sub(
            r'^(ocio_profile_version:\s*)[\d.]+',
            rf'\g<1>{declared_major}.{declared_minor}',
            serialized, count=1, flags=_re.MULTILINE,
        )
    with open(output_path, 'w') as f:
        f.write(serialized)

    print(f"\n{'='*80}")
    print(f"COLOR SPACE ADDITION COMPLETE")
    print(f"{'='*80}")
    print(f"Added:      {added_count} color spaces")
    print(f"LUT files:  {lut_copied_count} copied")
    print(f"Skipped:    {skipped_count} color spaces")
    print(f"Total:      {len(existing_colorspace_names)} color spaces in output")
    print(f"Output:     {output_path}")
    print(f"{'='*80}\n")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Enrich OCIO config with ACES transform IDs and missing color spaces",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Enrich an ACES 2.0 studio config (default: download official transforms.json)
  python3 enrich_ocio_config.py -i studio.ocio -o enriched.ocio \\
      --aces-version 2.0 --config-type studio

  # Use a local registry (offline / pinned copy)
  python3 enrich_ocio_config.py -i studio.ocio -o enriched.ocio \\
      --aces-version 2.0 --config-type studio --transforms transforms.json

  # Preview what enrichment/pruning would do (no config changes)
  python3 enrich_ocio_config.py -i studio.ocio \\
      --aces-version 2.0 --report-only

  # Prune non-ACES-2.0 URNs then enrich
  python3 enrich_ocio_config.py -i studio.ocio -o clean.ocio \\
      --aces-version 2.0 --config-type studio --prune

  # Enrich an ACES 1.3 reference config
  python3 enrich_ocio_config.py -i reference.ocio -o enriched.ocio \\
      --aces-version 1.3 --config-type reference
        """
    )

    parser.add_argument('-i', '--input', required=True, type=Path,
                        help='Input OCIO config file (.ocio)')
    parser.add_argument('-o', '--output', type=Path, default=None,
                        help='Output enriched OCIO config file (.ocio). '
                             'If omitted, the output is named after the input '
                             'with a _enriched_YYYYMMDD_HHMMSS timestamp suffix. '
                             'Not required with --report-only.')
    parser.add_argument('--aces-version', required=True,
                        choices=['1.x', '1.3', '2.0', 'all'],
                        help='Target ACES version (1.x, 1.3, 2.0, or all)')
    parser.add_argument('--config-type', choices=['studio', 'reference', 'cg'], default=None,
                        help='Config type: studio, reference, or cg. '
                             'CG configs receive ACES ID enrichment but no '
                             'additional color spaces from the repository. '
                             'Required unless --report-only is used.')
    parser.add_argument(
        '--transforms',
        type=Path,
        default=None,
        help='Path to ACES transforms.json. If omitted, the file is downloaded '
             f'from the official repository ({DEFAULT_TRANSFORMS_JSON_URL}) '
             'on each run.',
    )
    parser.add_argument(
        '--transforms-url',
        default=DEFAULT_TRANSFORMS_JSON_URL,
        metavar='URL',
        help='URL to download transforms.json when --transforms is not set '
             f'(default: {DEFAULT_TRANSFORMS_JSON_URL})',
    )
    parser.add_argument('--skip-upgrade', action='store_true',
                        help='Skip OCIO v2.4 to v2.5 upgrade (assume already v2.5)')
    parser.add_argument('--work-dir', type=Path,
                        help='Working directory for intermediate files (default: temp dir)')
    parser.add_argument('--report-only', action='store_true',
                        help='Generate an audit report showing what enrichment/pruning '
                             'would change, without modifying the config. '
                             'Makes --config-type and --output optional.')
    parser.add_argument('--prune', action='store_true',
                        help='Remove URNs whose primary ACES version is outside the '
                             'target --aces-version before enriching.')

    args = parser.parse_args()

    # Validate inputs
    if not args.input.exists():
        print(f"Error: Input config not found: {args.input}")
        return 1

    if args.transforms is not None and not args.transforms.exists():
        print(f"Error: Transforms JSON not found: {args.transforms}")
        return 1

    if not args.report_only and not args.config_type:
        print("Error: --config-type is required unless --report-only is used.")
        return 1

    # Derive output path from input name + timestamp when not explicitly provided
    if args.output is None and not args.report_only:
        stem = args.input.stem
        suffix = args.input.suffix or '.ocio'
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.output = args.input.parent / f"{stem}_enriched_{timestamp}{suffix}"

    # Setup working directory
    if args.work_dir:
        work_dir = args.work_dir
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        import tempfile
        work_dir = Path(tempfile.mkdtemp(prefix="ocio_enricher_"))

    mode_label = "REPORT-ONLY" if args.report_only else ("PRUNE + ENRICH" if args.prune else "ENRICH")

    print(f"\n{'='*80}")
    print(f"OCIO ACES CONFIG ENRICHER  [{mode_label}]")
    print(f"{'='*80}")
    print(f"Input:        {args.input}")
    if not args.report_only:
        print(f"Output:       {args.output}")
    print(f"ACES Version: {args.aces_version}")
    if args.config_type:
        print(f"Config Type:  {args.config_type}")
    print(f"Report Only:  {args.report_only}")
    print(f"Prune:        {args.prune}")
    print(f"Work Dir:     {work_dir}")
    print(f"{'='*80}\n")

    # Resolve transforms.json: local path or fresh download into work dir
    if args.transforms is not None:
        transforms_path = args.transforms.resolve()
        print(f"ACES registry: local file {transforms_path}\n")
    else:
        transforms_path = work_dir / "transforms_official.json"
        print(f"ACES registry: downloading\n  {args.transforms_url}")
        print(f"  -> {transforms_path}\n")
        try:
            fetch_transforms_json(transforms_path, args.transforms_url)
        except urllib.error.URLError as e:
            print(f"Error: Could not download transforms.json: {e}")
            return 1
        except ValueError as e:
            print(f"Error: {e}")
            return 1

    try:
        # Step 1: Detect OCIO version and upgrade if needed
        current_config = args.input

        if not args.skip_upgrade and not args.report_only:
            version, _ = detect_ocio_version(args.input)
            print(f"Detected OCIO version: {version}")

            if version < 2.5:
                upgraded_config = work_dir / "upgraded_v2.5.ocio"
                if not upgrade_to_v25(args.input, upgraded_config):
                    print("Error: Upgrade failed")
                    return 1
                current_config = upgraded_config
            else:
                print("Config is already OCIO v2.5 or higher. Skipping upgrade.")

        # Step 2: Map ACES versions to JSON version strings
        if args.aces_version == 'all':
            aces_json_versions = ['v1.0', 'v1.0.1', 'v1.0.3', 'v1.1',
                                   'v1.2', 'v1.3', 'v1.3.1', 'v1.5',
                                   'v2.0.0+2025.04.04']
            aces_version_type = 'aces_all'
        elif args.aces_version == '2.0':
            aces_json_versions = ['v2.0.0+2025.04.04']
            aces_version_type = 'aces_2.0'
        elif args.aces_version in ['1.x', '1.3']:
            aces_json_versions = ['v1.0', 'v1.0.1', 'v1.0.3', 'v1.1',
                                   'v1.2', 'v1.3', 'v1.3.1', 'v1.5']
            aces_version_type = 'aces_1.x'

        # Step 3: Enrich (or audit) with ACES transform IDs
        enrichment_dir = work_dir / "enriched"
        enrichment_dir.mkdir(exist_ok=True)

        success, enriched_config = enrich_with_aces_ids(
            current_config,
            transforms_path,
            aces_json_versions,
            enrichment_dir,
            report_only=args.report_only,
            prune=args.prune,
        )

        if args.report_only:
            audit_csv = enrichment_dir / "enrichment_audit_report.csv"
            print(f"\n{'='*80}")
            print("REPORT-ONLY COMPLETE")
            print(f"{'='*80}")
            if audit_csv.exists():
                print(f"\nAudit report: {audit_csv}")
            print("No config files were modified.")
            return 0

        if not success or not enriched_config:
            print("Error: Enrichment failed")
            return 1

        # Step 4: Add missing color spaces from repository.
        # CG configs intentionally have a reduced scope — they should not
        # receive additional color spaces beyond what the generator produced.
        if args.config_type == 'cg':
            print("\n  CG config — skipping repository color space addition "
                  "(CG scope is intentionally limited).")
            shutil.copy(enriched_config, args.output)
        else:
            if not add_missing_colorspaces(
                enriched_config,
                aces_version_type,
                args.config_type,
                args.output
            ):
                print("Error: Failed to add missing color spaces")
                return 1

        # Success!
        steps_done = []
        steps_done.append("Upgraded to OCIO v2.5 (if needed)")
        if args.prune:
            steps_done.append(f"Pruned non-ACES-{args.aces_version} URNs")
        steps_done.append("Enriched with ACES transform IDs")
        steps_done.append("Enhanced with equivalent/inverse transform IDs")
        steps_done.append(f"Filtered for ACES {args.aces_version}")
        if args.config_type != 'cg':
            steps_done.append("Added missing color spaces from repository")

        print(f"\n{'='*80}")
        print("ENRICHMENT COMPLETE!")
        print(f"{'='*80}")
        print(f"\nEnriched config saved to: {args.output}")
        print(f"Working directory: {work_dir}")
        print("\nYour config has been:")
        for step in steps_done:
            print(f"  - {step}")

        return 0

    except Exception as e:
        print(f"\nError during enrichment: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
