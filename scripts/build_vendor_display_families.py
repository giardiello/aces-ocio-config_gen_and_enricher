#!/usr/bin/env python3
"""Build ocio_vendor_extensions/families/* packages from the FACES studio config."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import PyOpenColorIO as OCIO
import yaml

from ocio_vendor_extensions.config_merger import collect_all_file_refs_for_colorspace
FACES_OCIO = REPO / "INPUT_OCIO/FACES_OCIO/FACES_OCIO/studio-config-all-ACES_FACES-all-views-v2.4.ocio"
TRANSFORMS_DIR = REPO / "INPUT_OCIO/FACES_OCIO/FACES_OCIO/transforms"
FAMILIES_ROOT = REPO / "ocio_vendor_extensions" / "families"

# fmt: off
ARRI_DISPLAY_MAPPINGS = {
    "ARRI : Rec.1886: 2.4 Gamma : Rec.709": ["Rec.1886 Rec.709 - Display"],
    "ARRI : Rec.1886: 2.4 Gamma : Rec.709 (Classic)": ["Rec.1886 Rec.709 - Display"],
    "ARRI : DCI: 2.6 Gamma : P3 D65": ["Display P3 - Display", "P3-D65 - Display"],
    "ARRI : Rec.2020: 2.4 Gamma : Rec.2020": ["Rec.1886 Rec.2020 - Display"],
    "ARRI : Rec.2100 : HLG 1.2 Gamma : Rec.2020 : 1000 nits": ["Rec.2100-HLG - Display"],
    "ARRI : Rec.2100 : ST 2084 PQ : Rec.2020 : 1000 nits": ["Rec.2100-PQ - Display"],
}

DAVINCI_DISPLAY_MAPPINGS = {
    "DaVinci : sRGB Display: Piecewise : Rec.709": ["sRGB - Display"],
    "DaVinci : DCI: 2.6 Gamma : P3 D65": ["Display P3 - Display", "P3-D65 - Display"],
    "DaVinci : Rec.1886: 2.4 Gamma : Rec.709": ["Rec.1886 Rec.709 - Display"],
    "DaVinci : Rec.2020: 2.4 Gamma : Rec.2020": ["Rec.1886 Rec.2020 - Display"],
    "DaVinci : Rec.2100 : HLG 1.2 Gamma : Rec.2020 : 1000 nits": ["Rec.2100-HLG - Display"],
    "DaVinci : Rec.2100 : ST 2084 PQ : Rec.2020 : 1000 nits": ["Rec.2100-PQ - Display"],
    "DaVinci : Rec.2100 : ST 2084 PQ : Rec.2020 : 2000 nits": ["Rec.2100-PQ - Display"],
    "DaVinci : Rec.2100 : ST 2084 PQ : Rec.2020 : 4000 nits": ["Rec.2100-PQ - Display"],
    "DaVinci : Rec.2100 : ST 2084 PQ : Rec.2020 : 500 nits": ["Rec.2100-PQ - Display"],
    "DaVinci : Dolby Cin: ST 2084 PQ : Rec.2020 : 108 nits": ["Rec.2100-PQ - Display"],
    "DaVinci : Dolby: ST 2084 PQ : P3 D65 : 1000 nits": ["ST2084-P3-D65 - Display"],
    "DaVinci : Dolby: ST 2084 PQ : P3 D65 : 2000 nits": ["ST2084-P3-D65 - Display"],
    "DaVinci : Dolby: ST 2084 PQ : P3 D65 : 4000 nits": ["ST2084-P3-D65 - Display"],
    "DaVinci : Dolby: ST 2084 PQ : P3 D65 : 500 nits": ["ST2084-P3-D65 - Display"],
    "DaVinci : Dolby Cin: ST 2084 PQ : P3 D65 : 108 nits": ["ST2084-P3-D65 - Display"],
}

FILMLIGHT_DISPLAY_MAPPINGS = {
    "FilmLight : sRGB: ~2.2 Gamma : Rec.709": ["sRGB - Display"],
    "FilmLight : sRGB Display: 2.2 Gamma : Rec.709": ["sRGB - Display"],
    "FilmLight : DCI: 2.6 Gamma : P3 D65": ["Display P3 - Display", "P3-D65 - Display"],
    "FilmLight : DCI: 2.6 Gamma : P3 D60": ["P3-D60 - Display"],
    "FilmLight : DCI: 2.6 Gamma : P3 DCI": ["P3-DCI - Display"],
    "FilmLight : DCI: 2.6 Gamma : X′Y′Z′": [],
    "FilmLight : Rec.1886: 2.4 Gamma : Rec.709": ["Rec.1886 Rec.709 - Display"],
    "FilmLight : Rec.2020: 2.4 Gamma : Rec.2020": ["Rec.1886 Rec.2020 - Display"],
    "FilmLight : Rec.2100 : HLG 1.2 Gamma : Rec.2020 : 1000 nits": ["Rec.2100-HLG - Display"],
    "FilmLight : Rec.2100 : HLG 1.2 Gamma : Rec.2020 : Preview SDR": ["Rec.2100-HLG - Display"],
    "FilmLight : Rec.2100 : ST 2084 PQ : Rec.2020 : 1000 nits": ["Rec.2100-PQ - Display"],
    "FilmLight : Rec.2100 : ST 2084 PQ : Rec.2020 : 10000 nits": ["Rec.2100-PQ - Display"],
    "FilmLight : Rec.2100 : ST 2084 PQ : Rec.2020 : 1600 nits": ["Rec.2100-PQ - Display"],
    "FilmLight : Rec.2100 : ST 2084 PQ : Rec.2020 : 2000 nits": ["Rec.2100-PQ - Display"],
    "FilmLight : Rec.2100 : ST 2084 PQ : Rec.2020 : 4000 nits": ["Rec.2100-PQ - Display"],
    "FilmLight : Rec.2100 : ST 2084 PQ : Rec.2020 : 5000 nits": ["Rec.2100-PQ - Display"],
    "FilmLight : Rec.2100 : ST 2084 PQ : Rec.2020 : 600 nits": ["Rec.2100-PQ - Display"],
    "FilmLight : DCI: ST 2084 PQ : P3 D65 : 300 nits": ["ST2084-P3-D65 - Display"],
    "FilmLight : DCI: ST 2084 PQ : Rec.2020 : 300 nits": ["Rec.2100-PQ - Display"],
    "FilmLight : DCI: ST 2084 PQ : X′Y′Z′ : 300 nits": [],
    "FilmLight : Dolby Cin: ST 2084 PQ : P3 D65 : 108 nits": ["ST2084-P3-D65 - Display"],
    "FilmLight : Dolby Cin: ST 2084 PQ : Rec.2020 : 108 nits": ["Rec.2100-PQ - Display"],
    "FilmLight : Dolby Cin: ST 2084 PQ : X′Y′Z′ : 108 nits": [],
    "FilmLight : Dolby: ST 2084 PQ : P3 D65 : 1000 nits": ["ST2084-P3-D65 - Display"],
    "FilmLight : Dolby: ST 2084 PQ : P3 D65 : 10000 nits": ["ST2084-P3-D65 - Display"],
    "FilmLight : Dolby: ST 2084 PQ : P3 D65 : 1600 nits": ["ST2084-P3-D65 - Display"],
    "FilmLight : Dolby: ST 2084 PQ : P3 D65 : 2000 nits": ["ST2084-P3-D65 - Display"],
    "FilmLight : Dolby: ST 2084 PQ : P3 D65 : 4000 nits": ["ST2084-P3-D65 - Display"],
    "FilmLight : Dolby: ST 2084 PQ : P3 D65 : 5000 nits": ["ST2084-P3-D65 - Display"],
    "FilmLight : Dolby: ST 2084 PQ : P3 D65 : 600 nits": ["ST2084-P3-D65 - Display"],
}

RED_IPP2_DISPLAY_MAPPINGS = {
    "RED-IPP2 : Rec.1886: 2.4 Gamma : Rec.709 - MC-R1": ["Rec.1886 Rec.709 - Display"],
    "RED-IPP2 : Rec.1886: 2.4 Gamma : Rec.709 - MC-R2": ["Rec.1886 Rec.709 - Display"],
    "RED-IPP2 : Rec.1886: 2.4 Gamma : Rec.709 - MC-R3": ["Rec.1886 Rec.709 - Display"],
    "RED-IPP2 : Rec.1886: 2.4 Gamma : Rec.709 - MC-R4": ["Rec.1886 Rec.709 - Display"],
    "RED-IPP2 : Rec.1886: 2.4 Gamma : Rec.2020 - MC-R1": ["Rec.1886 Rec.2020 - Display"],
    "RED-IPP2 : Rec.1886: 2.4 Gamma : Rec.2020 - MC-R2": ["Rec.1886 Rec.2020 - Display"],
    "RED-IPP2 : Rec.1886: 2.4 Gamma : Rec.2020 - MC-R3": ["Rec.1886 Rec.2020 - Display"],
    "RED-IPP2 : Rec.1886: 2.4 Gamma : Rec.2020 - MC-R4": ["Rec.1886 Rec.2020 - Display"],
}
# fmt: on


def collect_refs_from_transform(tr, names: set[str]) -> None:
    if tr is None:
        return
    tt = str(tr.getTransformType())
    if "GROUP" in tt:
        for i in range(len(tr)):
            collect_refs_from_transform(tr[i], names)
    elif "COLORSPACE" in tt.upper().replace("_", ""):
        names.add(tr.getSrc())
        names.add(tr.getDst())


def closure_for_cs(config: OCIO.Config, root_names: list[str]) -> set[str]:
    pending = set(root_names)
    done: set[str] = set()
    while pending:
        name = pending.pop()
        if name in done:
            continue
        cs = config.getColorSpace(name)
        if cs is None:
            done.add(name)
            continue
        done.add(name)
        for d in (OCIO.COLORSPACE_DIR_TO_REFERENCE, OCIO.COLORSPACE_DIR_FROM_REFERENCE):
            collect_refs_from_transform(cs.getTransform(d), pending)
    return {n for n in done if config.getColorSpace(n) is not None}


def role_color_space_names(config: OCIO.Config) -> set[str]:
    out: set[str] = set()
    for rn in config.getRoleNames():
        csname = config.getRoleColorSpace(rn)
        if csname:
            out.add(csname)
    return out


def collect_lut_refs_for_names(config: OCIO.Config, cs_names: set[str]) -> list[str]:
    refs: set[str] = set()
    for name in cs_names:
        cs = config.getColorSpace(name)
        if cs is None:
            continue
        refs.update(collect_all_file_refs_for_colorspace(cs))
    return sorted(refs)


def build_snippet_config(
    faces: OCIO.Config,
    vendor_prefix: str,
    intermediates: tuple[str, ...] = (),
) -> OCIO.Config:
    vnames = [cs.getName() for cs in faces.getColorSpaces() if cs.getName().startswith(vendor_prefix)]
    vnames = list(vnames) + list(intermediates)
    cl = closure_for_cs(faces, vnames)
    all_names = cl | role_color_space_names(faces) | {"Raw"}

    snippet = OCIO.Config()
    snippet.setMajorVersion(2)
    snippet.setMinorVersion(4)
    for n in sorted(all_names):
        snippet.addColorSpace(faces.getColorSpace(n))
    for rn in faces.getRoleNames():
        snippet.setRole(rn, faces.getRoleColorSpace(rn))
    snippet.addViewTransform(faces.getViewTransform("Un-tone-mapped"))
    snippet.setFileRules(faces.getFileRules())
    snippet.setSearchPath("luts")
    snippet.addDisplayView("sRGB - Display", "Raw", "Raw", "")
    snippet.validate()
    return snippet


def write_family_yaml(path: Path, data: dict) -> None:
    path.write_text(
        yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


def copy_luts(refs: list[str], dest_luts: Path) -> None:
    dest_luts.mkdir(parents=True, exist_ok=True)
    for ref in refs:
        if ".." in ref or Path(ref).is_absolute():
            raise ValueError(f"Unsafe LUT path: {ref!r}")
        src = TRANSFORMS_DIR / ref
        if not src.is_file():
            raise FileNotFoundError(f"Missing LUT in FACES transforms: {src}")
        dst = dest_luts / Path(ref).name
        shutil.copy2(src, dst)


def main() -> None:
    if not FACES_OCIO.is_file():
        raise SystemExit(f"FACES config not found: {FACES_OCIO}")
    if not TRANSFORMS_DIR.is_dir():
        raise SystemExit(f"Transforms dir not found: {TRANSFORMS_DIR}")

    faces = OCIO.Config.CreateFromFile(str(FACES_OCIO))

    packages: list[tuple[str, str, str, dict, tuple[str, ...], list[str]]] = [
        (
            "arri",
            "ARRI : ",
            "ARRI LogC2 video display-referred views (FACES)",
            ARRI_DISPLAY_MAPPINGS,
            (),
            [],
        ),
        (
            "davinci",
            "DaVinci : ",
            "DaVinci DWG display-referred views (FACES)",
            DAVINCI_DISPLAY_MAPPINGS,
            (),
            [],
        ),
        (
            "filmlight",
            "FilmLight : ",
            "FilmLight T-Log / E-Gamut 2 display-referred views (FACES)",
            FILMLIGHT_DISPLAY_MAPPINGS,
            (
                "FilmLight : Linear : E-Gamut 2",
                "FilmLight : T-Log : E-Gamut 2",
            ),
            ["ACES_lin_2_FilmLight_Linear_EGamut2.spimtx"],
        ),
        (
            "red_ipp2",
            "RED-IPP2 : ",
            "RED IPP2 RWG Log3G10 display-referred views (FACES)",
            RED_IPP2_DISPLAY_MAPPINGS,
            (),
            [],
        ),
    ]

    for dir_name, prefix, description, mappings, intermediates, extra_lut_basenames in packages:
        fam_dir = FAMILIES_ROOT / dir_name
        fam_dir.mkdir(parents=True, exist_ok=True)
        luts_dir = fam_dir / "luts"
        if luts_dir.exists():
            shutil.rmtree(luts_dir)

        vnames = [cs.getName() for cs in faces.getColorSpaces() if cs.getName().startswith(prefix)]
        vnames = list(vnames) + list(intermediates)
        closure = closure_for_cs(faces, vnames)
        lut_refs = collect_lut_refs_for_names(faces, closure)
        for base in extra_lut_basenames:
            if base not in lut_refs:
                lut_refs = sorted(set(lut_refs) | {base})

        copy_luts(lut_refs, luts_dir)

        snippet = build_snippet_config(faces, prefix, intermediates)
        out_ocio = fam_dir / "colorspaces.ocio"
        out_ocio.write_text(snippet.serialize(), encoding="utf-8")
        OCIO.Config.CreateFromFile(str(out_ocio))  # load check

        manifest = {
            "schema_version": 1,
            "family": dir_name,
            "description": description,
            "depends_on": [],
            "display_mappings": mappings,
            "intermediates": list(intermediates),
        }
        write_family_yaml(fam_dir / "family.yaml", manifest)

        print(f"OK {dir_name}: CS in closure={len(closure)}, LUTs={len(lut_refs)}, snippet={out_ocio}")


if __name__ == "__main__":
    main()
