"""JSON Schema generation for the packaged configuration contract."""

# Schema descriptions intentionally preserve readable prose on single lines.
# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path

from shieldfont.config.models import ShieldFontConfig

SCHEMA_PATH = Path(__file__).with_name("schemas") / "shieldfont-v1.schema.json"

FIELD_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "ShieldFontConfig": {
        "project": "Controls the project identity and output location.",
        "source": "Controls which source font is inspected and accepted by the build.",
        "font": "Controls generated font metadata, formats, and the neutral face.",
        "layout": "Controls OpenType feature selection and GSUB lookup layout.",
        "scopes": "Defines the locale, script, language, and dictionary partitions used by mappings.",
        "mapping": "Controls how dictionary mappings are interpreted and how conflicts are handled.",
        "protection": "Controls additive mapping-contract, document-subset, cache-identity, and privacy behavior.",
        "css": "Controls the generated stylesheet, font loading behavior, and CSS class names.",
        "codec": "Controls generated JavaScript codec packages and their runtime scope behavior.",
        "verification": "Controls structural, shaping, codec, and browser verification checks.",
        "license": "Controls how licensing findings affect the build and verification result.",
    },
    "ProjectSection": {
        "id": "Affects the stable project identifier used in reports and artifacts.",
        "version": "Affects the project contract version recorded in generated metadata.",
        "outputDir": "Affects the directory where generated artifacts and reports are published.",
        "reproducible": "Affects whether build inputs and timestamps are normalized for repeatable output.",
        "sourceDateEpoch": "Affects the timestamp used when reproducible output is enabled.",
    },
    "InstanceSection": {
        "axes": "Affects the variable-font axis coordinates used to select the source instance.",
    },
    "SourceSection": {
        "path": "Affects which source font is inspected and used for building.",
        "requiredOutline": "Affects which TrueType outline table is accepted by the build.",
        "allowedContainers": "Affects which source and generated font containers are permitted.",
        "instance": "Affects the variable-font instance selected before inspection and shaping.",
    },
    "NeutralFaceSection": {
        "enabled": "Affects whether a neutral, non-substituting face is generated.",
        "family": "Affects the family name exposed by the generated neutral face.",
    },
    "ShieldFaceSection": {
        "family": "Affects the local family name exposed by the generated ShieldFont face in CSS.",
    },
    "FontSection": {
        "family": "Affects the generated font asset family and filename.",
        "description": "Affects the descriptive metadata embedded in generated fonts.",
        "outputFormats": "Affects which font container formats are emitted.",
        "shieldFace": "Affects the local CSS family name for the generated ShieldFont face.",
        "neutralFace": "Affects the options for the generated neutral face.",
    },
    "LayoutSection": {
        "defaultFeature": "Affects the OpenType feature used when no feature is selected explicitly.",
        "boundaryMode": "Affects how substitutions are applied around protected boundaries.",
        "maxEstimatedSubtableBytes": "Affects the maximum estimated size allowed for a generated GSUB subtable.",
        "useExtensionLookups": "Affects whether large GSUB lookups may use extension lookups.",
        "gsubOptimization": "Affects whether GSUB boundary generation evaluates Format 2 or uses the deterministic Format 3 fallback.",
        "defaultScopePolicy": "Affects behavior when no configured scope matches the current text.",
    },
    "EncoderScopeSection": {
        "locales": "Affects which source locales use this scope during encoding.",
        "sourceScripts": "Affects which source scripts use this scope during encoding.",
    },
    "ShapingScopeSection": {
        "targetScripts": "Affects which target scripts activate this scope during shaping.",
        "openTypeScript": "Affects the OpenType script tag used for this scope.",
        "defaultLanguage": "Affects whether the default OpenType language system is enabled.",
        "languages": "Affects which OpenType language systems activate this scope.",
    },
    "ScopeSection": {
        "id": "Affects the stable identifier used to select and report this scope.",
        "encoder": "Affects locale and source-script matching during encoding.",
        "shaping": "Affects script and language matching during font shaping.",
        "dictionaries": "Affects which dictionary files provide mappings for this scope.",
    },
    "MappingSection": {
        "mode": "Affects the direction and algebraic behavior of dictionary replacements.",
        "duplicatePolicy": "Affects how duplicate source mappings are handled.",
        "targetCollisionPolicy": "Affects how multiple mappings targeting one value are handled.",
        "selfMapPolicy": "Affects how mappings with identical source and target values are handled.",
        "crossScript": "Affects whether mappings may cross writing-system boundaries.",
        "caseMode": "Affects whether matching distinguishes or folds letter case.",
        "normalization": "Affects Unicode normalization applied before mapping.",
    },
    "ProtectionSection": {
        "profile": "Affects whether the build preserves compatibility output or creates a document-bound canonical bundle.",
        "mappingContract": "Affects whether scope dictionaries use legacy CSV/flat mappings or versioned grouped alias contracts.",
        "seed": "Affects deterministic alias selection for versioned mappings; it is omitted from public metadata.",
        "documentNonce": "Affects document-specific alias selection and cache identity; only a digest prefix may be reported.",
        "tenantId": "Affects cache isolation; only an opaque digest may be reported.",
        "inventory": "Affects which source groups are retained in a document-bound subset.",
        "reserveAliases": "Affects how many deterministic future-coverage entries are retained beyond the document inventory.",
        "reserve": "Affects which explicit source or alias entries are retained beyond the document inventory.",
        "scanPublicArtifacts": "Affects whether public artifacts are scanned for private files, paths, timestamps, and mapping hints before publication.",
    },
    "CssClassesSection": {
        "shield": "Affects the CSS class applied to ShieldFont-rendered text.",
        "neutral": "Affects the CSS class applied to neutral-font text.",
    },
    "CssSection": {
        "file": "Affects the output path of the generated CSS stylesheet.",
        "assetBaseUrl": "Affects the URL prefix used to locate generated font assets.",
        "fontDisplay": "Affects how browsers display fallback text while fonts load.",
        "fontSynthesis": "Affects whether browsers may synthesize missing font styles.",
        "embedFont": "Affects whether generated font data is embedded as base64 data URLs in CSS.",
        "classes": "Affects the CSS class names emitted for generated text styles.",
    },
    "CodecSection": {
        "packageName": "Affects the package name written into generated codec metadata.",
        "formats": "Affects which JavaScript module formats are emitted by the codec build.",
        "browserBuild": "Affects whether a browser-oriented codec build is emitted.",
        "embedMappings": "Affects whether mapping data is embedded directly in codec output.",
        "unknownScopePolicy": "Affects codec behavior when the requested scope is unknown.",
    },
    "HarfBuzzSection": {
        "implementation": "Affects which HarfBuzz implementation is used for shaping verification.",
    },
    "VerificationSection": {
        "levels": "Affects which structural, shaping, codec, and browser checks are run.",
        "harfbuzz": "Affects the HarfBuzz backend settings used by shaping checks.",
        "browsers": "Affects which browser engines execute browser verification.",
        "failOnWarning": "Affects whether verification warnings fail the overall verification.",
    },
    "LicenseSection": {
        "policy": "Affects whether license findings are ignored, reported, or treated as errors.",
    },
}

SECTION_DESCRIPTIONS = {
    "ShieldFontConfig": "Defines the complete ShieldFont Toolchain project configuration.",
    "ProjectSection": "Defines project identity, output location, and reproducibility settings.",
    "InstanceSection": "Defines variable-font coordinates used for source inspection.",
    "SourceSection": "Defines the source font and the input constraints for the build.",
    "NeutralFaceSection": "Defines the optional neutral face generated alongside ShieldFont.",
    "ShieldFaceSection": "Defines the local CSS family name for the generated ShieldFont face.",
    "FontSection": "Defines generated font metadata, formats, and neutral-face settings.",
    "LayoutSection": "Defines OpenType feature and GSUB lookup layout behavior.",
    "EncoderScopeSection": "Defines source-side locale and script matching for a scope.",
    "ShapingScopeSection": "Defines target-side script and language matching for a scope.",
    "ScopeSection": "Defines one mapping scope and the dictionaries that populate it.",
    "MappingSection": "Defines mapping direction, conflict handling, and text normalization.",
    "ProtectionSection": "Defines compatibility and document-bound mapping, subset, identity, and artifact privacy behavior.",
    "CssClassesSection": "Defines CSS class names emitted for generated font styles.",
    "CssSection": "Defines generated stylesheet and browser font-loading behavior.",
    "CodecSection": "Defines generated JavaScript codec package formats and policies.",
    "HarfBuzzSection": "Defines the HarfBuzz backend used by shaping verification.",
    "VerificationSection": "Defines the verification levels and runtimes used after building.",
    "LicenseSection": "Defines how licensing findings are reported or enforced.",
}


def _apply_field_descriptions(schema: dict[str, object]) -> None:
    definitions = schema.get("$defs", {})
    containers: dict[str, object] = {"ShieldFontConfig": schema}
    if isinstance(definitions, dict):
        containers.update(definitions)
    for definition_name, descriptions in FIELD_DESCRIPTIONS.items():
        definition = containers.get(definition_name)
        if not isinstance(definition, dict):
            continue
        section_description = SECTION_DESCRIPTIONS.get(definition_name)
        if section_description:
            definition["description"] = section_description
        properties = definition.get("properties", {})
        if not isinstance(properties, dict):
            continue
        for property_name, description in descriptions.items():
            property_schema = properties.get(property_name)
            if isinstance(property_schema, dict):
                property_schema["description"] = description


def generate_schema() -> dict[str, object]:
    """Return the canonical ``shieldfont/v1`` JSON Schema."""

    schema = ShieldFontConfig.model_json_schema(by_alias=True)
    schema["$id"] = "https://shieldfont.dev/schema/shieldfont-v1.schema.json"
    schema["title"] = "ShieldFont Toolchain configuration"
    schema["properties"]["schema"]["description"] = (
        "Affects the configuration contract selected by this project file."
    )
    _apply_field_descriptions(schema)
    return schema


def write_schema(path: Path = SCHEMA_PATH) -> None:
    """Write the canonical schema using stable JSON formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(generate_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_schema()
