"""Project initialization use case."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from shieldfont.config.models import (
    EncoderScopeSection,
    FontSection,
    InstanceSection,
    MappingSection,
    NeutralFaceSection,
    ProjectSection,
    ScopeSection,
    ShapingScopeSection,
    ShieldFaceSection,
    ShieldFontConfig,
    SourceSection,
)
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.domain.font import FontSummary
from shieldfont.domain.font_naming import neutral_family_name, shield_family_name
from shieldfont.infrastructure.logging import log_event

LOGGER = logging.getLogger("shieldfont.init")
_SCRIPT_NAMES = {"DFLT": "default", "latn": "latin", "cyrl": "cyrillic"}
FONT_FAMILY_POSTFIX = "_shld"
PROFILE_HEADER = """# ShieldFont Toolchain generation profile.
# Edit the values below to control the generated font and delivery artifacts.
# Paths are relative to this shieldfont.yml file unless an absolute path is used.
#
# schema: profile format version; it selects the validation contract.
# project: project identity, reproducibility, and the default output directory.
# source: input font, accepted containers, and variable-font instance axes.
# font: generated family names, descriptions, and TTF/WOFF2 output formats.
# layout: OpenType feature and lookup-size policies used during font building.
# scopes: per-script processing scopes, shaping settings, and dictionaries.
# mapping: dictionary conflict, case, normalization, and cross-script policies.
# css: generated CSS path, URL/font-display behavior, and optional embedding.
# codec: JavaScript codec package formats and whether browser assets are built.
# verification: enabled verification levels, HarfBuzz, browsers, and warnings.
# license: behavior when source-font licensing metadata does not satisfy policy.
#
# Changing source, scopes, mapping, or layout changes generated glyphs/features.
# Changing font changes font naming and manifest metadata. Changing css or codec
# changes delivery assets. Changing verification changes checks performed, not
# the font itself. The CLI can override the main inputs without editing this file.
"""
PROFILE_FIELD_COMMENTS = {
    "schema": "Profile contract version used for validation.",
    "project": "Project identity and output/reproducibility settings.",
    "id": "Stable identifier used in manifests and scope records.",
    "version": "Version written to generated font metadata and the manifest.",
    "outputDir": "Default atomic publication directory for generated artifacts.",
    "reproducible": "Keep build serialization deterministic when enabled.",
    "sourceDateEpoch": (
        "Optional timestamp used to make generated metadata reproducible."
    ),
    "source": "Source-font input and variable-font selection settings.",
    "path": "Input font path; changing it changes the source glyph inventory.",
    "requiredOutline": (
        "Required outline technology; glyf is the supported TrueType outline."
    ),
    "allowedContainers": "Accepted source containers before normalization.",
    "instance": "Variable-font instance selection applied before generation.",
    "axes": "Axis values such as wght or wdth used for the normalized instance.",
    "font": "Generated font naming, description, and output container settings.",
    "family": (
        "Generated family name; affects font filenames, names, and manifest metadata."
    ),
    "description": "Human-readable description stored with generated project metadata.",
    "outputFormats": "Font containers to publish, normally ttf and/or woff2.",
    "shieldFace": "CSS-visible ShieldFont face naming.",
    "neutralFace": "Optional unchanged comparison face and its CSS family name.",
    "enabled": "Whether the neutral comparison font is generated.",
    "layout": "OpenType feature generation and lookup safety policies.",
    "defaultFeature": "Feature tag that receives generated mapping lookups.",
    "boundaryMode": "Lookup boundary behavior used around transformed text.",
    "maxEstimatedSubtableBytes": "Safety limit for generated OpenType subtables.",
    "useExtensionLookups": (
        "Permit extension lookups when ordinary lookup space is insufficient."
    ),
    "defaultScopePolicy": "Behavior when text does not match a configured scope.",
    "scopes": "Independent dictionary and shaping pipelines for scripts/locales.",
    "encoder": "Input-side locale and source-script selection for a scope.",
    "locales": "Locales accepted by the scope's encoder.",
    "sourceScripts": "Unicode/script sources eligible for the scope.",
    "shaping": "OpenType script/language settings for the generated scope.",
    "targetScripts": "Scripts targeted by shaping rules.",
    "openTypeScript": "Four-character OpenType script tag for generated lookups.",
    "defaultLanguage": "Whether the scope is used as the default language system.",
    "languages": "OpenType language tags associated with the scope.",
    "dictionaries": (
        "CSV mappings consumed by the scope; they change generated substitutions."
    ),
    "mapping": "Dictionary interpretation and conflict policies.",
    "mode": "Mapping direction semantics: directed, bidirectional, or involution.",
    "duplicatePolicy": "Resolution when a source appears more than once.",
    "targetCollisionPolicy": "Resolution when multiple sources produce one target.",
    "selfMapPolicy": "Handling of mappings whose source and target are identical.",
    "crossScript": "Allow mappings that cross script boundaries.",
    "caseMode": "Case handling before dictionary matching.",
    "normalization": "Unicode normalization applied before matching.",
    "css": "CSS delivery settings generated beside the font assets.",
    "file": "Configured CSS filename; the build currently publishes shieldfont.css.",
    "assetBaseUrl": "URL prefix used by generated @font-face declarations.",
    "fontDisplay": "CSS font-display value controlling browser font loading behavior.",
    "fontSynthesis": "CSS font-synthesis policy for the generated faces.",
    "embedFont": "Embed font data in CSS instead of referencing external font files.",
    "classes": "CSS class names emitted for ShieldFont and neutral text faces.",
    "shield": "CSS class selecting the generated ShieldFont face.",
    "neutral": "CSS class selecting the neutral comparison face.",
    "codec": "JavaScript codec package and browser-delivery settings.",
    "packageName": "Package name used by generated codec metadata.",
    "formats": "JavaScript module formats to emit.",
    "browserBuild": "Include browser codec assets in the generated delivery set.",
    "embedMappings": "Embed mapping data in codec output when enabled.",
    "unknownScopePolicy": "Codec behavior for an unknown scope identifier.",
    "verification": "Post-build verification levels and failure policy.",
    "levels": "Verification stages such as structural, shaping, codec, and browser.",
    "harfbuzz": "HarfBuzz implementation used by shaping verification.",
    "implementation": "HarfBuzz backend selection: uharfbuzz, binary, or both.",
    "browsers": "Browsers used by browser verification.",
    "failOnWarning": "Treat verification warnings as build failures when enabled.",
    "license": "Source-font license metadata policy.",
    "policy": "warn, error, or ignore behavior for license checks.",
}
DEFAULT_DICTIONARY_CSV = """source,target
чудное,тягостная
мгновенье,вечность
мимолетное,неотступная
виденье,явь
гений,посредственность
чистой,порочной
красоты,безобразности
грусти,радости
безнадежной,обнадеживающей
тревогах,покое
шумной,безмолвной
суеты,умиротворения
голос,молчание
нежный,суровый
милые,отталкивающие
черты,безликость
бурь,штиля
порыв,покой
мятежный,покорный
прежние,нынешние
мечты,действительность
небесные,земные
мраке,свете
заточенья,освобожденья
без,с
божества,безбожия
вдохновенья,опустошения
слез,бесчувствия
жизни,смерти
любви,ненависти
душе,телу
настало,миновало
пробужденье,угасание
сердце,бесчувствие
бьется,замирает
в,вне
упоенье,отчаянье
воскресли,угасли
вновь,навсегда
божество,безбожие
вдохновенье,опустошение
жизнь,смерть
любовь,ненависть
"""
DEFAULT_DEMO_CORPUS = """Я помню чудное мгновенье:
Передо мной явилась ты,
Как мимолетное виденье,
Как гений чистой красоты.

В томленьях грусти безнадежной,
В тревогах шумной суеты,
Звучал мне долго голос нежный
И снились милые черты.

Шли годы. Бурь порыв мятежный
Рассеял прежние мечты,
И я забыл твой голос нежный,
Твои небесные черты.

В глуши, во мраке заточенья
Тянулись тихо дни мои
Без божества, без вдохновенья,
Без слез, без жизни, без любви.

Душе настало пробужденье:
И вот опять явилась ты,
Как мимолетное виденье,
Как гений чистой красоты.

И сердце бьется в упоенье,
И для него воскресли вновь
И божество, и вдохновенье,
И жизнь, и слезы, и любовь.
"""


def _serialize_profile(config: ShieldFontConfig) -> str:
    """Serialize a generated profile with editable field documentation."""

    serialized = yaml.safe_dump(
        config.model_dump(mode="json", by_alias=True, exclude_none=True),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    lines = [PROFILE_HEADER.rstrip()]
    for line in serialized.splitlines():
        match = re.match(r"^(?P<indent>\s*)(?P<key>[A-Za-z][A-Za-z0-9_-]*):", line)
        if match:
            comment = PROFILE_FIELD_COMMENTS.get(match.group("key"))
            if comment:
                indent = match.group("indent")
                lines.append(f"{indent}# {comment}")
        lines.append(line)
    return "\n".join(lines) + "\n"


class FontInspector(Protocol):
    """Port used to inspect an optional source font."""

    def __call__(self, path: Path) -> FontSummary: ...


@dataclass(frozen=True, slots=True)
class InitRequest:
    """Inputs for creating a ShieldFont project."""

    project_dir: Path
    font_path: Path | None = None
    family: str | None = None
    postfix: str = FONT_FAMILY_POSTFIX
    scripts: tuple[str, ...] = ("DFLT",)
    force: bool = False


def ensure_default_dictionary(project_dir: Path) -> Path | None:
    """Create the requested default dictionary only when no dictionary files exist."""

    dictionaries_dir = project_dir.resolve() / "dictionaries"
    dictionaries_dir.mkdir(parents=True, exist_ok=True)
    if any(path.is_file() for path in dictionaries_dir.rglob("*")):
        return None

    dictionary_path = dictionaries_dir / "default.csv"
    dictionary_path.write_text(DEFAULT_DICTIONARY_CSV, encoding="utf-8")
    log_event(
        LOGGER,
        logging.INFO,
        "Created default dictionary",
        code="SF-INIT-DICTIONARY",
        stage="init.write",
        details={"path": str(dictionary_path)},
    )
    return dictionary_path


def ensure_demo_corpus(project_dir: Path) -> Path | None:
    """Create the demo corpus only when the texts directory has no files."""

    texts_dir = project_dir.resolve() / "texts"
    texts_dir.mkdir(parents=True, exist_ok=True)
    if any(path.is_file() for path in texts_dir.rglob("*")):
        return None

    corpus_path = texts_dir / "demo.txt"
    corpus_path.write_text(DEFAULT_DEMO_CORPUS, encoding="utf-8")
    log_event(
        LOGGER,
        logging.INFO,
        "Created demo corpus",
        code="SF-INIT-DEMO-CORPUS",
        stage="init.write",
        details={"path": str(corpus_path)},
    )
    return corpus_path


def _build_scopes(scripts: tuple[str, ...]) -> list[ScopeSection]:
    scopes: list[ScopeSection] = []
    for script in scripts:
        scope_name = _SCRIPT_NAMES.get(script, script.lower())
        scopes.append(
            ScopeSection(
                id=scope_name,
                encoder=EncoderScopeSection(
                    source_scripts=[] if script == "DFLT" else [script.title()]
                ),
                shaping=ShapingScopeSection(open_type_script=script),
                dictionaries=[Path(f"dictionaries/{scope_name}.csv")],
            )
        )
    return scopes


def initialize_project(
    request: InitRequest,
    *,
    inspect_font: FontInspector | None = None,
) -> Path:
    """Create a project template and return the configuration path."""

    project_dir = request.project_dir.resolve()
    config_path = project_dir / "shieldfont.yml"
    if config_path.exists() and not request.force:
        raise ShieldFontError(
            "shieldfont.yml already exists; pass --force to replace it",
            code=ErrorCode.INIT_EXISTS,
            exit_code=ExitCode.INVALID_INPUT,
            stage="init.prepare",
            details={"path": str(config_path)},
        )

    font_summary: FontSummary | None = None
    source_name = "Source.ttf"
    source_path = request.font_path.resolve() if request.font_path else None
    if source_path is not None:
        if inspect_font is None:
            raise ShieldFontError(
                "A font inspector is required when --font is used",
                code=ErrorCode.INIT_FONT_INVALID,
                exit_code=ExitCode.SOURCE_FONT_ERROR,
                stage="init.inspect",
            )
        font_summary = inspect_font(source_path)
        if not font_summary.has_glyf:
            raise ShieldFontError(
                "Source font does not contain TrueType glyf outlines",
                code=ErrorCode.INIT_FONT_INVALID,
                exit_code=ExitCode.UNSUPPORTED_FONT,
                stage="init.inspect",
                details={"path": str(source_path)},
            )
        source_name = source_path.name

    postfix = request.postfix.strip()
    if not postfix:
        raise ShieldFontError(
            "Font family postfix must not be empty",
            code=ErrorCode.INVALID_INPUT,
            exit_code=ExitCode.INVALID_INPUT,
            stage="init.naming",
        )
    family = request.family or (
        shield_family_name(font_summary.family, postfix)
        if font_summary
        else "ShieldFont"
    )
    axes = font_summary.axes if font_summary and font_summary.variable else {}
    config = ShieldFontConfig(
        project=ProjectSection(
            id=re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-")
        ),
        source=SourceSection(
            path=Path(".fonts") / source_name,
            instance=InstanceSection(axes=axes),
        ),
        font=FontSection(
            family=family,
            shield_face=ShieldFaceSection(family="ShieldFont"),
            neutral_face=NeutralFaceSection(
                family=(
                    neutral_family_name(font_summary.family)
                    if font_summary
                    else "ShieldFont Text"
                )
            ),
        ),
        mapping=MappingSection(mode="directed"),
        scopes=_build_scopes(request.scripts),
    )

    log_event(
        LOGGER,
        logging.DEBUG,
        "Creating ShieldFont project structure",
        code="SF-INIT-START",
        stage="init.write",
        details={
            "path": str(project_dir),
            "scripts": list(request.scripts),
            "font": source_name if source_path else None,
        },
    )
    project_dir.mkdir(parents=True, exist_ok=True)
    for directory in ("fonts", ".fonts", "dictionaries", "texts", "dist"):
        (project_dir / directory).mkdir(exist_ok=True)
    ensure_default_dictionary(project_dir)
    ensure_demo_corpus(project_dir)
    if source_path is not None:
        destination = project_dir / ".fonts" / source_name
        if source_path != destination:
            shutil.copy2(source_path, destination)

    serialized = _serialize_profile(config)
    config_path.write_text(serialized, encoding="utf-8")
    log_event(
        LOGGER,
        logging.INFO,
        "ShieldFont project initialized",
        code="SF-INIT-COMPLETE",
        stage="init.write",
        details={"config": str(config_path)},
    )
    return config_path
