# OCIO Config Generation from Upstream Source -- Design

**Date:** 2026-03-19
**Status:** Approved

## Goal

Generate 24 OCIO config files covering all combinations of:

- **OCIO profile versions:** v2.5, v2.3
- **ACES versions:** 2.0, 1.3.1, combined 1.3+2.0
- **Config types:** CG, Studio
- **View variants:** default (D65 only), all-views (D65 + D60)

## Approach

Fork the [OpenColorIO-Config-ACES](https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES) repository at tag `v4.0.0`. Track upstream for future merges. The existing generation pipeline stays untouched -- all work is in CSV mapping files, `BUILD_CONFIGURATIONS`, and pre-baked CLF files.

## Architecture

### How the upstream pipeline works

The generation is CSV-driven and layered:

1. **Reference CSV** maps each `ACEStransformID` to a `BuiltinTransform` style and an OCIO interface type (ColorSpace, ViewTransform, or Look). This produces the Reference config.
2. **CG/Studio CSVs** filter the Reference output and extend it with CLF-based transforms (utility spaces, named transforms). These CSVs have both `BuiltinTransform Style` and `CLFtransformID` columns.
3. `generate_config_aces()` → `generate_config_cg()` → `generate_config_studio()` is a cascading chain. Studio calls CG, CG calls Reference.

The core generation code (`common.py`, `factories.py`, `beautifiers.py`) is not modified.

### What we change

**CSV mapping files** (the real work):

| CSV | Purpose |
|-----|---------|
| ACES 1.3 Reference CSV | Normalized from v2.2.0 release to v4.0.0 schema (add `ViewingRule`, `InteropId` columns) |
| ACES 1.3 CG CSV | Filtered subset of ACES 1.3 Reference |
| ACES 1.3 Studio CSV | Wider subset of ACES 1.3 Reference |
| Combined Reference CSV | Superset merge of ACES 2.0 + ACES 1.3 Reference CSVs |
| Combined CG CSV | Filtered subset of Combined Reference |
| Combined Studio CSV | Wider subset of Combined Reference |
| v2.3-targeted CG/Studio CSVs | Same as v2.5 CSVs but with `CLFtransformID` replacing `BuiltinTransform Style` for v2.4+ transforms |

**Missing transforms**: Both ACES 2.0 and ACES 1.3 CSVs are audited against `transforms.json` to add missing input transforms (e.g., SLog1, CanonLog BT2020) that have corresponding `BuiltinTransform` styles but aren't in the current CSVs.

**`BUILD_CONFIGURATIONS`**: Extended in `configuration.py` with entries for all 6 ACES/OCIO combinations.

**CLF files**: Pre-baked for OCIO v2.3 targets using existing `generate_lut_based_config.py` logic.

### Transform scope

Only real ACES transforms that map to OCIO color spaces:

- **Output Transforms** (ODT/RRTODT/Output) → ViewTransform + Display ColorSpace
- **Input Transforms** (CSC) → ColorSpace
- **Looks** (LMT) → Look

No library utilities, no inverse-only transforms.

## Build Matrix

| # | OCIO | ACES | Variants | CSV Source | CLF Needed |
|---|------|------|----------|------------|------------|
| 1 | v2.5 | 2.0 | default + all-views | v4.0.0 CSV + missing transforms | No |
| 2 | v2.5 | 1.3.1 | default + all-views | v2.2.0 CSV normalized + missing transforms | No |
| 3 | v2.5 | 1.3+2.0 | default + all-views | Combined superset CSV | No |
| 4 | v2.3 | 2.0 | default + all-views | v2.5 CSV with ACES 2.0 outputs → CLFtransformID | Yes |
| 5 | v2.3 | 1.3.1 | default + all-views | v2.5 ACES 1.3 CSV (all BuiltinTransforms native at v2.3) | No |
| 6 | v2.3 | 1.3+2.0 | default + all-views | Combined CSV with ACES 2.0 outputs → CLF | Yes |

Each combo produces 4 files (CG default, CG all-views, Studio default, Studio all-views) = **24 configs total**.

## OCIO v2.3 CLF Fallback Strategy

BuiltinTransforms are version-gated. At OCIO v2.3, the following are unavailable:

| Transform | Min OCIO | Fallback |
|-----------|----------|----------|
| All ACES 2.0 output transforms (`_2.0` suffix) | v2.4 | CLF: Matrix(AP0→AP1) + Log(ACEScct) + LUT3D |
| Apple Log CSC and curve | v2.4 | CLF: baked 1D LUT |
| DJI D-Log CSC | v2.5 | CLF: baked 1D LUT |

All ACES 1.x BuiltinTransforms (`_1.0`, `_1.1` suffixes) are available at v2.3. No fallback needed.

For v2.3 configs, the CG/Studio CSVs replace the `BuiltinTransform Style` cell with a `CLFtransformID` for affected transforms. The generation pipeline already handles CLF-referenced transforms natively in the CG/Studio generators -- no code changes required.

The Reference config is not generated for v2.3 targets (it has no CLF column support, and studios use CG/Studio configs).

## Combined CSV Merge Logic

The combined ACES 1.3+2.0 Reference CSV is built by:

1. Starting with the ACES 2.0 (v4.0.0) Reference CSV as the base
2. Adding ACES 1.3 output transforms (ODT/RRTODT rows) -- these use completely different `BuiltinTransform` styles (`_1.0`/`_1.1` vs `_2.0`), so there is zero overlap
3. For input CSCs that appear in both (same `BuiltinTransform` style, different `ACEStransformID` URN), keeping the v2.0 URN (the v1.5 URN is a `previousEquivalentTransformId`)
4. Including both Looks (Reference Gamut Compression + Blue Light Artifact Fix)

## Fork Maintenance

The fork tracks upstream. Changes are isolated to:

- `configuration.py` -- extended `BUILD_CONFIGURATIONS`
- New CSV files in `resources/` directories
- New CLF files for v2.3 fallbacks
- New `invoke` task for building all variants

Core generation code is untouched, minimizing merge conflicts when pulling upstream releases.

## Phases

### Phase 1 -- Fork & CSV work

1. Fork upstream at v4.0.0
2. Audit `transforms.json` vs existing CSVs to identify missing input transforms
3. Normalize ACES 1.3 Reference CSV to v4.0.0 schema
4. Add missing transforms to both ACES version CSVs
5. Build combined Reference CSV
6. Build CG and Studio CSVs for ACES 1.3 and combined variants
7. Extend `BUILD_CONFIGURATIONS`

### Phase 2 -- CLF baking for v2.3

1. Identify all BuiltinTransforms requiring v2.4+ (ACES 2.0 outputs, Apple Log, DJI D-Log)
2. Bake CLF files using existing `generate_lut_based_config.py` logic
3. Create v2.3-targeted CG/Studio CSVs referencing CLF files

### Phase 3 -- Build orchestration & validation

1. Add `invoke build-all-variants` task
2. Generate all 24 configs
3. Validate each config with `config.validate()`
4. Spot-check color transforms against reference
