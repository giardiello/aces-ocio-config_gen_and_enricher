#!/usr/bin/env python

import json
import csv
import argparse
import os
from collections import OrderedDict, defaultdict

# This script requires the PyOpenColorIO library.
# You can install it by running: pip install OpenColorIO
try:
    import PyOpenColorIO as OCIO
except ImportError:
    print("Error: PyOpenColorIO library not found.")
    print("Please install it using: pip install OpenColorIO")
    exit(1)

from ocio_aces_tools.display_view import (
    is_output_transform_urn,
    get_transform_type_from_urn,
    parse_display_view_structure,
)
from ocio_aces_tools.ocio_utils import get_transform_ids


# ============================================================================
# Display+View Validation (uses ocio_aces_tools.display_view)
# ============================================================================


def build_urn_to_display_view_map(display_view_map, filter_output_transforms=True,
                                   require_both_sources=False):
    """
    Build a reverse mapping from URN to list of (Display, View) combinations.
    """
    urn_to_display_view = defaultdict(list)

    for (display, view), info in display_view_map.items():
        vt_urns = set(info['view_transform_urns'])
        dc_urns = set(info['display_colorspace_urns'])

        for urn in info['all_urns']:
            if filter_output_transforms and not is_output_transform_urn(urn):
                continue

            in_vt = urn in vt_urns
            in_dc = urn in dc_urns

            if require_both_sources and not (in_vt and in_dc):
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


def validate_display_view_mappings(config, output_folder):
    """
    Validate Display+View mappings and generate reports.

    Returns:
        dict: Validation results with statistics
    """
    print("\n" + "="*80)
    print("DISPLAY+VIEW VALIDATION")
    print("="*80)

    # Parse the display/view structure
    print("\nParsing Display+View structure...")
    display_view_map = parse_display_view_structure(config)
    print(f"Found {len(display_view_map)} Display+View combinations")

    # Build URN mappings - relaxed and strict modes
    urn_to_dv_relaxed = build_urn_to_display_view_map(display_view_map,
                                                       filter_output_transforms=True,
                                                       require_both_sources=False)
    urn_to_dv_strict = build_urn_to_display_view_map(display_view_map,
                                                      filter_output_transforms=True,
                                                      require_both_sources=True)

    print(f"Output transform URNs (relaxed mode): {len(urn_to_dv_relaxed)}")
    print(f"Output transform URNs (strict mode): {len(urn_to_dv_strict)}")

    # Categorize strict mode results
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

    # Print summary
    print(f"\nSTRICT MODE RESULTS (Recommended for AMF):")
    print(f"  Unique mappings (1:1): {len(strict_unique)} ✓")
    print(f"  Conflicting mappings: {len(strict_conflicting)} {'✗' if strict_conflicting else '✓'}")
    print(f"  Coverage gap (URNs only in view_transform): {len(vt_only_urns)}")

    if strict_conflicting:
        print(f"\n  Conflicts ({len(strict_conflicting)}):")
        for urn in list(strict_conflicting.keys())[:5]:
            mappings = strict_conflicting[urn]
            combos = set((m['display'], m['view']) for m in mappings)
            print(f"    {urn}")
            for d, v in sorted(combos):
                print(f"      -> {d} / {v}")
        if len(strict_conflicting) > 5:
            print(f"    ... and {len(strict_conflicting) - 5} more")

    # Write CSV reports
    # Report 1: Strict mode mappings
    strict_path = os.path.join(output_folder, 'display_view_strict_mappings.csv')
    with open(strict_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['URN', 'Transform Type', 'Display', 'View', 'View Transform',
                        'Display Colorspace', 'Status', 'Num Combos'])
        for urn, mappings in sorted(urn_to_dv_strict.items()):
            unique_combos = set((m['display'], m['view']) for m in mappings)
            status = 'UNIQUE' if len(unique_combos) == 1 else 'CONFLICT'
            transform_type = get_transform_type_from_urn(urn) or ''
            for m in mappings:
                writer.writerow([urn, transform_type, m['display'], m['view'],
                                m['view_transform'], m['display_colorspace'],
                                status, len(unique_combos)])
    print(f"\n  Wrote: {strict_path}")

    # Report 2: Conflicts only
    if strict_conflicting:
        conflicts_path = os.path.join(output_folder, 'display_view_conflicts.csv')
        with open(conflicts_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['URN', 'Transform Type', 'Num Combos', 'Display', 'View',
                            'View Transform', 'Display Colorspace'])
            for urn, mappings in sorted(strict_conflicting.items()):
                unique_combos = set((m['display'], m['view']) for m in mappings)
                transform_type = get_transform_type_from_urn(urn) or ''
                for m in mappings:
                    writer.writerow([urn, transform_type, len(unique_combos),
                                    m['display'], m['view'],
                                    m['view_transform'], m['display_colorspace']])
        print(f"  Wrote: {conflicts_path}")

    # Report 3: Coverage gap (URNs only in view_transform)
    if vt_only_urns:
        gap_path = os.path.join(output_folder, 'display_view_coverage_gap.csv')
        with open(gap_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['URN', 'Transform Type', 'View Transform(s)',
                            'Suggested Display Colorspace(s)', 'Notes'])
            for urn in sorted(vt_only_urns):
                transform_type = get_transform_type_from_urn(urn) or ''
                mappings = urn_to_dv_relaxed[urn]
                vt_names = set(m['view_transform'] for m in mappings
                              if m['source'] in ['view_transform', 'both'])
                dc_names = set(m['display_colorspace'] for m in mappings)
                notes = "Add URN to display_colorspace for strict matching"
                writer.writerow([urn, transform_type, '; '.join(sorted(vt_names)),
                                '; '.join(sorted(dc_names)), notes])
        print(f"  Wrote: {gap_path}")

    # Report 4: Display+View summary
    summary_path = os.path.join(output_folder, 'display_view_summary.csv')
    with open(summary_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Display', 'View', 'View Transform', 'Display Colorspace',
                        'Num Output URNs (Relaxed)', 'Num Output URNs (Strict)'])
        for (display, view), info in display_view_map.items():
            output_urns = [urn for urn in info['all_urns'] if is_output_transform_urn(urn)]
            vt_set = set(info['view_transform_urns'])
            dc_set = set(info['display_colorspace_urns'])
            strict_urns = [u for u in output_urns if u in vt_set and u in dc_set]
            writer.writerow([display, view, info['view_transform'],
                            info['display_colorspace'], len(output_urns), len(strict_urns)])
    print(f"  Wrote: {summary_path}")

    # Final verdict
    print("\n" + "-"*80)
    if strict_conflicting:
        print(f"DISPLAY+VIEW VALIDATION: {len(strict_conflicting)} CONFLICTS FOUND")
    elif vt_only_urns:
        print(f"DISPLAY+VIEW VALIDATION: PASSED ({len(vt_only_urns)} URNs need coverage)")
    else:
        print("DISPLAY+VIEW VALIDATION: PASSED (All URNs have unique mappings)")

    return {
        'strict_unique': len(strict_unique),
        'strict_conflicting': len(strict_conflicting),
        'coverage_gap': len(vt_only_urns),
        'total_display_views': len(display_view_map)
    }


def build_aces_id_map(aces_data):
    """
    Builds a dictionary that maps every ACES transform ID (primary or equivalent)
    to its primary transform object.

    Args:
        aces_data (dict): The loaded, version-filtered data from the transforms.json file.

    Returns:
        dict: A map where keys are transform IDs and values are the transform objects.
    """
    id_map = {}
    for version, data in aces_data.items():
        if 'transforms' in data:
            for transform in data['transforms']:
                # Map the primary ID
                primary_id = transform.get('transformId')
                if primary_id:
                    id_map[primary_id] = transform
                
                # Map all previous equivalent IDs
                for eq_id in transform.get('previousEquivalentTransformIds', []):
                    id_map[eq_id] = transform
    return id_map


def build_aces_version_map(all_aces_data):
    """
    Build a mapping from every known URN to the ACES version(s) where it
    appears as a **primary** transformId.  Uses the *unfiltered*
    transformsData so that URNs from any version can be identified.

    Only primary IDs are mapped to their version.  Equivalent and inverse
    IDs are NOT attributed to the version that merely *references* them —
    they are only attributed to versions where they are the primary ID.
    This prevents e.g. a v1.5 equivalent URN from being classified as
    belonging to v2.0 just because a v2.0 transform lists it in
    previousEquivalentTransformIds.

    Args:
        all_aces_data (dict): The full ``transformsData`` dict from transforms.json,
                              keyed by version string.

    Returns:
        dict: ``{urn_string: set_of_version_strings}``
    """
    urn_to_versions = defaultdict(set)
    for version, data in all_aces_data.items():
        for transform in data.get('transforms', []):
            primary_id = transform.get('transformId')
            if primary_id:
                urn_to_versions[primary_id].add(version)
    return dict(urn_to_versions)


def audit_ocio_items(config, aces_id_map, aces_version_map, target_versions):
    """
    Walk every OCIO item and classify each URN for the audit report.

    For each existing URN the status is:
      - KEEP          – belongs to a target ACES version
      - WOULD_PRUNE   – belongs only to non-target versions
      - UNKNOWN       – not found in transforms.json at all

    For URNs that enrichment *would* add (equivalents / inverses):
      - WOULD_ADD     – not yet present, belongs to a target version
      - WOULD_ADD_AND_PRUNE – would be added by enrichment but then pruned
                              (belongs to non-target version)

    Args:
        config:            OCIO.Config object
        aces_id_map:       {urn: transform_obj}  (version-filtered)
        aces_version_map:  {urn: set(version_strings)}  (unfiltered)
        target_versions:   set of version strings the user selected

    Returns:
        list[dict]: One row per URN per OCIO item, with keys:
            OCIO Item, Item Type, URN, URN Source, ACES Version, Status
    """
    target_set = set(target_versions) if target_versions else set()
    rows = []

    def _classify_existing(urn):
        versions = aces_version_map.get(urn)
        if not versions:
            return 'UNKNOWN', ''
        version_str = '; '.join(sorted(versions))
        if not target_set:
            return 'KEEP', version_str
        if versions & target_set:
            return 'KEEP', version_str
        return 'WOULD_PRUNE', version_str

    def _classify_potential(urn):
        versions = aces_version_map.get(urn)
        if not versions:
            return 'WOULD_ADD', ''
        version_str = '; '.join(sorted(versions))
        if not target_set:
            return 'WOULD_ADD', version_str
        if versions & target_set:
            return 'WOULD_ADD', version_str
        return 'WOULD_ADD_AND_PRUNE', version_str

    def _audit_item(ocio_item, item_type):
        name = ocio_item.getName()
        if not name:
            return

        existing_ids = get_transform_ids(ocio_item)

        # Classify existing URNs
        for urn in existing_ids:
            transform_obj = aces_id_map.get(urn)
            source = 'primary'
            if transform_obj:
                pid = transform_obj.get('transformId', '')
                if urn != pid and urn in transform_obj.get('previousEquivalentTransformIds', []):
                    source = 'equivalent'
                elif urn == transform_obj.get('inverseTransformId'):
                    source = 'inverse'
            status, ver = _classify_existing(urn)
            rows.append({
                'OCIO Item': name, 'Item Type': item_type,
                'URN': urn, 'URN Source': source,
                'ACES Version': ver, 'Status': status,
            })

        # Determine what enrichment would add.
        # When version filtering is active, skip equivalent IDs — they are
        # legacy URNs from older ACES versions and should not be injected.
        existing_set = set(existing_ids)
        for urn in existing_ids:
            transform_obj = aces_id_map.get(urn)
            if not transform_obj:
                continue
            if not target_set:
                for eq_id in transform_obj.get('previousEquivalentTransformIds', []):
                    if eq_id not in existing_set:
                        existing_set.add(eq_id)
                        status, ver = _classify_potential(eq_id)
                        rows.append({
                            'OCIO Item': name, 'Item Type': item_type,
                            'URN': eq_id, 'URN Source': 'equivalent',
                            'ACES Version': ver, 'Status': status,
                        })
            inv_id = transform_obj.get('inverseTransformId')
            if inv_id and inv_id not in existing_set:
                existing_set.add(inv_id)
                status, ver = _classify_potential(inv_id)
                rows.append({
                    'OCIO Item': name, 'Item Type': item_type,
                    'URN': inv_id, 'URN Source': 'inverse',
                    'ACES Version': ver, 'Status': status,
                })

    for cs in config.getColorSpaces():
        _audit_item(cs, 'ColorSpace')
    for look in config.getLooks():
        _audit_item(look, 'Look')
    for vt in config.getViewTransforms():
        _audit_item(vt, 'ViewTransform')

    return rows


def prune_non_target_urns(config, aces_version_map, target_versions):
    """
    Remove URNs from OCIO items whose primary definition does not belong
    to any of the *target_versions*.

    Modifies the config in-place.

    Args:
        config:           OCIO.Config object
        aces_version_map: {urn: set(version_strings)}  (unfiltered)
        target_versions:  set/list of version strings the user selected

    Returns:
        dict: ``{ocio_item_name: [list_of_pruned_urns]}``
    """
    import re as _re

    target_set = set(target_versions)
    ocio_version = config.getMajorVersion() + (config.getMinorVersion() / 10.0)
    pruned_map = {}

    def _should_keep(urn):
        versions = aces_version_map.get(urn)
        if not versions:
            return True  # unknown URNs are kept (conservative)
        return bool(versions & target_set)

    def _prune_item(ocio_item):
        name = ocio_item.getName()
        if not name:
            return
        existing_ids = get_transform_ids(ocio_item)
        if not existing_ids:
            return

        keep = [u for u in existing_ids if _should_keep(u)]
        pruned = [u for u in existing_ids if not _should_keep(u)]
        if not pruned:
            return

        pruned_map[name] = pruned

        if ocio_version >= 2.5:
            try:
                if hasattr(ocio_item, 'setInterchangeAttribute'):
                    new_amf = '\n'.join(keep) if keep else ''
                    ocio_item.setInterchangeAttribute('amf_transform_ids', new_amf)
            except (AttributeError, Exception):
                pass

        # Also clean description-based IDs
        desc = ocio_item.getDescription() or ''
        if desc:
            changed = False
            for urn in pruned:
                pattern = r'\s*ACEStransformID:\s*' + _re.escape(urn) + r'\s*'
                new_desc = _re.sub(pattern, '\n', desc)
                if new_desc != desc:
                    desc = new_desc
                    changed = True
            if changed:
                # Clean up empty section headers left behind
                desc = _re.sub(
                    r'\n\s*(Previous Equivalent ACES Transform IDs:|'
                    r'Inverse ACES Transform ID:)\s*\n\s*-+\s*\n\s*\n',
                    '\n', desc)
                desc = desc.strip()
                ocio_item.setDescription(desc)

    for cs in config.getColorSpaces():
        _prune_item(cs)
    for look in config.getLooks():
        _prune_item(look)
    for vt in config.getViewTransforms():
        _prune_item(vt)

    return pruned_map


def parse_ocio_config(config):
    """
    Parses an OCIO Config object to extract ACEStransformIDs.
    Supports both OCIO v2.4 (description-based) and v2.5+ (interchange-based) formats.

    Args:
        config (OCIO.Config): An OCIO Config object.

    Returns:
        tuple: A tuple containing three items:
               - ocio_to_ids_map: Maps OCIO names to a list of found ACEStransformIDs.
               - id_to_ocio_map: Maps a single ACEStransformID to its OCIO name.
               - ocio_version: The OCIO profile version (float).
    """
    ocio_to_ids_map = OrderedDict()
    id_to_ocio_map = OrderedDict()

    # Get OCIO profile version
    ocio_version = config.getMajorVersion() + (config.getMinorVersion() / 10.0)

    def find_ids_in_item(ocio_item):
        """Extract transform IDs from both description and interchange attributes."""
        name = ocio_item.getName()
        if not name:
            return

        found_ids = get_transform_ids(ocio_item)

        # Store found IDs
        if found_ids:
            if name not in ocio_to_ids_map:
                ocio_to_ids_map[name] = []
            for transform_id in found_ids:
                if transform_id not in ocio_to_ids_map[name]:
                    ocio_to_ids_map[name].append(transform_id)
                if transform_id not in id_to_ocio_map:
                    id_to_ocio_map[transform_id] = name

    # Parse all color spaces
    for cs in config.getColorSpaces():
        find_ids_in_item(cs)

    # Parse all looks
    for look in config.getLooks():
        find_ids_in_item(look)

    # Parse all view transforms
    for vt in config.getViewTransforms():
        find_ids_in_item(vt)

    return ocio_to_ids_map, id_to_ocio_map, ocio_version

def process_files(transforms_json_path, ocio_path, output_folder, versions_to_process=None, types_to_process=None, validate_display_view=False, report_only=False, prune=False):
    """
    Main processing function to correlate ACES transforms with OCIO names and
    generate the specified output files.

    Args:
        report_only: When True, generate an audit report showing what would
                     change (additions and pruning) without modifying the config.
        prune:       When True, remove URNs whose primary definition belongs
                     to ACES versions outside *versions_to_process*.
    """
    # 1. Read ACES transforms JSON file
    print("Reading ACES transforms JSON file...")
    with open(transforms_json_path, 'r', encoding='utf-8') as f:
        full_json_data = json.load(f, object_pairs_hook=OrderedDict)

    # Get the dictionary of transforms data, accommodating the new structure
    all_aces_data = full_json_data.get('transformsData', {})

    # 2. Filter the data based on CLI arguments
    aces_data = OrderedDict()
    if versions_to_process:
        print(f"Filtering for ACES versions: {', '.join(versions_to_process)}")
    if types_to_process:
        print(f"Filtering for transform types: {', '.join(types_to_process)}")
    print("Filtering out ARRI v2-raw and v3-raw IDTs")

    arri_raw_filtered_count = 0
    idt_filtered_count = 0

    # Define allowed ARRI Alexa v3-logC EI values
    allowed_arri_ei = ['EI160', 'EI200', 'EI250', 'EI320', 'EI400', 'EI500',
                       'EI640', 'EI800', 'EI1000', 'EI1280', 'EI1600',
                       'EI2000', 'EI2560', 'EI3200']

    for version, data in all_aces_data.items():
        if versions_to_process and version not in versions_to_process:
            continue

        filtered_version_data = data.copy()
        filtered_transforms = []
        if 'transforms' in data:
            for transform in data['transforms']:
                # Filter by type if specified
                if types_to_process and transform.get('transformType') not in types_to_process:
                    continue

                transform_id = transform.get('transformId', '')
                transform_type = transform.get('transformType', '')

                # Filter out ARRI v2-raw and v3-raw IDTs
                if 'IDT.ARRI' in transform_id and ('v2-raw' in transform_id or 'v3-raw' in transform_id):
                    arri_raw_filtered_count += 1
                    continue

                # Filter ARRI IDTs: only keep v3-logC with specific EI values
                # Keep all other manufacturer IDTs (Apple, Canon, Sony, etc.)
                if transform_type == 'IDT' and 'IDT.ARRI' in transform_id:
                    # Check if it's an ARRI IDT with EI/ISO/CCT specification
                    # Pattern: contains -EI or -ISO or -CCT in the name
                    has_ei_iso_cct = '-EI' in transform_id or '-ISO' in transform_id or '-CCT' in transform_id

                    if has_ei_iso_cct:
                        # It's a specific variant - check if it's an allowed v3-logC EI
                        if 'Alexa-v3-logC' in transform_id:
                            # Check if it has an allowed EI value
                            has_allowed_ei = any(ei in transform_id for ei in allowed_arri_ei)
                            if not has_allowed_ei:
                                idt_filtered_count += 1
                                continue
                        else:
                            # It's an ARRI variant (v2-logC, v3-raw-EI, etc.) - filter it out
                            idt_filtered_count += 1
                            continue
                    # If no EI/ISO/CCT, it's a generic ARRI IDT - keep it

                filtered_transforms.append(transform)

        if filtered_transforms:
            filtered_version_data['transforms'] = filtered_transforms
            aces_data[version] = filtered_version_data

    if not aces_data:
        print("Warning: No transforms match the specified version/type filters. No data to process.")
        return

    if arri_raw_filtered_count > 0:
        print(f"Filtered out {arri_raw_filtered_count} ARRI v2-raw and v3-raw IDTs")
    if idt_filtered_count > 0:
        print(f"Filtered out {idt_filtered_count} other IDTs (keeping only ARRI Alexa v3-logC with specific EI values)")

    # 3. Build a comprehensive map of all ACES IDs to their parent transform
    print("Building map of all known ACES transform IDs...")
    aces_id_map = build_aces_id_map(aces_data)

    # 3b. Build the unfiltered version map (needed for audit & prune)
    aces_version_map = build_aces_version_map(all_aces_data)

    # 4. Parse the OCIO file
    print("Parsing OCIO file...")
    try:
        config = OCIO.Config.CreateFromFile(ocio_path)
    except OCIO.Exception:
        # Some configs (e.g. CLF-based v2.3 with DISPLAY BuiltinTransforms)
        # can't be loaded at their declared version.  Retry with a permissive
        # version so the enrichment can still proceed.
        import re as _re
        import tempfile as _tempfile
        txt = open(ocio_path).read()
        txt = _re.sub(r'^(ocio_profile_version:\s*)[\d.]+',
                       r'\g<1>2.5', txt, count=1, flags=_re.MULTILINE)
        fd, tmp = _tempfile.mkstemp(suffix='.ocio')
        try:
            os.write(fd, txt.encode()); os.close(fd)
            config = OCIO.Config.CreateFromFile(tmp)
            print("  (loaded with permissive version override)")
        finally:
            os.unlink(tmp)
    try:
        ocio_to_ids, id_to_ocio, ocio_version = parse_ocio_config(config)
        print(f"OCIO profile version: {ocio_version}")
        print(f"Found {len(id_to_ocio)} unique transformID mappings in OCIO file.")
    except OCIO.Exception as e:
        print(f"Error parsing OCIO file with PyOpenColorIO: {e}")
        return

    # 4b. Report-only mode: generate audit and exit early
    if report_only:
        print("\n" + "="*80)
        print("AUDIT / REPORT-ONLY MODE")
        print("="*80)
        audit_rows = audit_ocio_items(config, aces_id_map, aces_version_map,
                                       versions_to_process)

        # Print summary
        from collections import Counter
        status_counts = Counter(r['Status'] for r in audit_rows)
        print(f"\nAudit summary ({len(audit_rows)} URN entries across all OCIO items):")
        for status in ['KEEP', 'WOULD_ADD', 'WOULD_PRUNE', 'WOULD_ADD_AND_PRUNE', 'UNKNOWN']:
            count = status_counts.get(status, 0)
            if count:
                print(f"  {status:25s} {count}")

        # Write audit CSV
        audit_csv_path = os.path.join(output_folder, "enrichment_audit_report.csv")
        fieldnames = ['OCIO Item', 'Item Type', 'URN', 'URN Source',
                      'ACES Version', 'Status']
        with open(audit_csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(audit_rows)
        print(f"\n  Audit report written to: {audit_csv_path}")
        print("\nNo config files were modified (report-only mode).")
        return

    # 4c. Prune non-target URNs if requested
    if prune and versions_to_process:
        print("\n" + "="*80)
        print("PRUNING NON-TARGET ACES VERSION URNs")
        print(f"Target versions: {', '.join(versions_to_process)}")
        print("="*80)
        pruned_map = prune_non_target_urns(config, aces_version_map,
                                            versions_to_process)
        total_pruned = sum(len(v) for v in pruned_map.values())
        if pruned_map:
            print(f"\nPruned {total_pruned} URNs from {len(pruned_map)} OCIO items:")
            for name, urns in sorted(pruned_map.items()):
                for urn in urns:
                    print(f"  - {name}: {urn}")
        else:
            print("\nNo URNs needed pruning — all belong to target versions.")

        # Re-parse after pruning so enrichment works on the cleaned config
        ocio_to_ids, id_to_ocio, ocio_version = parse_ocio_config(config)
    elif prune and not versions_to_process:
        print("\nWarning: --prune requires version filtering (-v). Skipping prune step.")

    # 5. Pre-calculate which 'missing' IDs will be added to descriptions
    #    When version filtering is active, skip previousEquivalentTransformIds
    #    entirely — they are by definition legacy IDs from older ACES versions
    #    and should not be injected into a version-targeted config.
    #    Inverse IDs are still added (they reference the current version).
    skip_equivalents = bool(versions_to_process)

    added_as_related_map = {}
    for ocio_name, id_list in ocio_to_ids.items():
        for found_id in id_list:
            transform_obj = aces_id_map.get(found_id)
            if transform_obj:
                if not skip_equivalents:
                    for eq_id in transform_obj.get('previousEquivalentTransformIds', []):
                        added_as_related_map[eq_id] = ocio_name
                inv_id = transform_obj.get('inverseTransformId')
                if inv_id:
                    added_as_related_map[inv_id] = ocio_name

    # 6. Process and update the JSON data & create reports
    print("Correlating JSON with OCIO and creating reports...")
    full_report_rows = []
    found_matches = 0
    total_transforms = 0

    for version, data in aces_data.items():
        if 'transforms' in data:
            for transform in data['transforms']:
                total_transforms += 1
                transform_id = transform.get('transformId')
                if not transform_id:
                    continue
                
                ocio_alias = id_to_ocio.get(transform_id)
                notes = ""
                if not ocio_alias:
                    parent_ocio_item = added_as_related_map.get(transform_id)
                    if parent_ocio_item:
                        notes = f"Added to description of '{parent_ocio_item}'"

                report_row = {
                    'ACES Version': version, 
                    'ACEStransformID': transform_id, 
                    'OCIO Name': ocio_alias or 'MISSING',
                    'Notes': notes
                }
                full_report_rows.append(report_row)

                if ocio_alias:
                    found_matches += 1
                    transform['OCIOalias'] = ocio_alias

    print(f"Matched {found_matches} of {total_transforms} transforms.")

    # 7. Update the OCIO config object in memory with related IDs
    print("Updating OCIO configuration in memory with related transform IDs...")

    def update_item_with_related_ids(ocio_item):
        """
        Update OCIO item with related transform IDs.
        For OCIO v2.5+, adds to interchange amf_transform_ids.
        For OCIO v2.4 and earlier, adds to description.
        """
        # Collect all existing transform IDs from both sources
        found_ids = get_transform_ids(ocio_item)
        original_description = ocio_item.getDescription() or ""

        # Collect equivalent and inverse IDs.
        # When version filtering is active, skip equivalent IDs (they are
        # legacy URNs from older ACES versions).
        all_equivalents = set()
        all_inverses = set()

        for an_id in found_ids:
            transform_obj = aces_id_map.get(an_id)
            if transform_obj:
                if not skip_equivalents:
                    for eq_id in transform_obj.get('previousEquivalentTransformIds', []):
                        all_equivalents.add(eq_id)

                inv_id = transform_obj.get('inverseTransformId')
                if inv_id:
                    all_inverses.add(inv_id)

        # Filter out IDs that are already present
        all_existing_content = original_description or ""
        try:
            if hasattr(ocio_item, 'getInterchangeAttributes'):
                attrs = ocio_item.getInterchangeAttributes()
                if attrs and 'amf_transform_ids' in attrs:
                    amf_ids = attrs['amf_transform_ids']
                    if amf_ids:
                        all_existing_content += amf_ids
        except (AttributeError, Exception):
            pass

        new_equivalents = [eq for eq in sorted(list(all_equivalents)) if eq not in all_existing_content]
        new_inverses = [inv for inv in sorted(list(all_inverses)) if inv not in all_existing_content]

        # Update based on OCIO version
        if ocio_version >= 2.5:
            # For v2.5+, update interchange amf_transform_ids
            if new_equivalents or new_inverses:
                try:
                    if hasattr(ocio_item, 'setInterchangeAttribute'):
                        # Get existing IDs
                        existing_ids = []
                        if hasattr(ocio_item, 'getInterchangeAttributes'):
                            attrs = ocio_item.getInterchangeAttributes()
                            if attrs and 'amf_transform_ids' in attrs:
                                existing_amf = attrs['amf_transform_ids'] or ""
                                existing_ids = [tid.strip() for tid in existing_amf.split('\n') if tid.strip()]

                        # Add new IDs
                        updated_ids = existing_ids + new_equivalents + new_inverses
                        new_amf_content = '\n'.join(updated_ids)

                        # Set updated content
                        ocio_item.setInterchangeAttribute('amf_transform_ids', new_amf_content)
                except (AttributeError, Exception) as e:
                    # If updating interchange fails, fall back to description method
                    print(f"  Warning: Could not update interchange for {ocio_item.getName()}, using description fallback: {e}")
                    update_description_fallback(ocio_item, new_equivalents, new_inverses, original_description)
        else:
            # For v2.4 and earlier, update description
            update_description_fallback(ocio_item, new_equivalents, new_inverses, original_description)

    def update_description_fallback(ocio_item, new_equivalents, new_inverses, original_description):
        """Legacy method: Add related IDs to description field."""
        new_description_part = ""

        # Add Equivalent IDs section
        if new_equivalents:
            new_description_part += "\n\n      Previous Equivalent ACES Transform IDs:\n"
            new_description_part += "      --------------\n"
            formatted_lines = [f"      ACEStransformID: {eq_id}" for eq_id in new_equivalents]
            new_description_part += "\n".join(formatted_lines)

        # Add Inverse ID section
        if new_inverses:
            new_description_part += "\n\n      Inverse ACES Transform ID:\n"
            new_description_part += "      --------------\n"
            formatted_lines = [f"      ACEStransformID: {inv_id}" for inv_id in new_inverses]
            new_description_part += "\n".join(formatted_lines)

        if new_description_part:
            ocio_item.setDescription(original_description + new_description_part)

    for cs in config.getColorSpaces():
        update_item_with_related_ids(cs)
    for look in config.getLooks():
        update_item_with_related_ids(look)
    for vt in config.getViewTransforms():
        update_item_with_related_ids(vt)
    
    # --- Generate Output Files ---
    output_json_path = os.path.join(output_folder, "transforms_updated.json")
    output_csv_path = os.path.join(output_folder, "ocio_transform_matches.csv")
    output_report_csv_path = os.path.join(output_folder, "aces_ocio_mapping_report.csv")
    output_ocio_path = os.path.join(output_folder, "config_updated.ocio")

    print("\nWriting output files...")
    # 1. Write the updated JSON file, preserving the original structure
    output_json_data = full_json_data.copy()
    output_json_data['transformsData'] = aces_data
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(output_json_data, f, indent=4)
    print(f"  - Updated JSON written to: {output_json_path}")

    # 2. Write the "matches only" CSV file from the OCIO data
    csv_rows = []
    for ocio_name, id_list in ocio_to_ids.items():
        for transform_id in id_list:
            csv_rows.append({'OCIO Name': ocio_name, 'ACEStransformID': transform_id})
            
    if csv_rows:
        with open(output_csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['OCIO Name', 'ACEStransformID'])
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"  - Matched transforms CSV report written to: {output_csv_path}")

    # 3. Write the new full CSV report
    if full_report_rows:
        with open(output_report_csv_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['ACES Version', 'ACEStransformID', 'OCIO Name', 'Notes']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(full_report_rows)
        print(f"  - Full mapping CSV report written to: {output_report_csv_path}")

    # 4. Write the new updated OCIO file
    with open(output_ocio_path, 'w', encoding='utf-8') as f:
        f.write(config.serialize())
    print(f"  - Updated OCIO config written to: {output_ocio_path}")

    # 5. Run Display+View validation if requested
    if validate_display_view:
        validate_display_view_mappings(config, output_folder)

    print("\nProcessing complete.")

def main():
    """
    Sets up the command-line interface and runs the main processing function.
    """
    parser = argparse.ArgumentParser(
        description="Correlate ACES transform IDs with OCIO color space names and update configs.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("transforms_json", help="Path to the input ACES transforms JSON file.")
    parser.add_argument("ocio_config", help="Path to the input OpenColorIO configuration file.")
    parser.add_argument("-v", "--versions", nargs='+', help="A list of ACES versions to process (e.g., 'v1.3' 'v2.0.0+2025.04.04').\nIf not provided, all versions are processed.")
    parser.add_argument("-t", "--types", nargs='+', help="A list of transform types to process (e.g., 'ODT' 'LMT' 'CSC').\nIf not provided, all types are processed.")
    parser.add_argument("-o", "--output_folder", default=".", help="Path to the output folder where all generated files will be saved.\n(default: current directory)")
    parser.add_argument("--validate-display-view", action="store_true",
                        help="Run Display+View validation to ensure each output transform URN\nmaps to exactly ONE Display+View combination (required for AMF export).")
    parser.add_argument("--report-only", action="store_true",
                        help="Generate an audit report showing what enrichment/pruning would\n"
                             "change, without modifying the config.")
    parser.add_argument("--prune", action="store_true",
                        help="Remove URNs whose primary ACES version is outside the target\n"
                             "versions specified with -v. Requires -v.")

    args = parser.parse_args()

    # Create the output directory if it doesn't exist
    os.makedirs(args.output_folder, exist_ok=True)

    process_files(
        args.transforms_json,
        args.ocio_config,
        args.output_folder,
        args.versions,
        args.types,
        args.validate_display_view,
        report_only=args.report_only,
        prune=args.prune,
    )

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    sys.argv = ["ocio_aces_tool", "map"] + sys.argv[1:]
    from ocio_aces_tools.cli import main as cli_main
    sys.exit(cli_main())
