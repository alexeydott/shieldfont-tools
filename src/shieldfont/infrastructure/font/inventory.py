"""Font inspection and diagnostic unpack application services."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError  # type: ignore[import-untyped]

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.font_inventory import FontInspection


def _name(font: TTFont, name_id: int, fallback: str = "") -> str:
    value = font["name"].getDebugName(name_id) if "name" in font else None
    return value or fallback


def _scripts(codepoints: set[int]) -> tuple[str, ...]:
    ranges = {
        "Latn": ((0x0041, 0x024F),),
        "Cyrl": ((0x0400, 0x052F),),
        "Grek": ((0x0370, 0x03FF),),
        "Hebr": ((0x0590, 0x05FF),),
        "Arab": ((0x0600, 0x06FF),),
        "Deva": ((0x0900, 0x097F),),
        "Hans": ((0x4E00, 0x9FFF),),
    }
    return tuple(
        script
        for script, script_ranges in ranges.items()
        if any(
            start <= codepoint <= end
            for codepoint in codepoints
            for start, end in script_ranges
        )
    )


def _layout_inventory(
    font: TTFont,
    table_name: str,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    if table_name not in font:
        return (), {}
    table = font[table_name].table
    feature_tags = tuple(
        sorted(
            {
                record.FeatureTag
                for record in getattr(
                    getattr(table, "FeatureList", None),
                    "FeatureRecord",
                    [],
                )
            }
        )
    )
    scripts_languages: dict[str, tuple[str, ...]] = {}
    script_list = getattr(getattr(table, "ScriptList", None), "ScriptRecord", [])
    for script_record in script_list:
        script = script_record.ScriptTag
        script_table = script_record.Script
        languages = []
        if script_table.DefaultLangSys is not None:
            languages.append("DFLT")
        languages.extend(
            record.LangSysTag
            for record in getattr(script_table, "LangSysRecord", [])
        )
        scripts_languages[script] = tuple(sorted(languages))
    return feature_tags, scripts_languages


def inspect_font(path: Path, *, strict: bool = False) -> FontInspection:
    """Inspect a TTF/WOFF2 and reject unsupported outline formats."""

    font_path = path.resolve()
    suffix = font_path.suffix.lower()
    if suffix not in {".ttf", ".woff2"}:
        raise ShieldFontError(
            "Only TTF and WOFF2 font containers are supported",
            code=ErrorCode.FONT_UNSUPPORTED,
            exit_code=ExitCode.UNSUPPORTED_FONT,
            stage="font.inspect",
            details={"path": str(font_path), "suffix": suffix},
        )
    try:
        font = TTFont(
            font_path,
            lazy=False,
            checkChecksums=1 if strict else 0,
        )
    except (OSError, TTLibError) as error:
        raise ShieldFontError(
            "Unable to inspect source font",
            code=ErrorCode.FONT_INSPECT_INVALID,
            exit_code=ExitCode.SOURCE_FONT_ERROR,
            stage="font.inspect",
            details={"path": str(font_path), "reason": str(error)},
        ) from error
    try:
        has_glyf = "glyf" in font
        if not has_glyf:
            raise ShieldFontError(
                "Font does not contain TrueType glyf outlines",
                code=ErrorCode.FONT_UNSUPPORTED,
                exit_code=ExitCode.UNSUPPORTED_FONT,
                stage="font.inspect",
                details={"path": str(font_path), "tables": sorted(font.keys())},
            )
        cmap = font.getBestCmap() or {}
        axes = {
            axis.axisTag: float(axis.defaultValue)
            for axis in getattr(font.get("fvar"), "axes", [])
        }
        instances = tuple(
            {
                "subfamily": _name(font, instance.subfamilyNameID),
                "coordinates": {
                    tag: float(value) for tag, value in instance.coordinates.items()
                },
            }
            for instance in getattr(font.get("fvar"), "instances", [])
        )
        gsub_features, scripts_languages = _layout_inventory(font, "GSUB")
        gpos_features, gpos_scripts = _layout_inventory(font, "GPOS")
        for script, languages in gpos_scripts.items():
            scripts_languages.setdefault(script, languages)
        warnings = []
        license_names = {
            "license": _name(font, 13),
            "licenseUrl": _name(font, 14),
        }
        if "Reserved Font Name" in license_names["license"]:
            warnings.append("name ID 13 contains Reserved Font Name")
        return FontInspection(
            path=str(font_path),
            container="woff2" if suffix == ".woff2" else "ttf",
            sfnt_version=str(font.sfntVersion),
            tables=tuple(sorted(font.keys())),
            has_glyf=True,
            variable="fvar" in font,
            axes=axes,
            instances=instances,
            names={
                "family": _name(font, 1, font_path.stem),
                "subfamily": _name(font, 2, "Regular"),
                "postScript": _name(font, 6),
            },
            cmap_codepoints=tuple(sorted(cmap)),
            scripts=_scripts(set(cmap)),
            glyph_count=len(font.getGlyphOrder()),
            gsub_features=gsub_features,
            gpos_features=gpos_features,
            scripts_languages={
                script: scripts_languages[script]
                for script in sorted(scripts_languages)
            },
            license_names=license_names,
            has_dsig="DSIG" in font,
            planned_changes=("glyf", "hmtx", "GSUB", "name", "head", "maxp"),
            warnings=tuple(warnings),
        )
    finally:
        font.close()


def unpack_font(path: Path, output_dir: Path) -> Path:
    """Write deterministic diagnostic decomposition files for an input font."""

    inspection = inspect_font(path)
    output = output_dir.resolve()
    layout_dir = output / "layout"
    glyph_dir = output / "glyphs"
    layout_dir.mkdir(parents=True, exist_ok=True)
    glyph_dir.mkdir(parents=True, exist_ok=True)
    output.joinpath("tables.json").write_text(
        json.dumps(
            {"tables": list(inspection.tables), "inspection": inspection.to_dict()},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    output.joinpath("names.json").write_text(
        json.dumps(
            inspection.names,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with output.joinpath("cmap.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["codePoint"])
        writer.writerows((f"U+{value:04X}",) for value in inspection.cmap_codepoints)
    font = TTFont(path.resolve(), lazy=False)
    try:
        font.saveXML(str(output / "font.ttx"))
        with glyph_dir.joinpath("glyph-order.txt").open(
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("\n".join(font.getGlyphOrder()) + "\n")
        with glyph_dir.joinpath("metrics.csv").open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["glyph", "advanceWidth", "lsb"])
            hmtx = font["hmtx"].metrics
            writer.writerows(
                (glyph, hmtx[glyph][0], hmtx[glyph][1])
                for glyph in font.getGlyphOrder()
            )
        for table_name in ("GSUB", "GPOS"):
            if table_name in font:
                font.saveXML(
                    str(layout_dir / f"{table_name.lower()}.ttx"),
                    tables=[table_name],
                )
    finally:
        font.close()
    layout_payload = {
        "gsub": list(inspection.gsub_features),
        "gpos": list(inspection.gpos_features),
        "scriptsLanguages": {
            script: list(languages)
            for script, languages in inspection.scripts_languages.items()
        },
    }
    (layout_dir / "feature-inventory.json").write_text(
        json.dumps(
            layout_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return output
