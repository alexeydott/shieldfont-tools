"""fontTools feaLib adapter for compiling generated feature source."""

from __future__ import annotations

from pathlib import Path

from fontTools.feaLib.builder import addOpenTypeFeatures  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont, TTLibError  # type: ignore[import-untyped]
from fontTools.ttLib.tables import otTables  # type: ignore[import-untyped]

from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError


def gsub_optimization_diagnostics(
    *,
    boundary_glyphs: int,
    substituted_glyphs: int,
    optimization: str,
) -> dict[str, object]:
    """Select the validated Format 3 path and report any Format 2 fallback."""

    format2_estimate = 96 + (boundary_glyphs + substituted_glyphs) * 2
    format3_estimate = 64 + (boundary_glyphs + substituted_glyphs) * 4
    class_candidate = optimization in {"auto", "format2"} and (
        optimization == "format2" or format2_estimate < format3_estimate
    )
    return {
        "requested": optimization,
        "selected": "format3",
        "fallback": (
            "shaping-validation-required"
            if class_candidate
            else "not-required"
        ),
        "format2EstimatedBytes": format2_estimate,
        "format3EstimatedBytes": format3_estimate,
        "boundaryGlyphs": boundary_glyphs,
        "substitutedGlyphs": substituted_glyphs,
    }


def compile_feature_source(font: TTFont, feature_path: Path) -> None:
    """Compile a generated feature source into an in-memory TrueType font."""

    try:
        addOpenTypeFeatures(font, str(feature_path.resolve()))
    except (OSError, TTLibError, ValueError) as error:
        raise ShieldFontError(
            "Unable to compile OpenType feature source",
            code=ErrorCode.GSUB_COMPILE_ERROR,
            exit_code=ExitCode.GSUB_COMPILE_ERROR,
            stage="gsub.compile",
            details={"featurePath": str(feature_path.resolve()), "reason": str(error)},
        ) from error


def add_fire_then_revert_context(
    font: TTFont,
    *,
    lookup_indices: tuple[int, int, int, int],
    generated_glyphs: set[str],
    optimization: str = "auto",
) -> dict[str, object]:
    """Make the two generated reverter lookups conditional on letter context."""

    if not generated_glyphs or "GSUB" not in font:
        return {
            "requested": optimization,
            "selected": "format3",
            "fallback": "empty-generated-set",
            "format2EstimatedBytes": 0,
            "format3EstimatedBytes": 0,
        }
    table = font["GSUB"].table
    lookups = table.LookupList.Lookup
    ligature_index, multiple_index, before_index, after_index = lookup_indices
    if max(lookup_indices) >= len(lookups):
        raise ShieldFontError(
            "Compiled GSUB lookup indices are out of range",
            code=ErrorCode.GSUB_COMPILE_ERROR,
            exit_code=ExitCode.GSUB_COMPILE_ERROR,
            stage="gsub.compile",
            details={
                "lookupIndices": list(lookup_indices),
                "lookupCount": len(lookups),
            },
        )
    if lookups[ligature_index].LookupType != 4:
        raise ShieldFontError(
            "Compiled GSUB ligature lookup has an unexpected type",
            code=ErrorCode.GSUB_COMPILE_ERROR,
            exit_code=ExitCode.GSUB_COMPILE_ERROR,
            stage="gsub.compile",
            details={"lookupIndex": ligature_index},
        )
    if lookups[multiple_index].LookupType != 2:
        raise ShieldFontError(
            "Compiled GSUB reversion lookup has an unexpected type",
            code=ErrorCode.GSUB_COMPILE_ERROR,
            exit_code=ExitCode.GSUB_COMPILE_ERROR,
            stage="gsub.compile",
            details={"lookupIndex": multiple_index},
        )

    cmap = font.getBestCmap() or {}
    glyph_order = font.getGlyphOrder()
    glyph_set = set(glyph_order)
    letter_glyphs = {
        glyph_name
        for codepoint, glyph_name in cmap.items()
        if chr(codepoint).isalpha() and glyph_name in glyph_set
    }
    boundary_glyphs = letter_glyphs | generated_glyphs
    substituted_glyphs = generated_glyphs & glyph_set
    if not boundary_glyphs or not substituted_glyphs:
        return {
            "requested": optimization,
            "selected": "format3",
            "fallback": "empty-boundary-set",
            "format2EstimatedBytes": 0,
            "format3EstimatedBytes": 0,
        }

    diagnostics = gsub_optimization_diagnostics(
        boundary_glyphs=len(boundary_glyphs),
        substituted_glyphs=len(substituted_glyphs),
        optimization=optimization,
    )

    def chain_lookup(*, before: bool) -> otTables.Lookup:
        chain = otTables.ChainContextSubst()
        chain.Format = 3
        boundary = otTables.Coverage()
        boundary.glyphs = sorted(boundary_glyphs, key=font.getGlyphID)
        substituted = otTables.Coverage()
        substituted.glyphs = sorted(substituted_glyphs, key=font.getGlyphID)
        chain.BacktrackCoverage = [boundary] if before else []
        chain.BacktrackGlyphCount = len(chain.BacktrackCoverage)
        chain.InputCoverage = [substituted]
        chain.InputGlyphCount = 1
        chain.LookAheadCoverage = [] if before else [boundary]
        chain.LookAheadGlyphCount = len(chain.LookAheadCoverage)
        record = otTables.SubstLookupRecord()
        record.SequenceIndex = 0
        record.LookupListIndex = multiple_index
        chain.SubstLookupRecord = [record]
        chain.SubstCount = 1
        lookup = otTables.Lookup()
        lookup.LookupType = 6
        lookup.LookupFlag = 0
        lookup.SubTable = [chain]
        lookup.SubTableCount = 1
        return lookup

    lookups[before_index] = chain_lookup(before=True)
    lookups[after_index] = chain_lookup(before=False)
    return diagnostics
