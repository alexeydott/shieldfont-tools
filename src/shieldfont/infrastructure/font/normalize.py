"""fontTools-backed variable instancing and metadata normalization."""

from __future__ import annotations

import re
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError  # type: ignore[import-untyped]
from fontTools.varLib.instancer import (  # type: ignore[import-untyped]
    instantiateVariableFont,
)

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.font_normalization import FontNormalizationResult

_POSTSCRIPT_RE = re.compile(r"^[A-Za-z0-9-]+$")
_VARIATION_TABLES = {"fvar", "gvar", "HVAR", "VVAR", "MVAR", "avar"}


def _name(font: TTFont, name_id: int, fallback: str = "") -> str:
    value = font["name"].getDebugName(name_id) if "name" in font else None
    return value or fallback


def _set_name(font: TTFont, name_id: int, value: str) -> None:
    if "name" not in font:
        return
    name_table = font["name"]
    name_table.names = [
        record for record in name_table.names if record.nameID != name_id
    ]
    name_table.setName(value, name_id, 3, 1, 0x409)
    name_table.setName(value, name_id, 1, 0, 0)


def _resolve_axes(
    font: TTFont,
    *,
    axes: dict[str, float] | None,
    named_instance: str | None,
) -> dict[str, float]:
    fvar = font.get("fvar")
    if fvar is None:
        if axes or named_instance:
            raise ShieldFontError(
                "An instance or axes were requested for a static font",
                code=ErrorCode.FONT_NORMALIZATION,
                exit_code=ExitCode.INVALID_INPUT,
                stage="font.normalize",
                details={"axes": axes or {}, "namedInstance": named_instance},
            )
        return {}
    defaults = {axis.axisTag: float(axis.defaultValue) for axis in fvar.axes}
    if named_instance:
        matches = [
            instance
            for instance in fvar.instances
            if _name(font, instance.subfamilyNameID) == named_instance
        ]
        if len(matches) != 1:
            raise ShieldFontError(
                "Named font instance was not found uniquely",
                code=ErrorCode.FONT_NORMALIZATION,
                exit_code=ExitCode.INVALID_INPUT,
                stage="font.normalize",
                details={
                    "namedInstance": named_instance,
                    "matches": len(matches),
                },
            )
        defaults.update(
            {tag: float(value) for tag, value in matches[0].coordinates.items()}
        )
    if axes:
        unknown = sorted(set(axes) - set(defaults))
        if unknown:
            raise ShieldFontError(
                "Unknown variation axis",
                code=ErrorCode.FONT_NORMALIZATION,
                exit_code=ExitCode.INVALID_INPUT,
                stage="font.normalize",
                details={"axes": unknown},
            )
        defaults.update(axes)
    return defaults


def normalize_font(
    input_path: Path,
    output_path: Path,
    *,
    family: str,
    subfamily: str,
    post_script_name: str | None = None,
    axes: dict[str, float] | None = None,
    named_instance: str | None = None,
    license_policy: str = "warn",
    drop_dsig: bool = True,
) -> FontNormalizationResult:
    """Create a static TrueType derivative with validated metadata."""

    source = input_path.resolve()
    destination = output_path.resolve()
    if source.suffix.lower() not in {".ttf", ".woff2"}:
        raise ShieldFontError(
            "Only TTF and WOFF2 inputs are supported for normalization",
            code=ErrorCode.FONT_UNSUPPORTED,
            exit_code=ExitCode.UNSUPPORTED_FONT,
            stage="font.normalize",
            details={"path": str(source)},
        )
    if not family.strip() or not subfamily.strip():
        raise ShieldFontError(
            "Font family and subfamily must not be empty",
            code=ErrorCode.FONT_METADATA,
            exit_code=ExitCode.INVALID_INPUT,
            stage="font.normalize",
            details={},
        )
    if license_policy not in {"warn", "error", "ignore"}:
        raise ShieldFontError(
            "Unsupported license policy",
            code=ErrorCode.INVALID_INPUT,
            exit_code=ExitCode.INVALID_INPUT,
            stage="font.normalize",
            details={"licensePolicy": license_policy},
        )
    post_name = post_script_name or (
        f"{re.sub(r'[^A-Za-z0-9-]', '', family)}-"
        f"{re.sub(r'[^A-Za-z0-9-]', '', subfamily)}"
    )
    if (
        len(post_name) > 63
        or not post_name
        or not _POSTSCRIPT_RE.fullmatch(post_name)
    ):
        raise ShieldFontError(
            "PostScript name contains unsupported characters",
            code=ErrorCode.FONT_METADATA,
            exit_code=ExitCode.INVALID_INPUT,
            stage="font.normalize",
            details={"postScriptName": post_name},
        )
    try:
        font = TTFont(source, lazy=False)
    except (OSError, TTLibError) as error:
        raise ShieldFontError(
            "Unable to load font for normalization",
            code=ErrorCode.FONT_NORMALIZATION,
            exit_code=ExitCode.SOURCE_FONT_ERROR,
            stage="font.normalize",
            details={"path": str(source), "reason": str(error)},
        ) from error
    removed_tables: list[str] = []
    warnings: list[str] = []
    try:
        if "glyf" not in font:
            raise ShieldFontError(
                "Font normalization requires TrueType glyf outlines",
                code=ErrorCode.FONT_UNSUPPORTED,
                exit_code=ExitCode.UNSUPPORTED_FONT,
                stage="font.normalize",
                details={"path": str(source)},
            )
        license_text = _name(font, 13)
        if "Reserved Font Name" in license_text:
            message = "Source font contains a Reserved Font Name"
            if license_policy == "error":
                raise ShieldFontError(
                    message,
                    code=ErrorCode.FONT_LICENSE,
                    exit_code=ExitCode.LICENSING_POLICY_ERROR,
                    stage="font.normalize",
                    details={"licensePolicy": license_policy},
                )
            if license_policy == "warn":
                warnings.append(message)
        selected_axes = _resolve_axes(
            font,
            axes=axes,
            named_instance=named_instance,
        )
        variable_input = "fvar" in font
        if variable_input:
            font = instantiateVariableFont(font, selected_axes, inplace=False)
            for table_name in sorted(_VARIATION_TABLES):
                if table_name in font:
                    del font[table_name]
                    removed_tables.append(table_name)
        if drop_dsig and "DSIG" in font:
            del font["DSIG"]
            removed_tables.append("DSIG")
        _set_name(font, 1, family)
        _set_name(font, 2, subfamily)
        _set_name(font, 4, f"{family} {subfamily}")
        _set_name(font, 3, f"{family};{subfamily};{post_name}")
        _set_name(font, 6, post_name)
        _set_name(font, 16, family)
        _set_name(font, 17, subfamily)
        destination.parent.mkdir(parents=True, exist_ok=True)
        font.save(destination)
    except ShieldFontError:
        raise
    except (OSError, TTLibError, ValueError) as error:
        raise ShieldFontError(
            "Unable to normalize font",
            code=ErrorCode.FONT_NORMALIZATION,
            exit_code=ExitCode.FONT_SERIALIZATION_ERROR,
            stage="font.normalize",
            details={"path": str(destination), "reason": str(error)},
        ) from error
    finally:
        font.close()
    return FontNormalizationResult(
        input_path=str(source),
        output_path=str(destination),
        variable_input=variable_input,
        instanced=variable_input,
        selected_axes=selected_axes,
        family=family,
        subfamily=subfamily,
        post_script_name=post_name,
        removed_tables=tuple(removed_tables),
        warnings=tuple(warnings),
    )
