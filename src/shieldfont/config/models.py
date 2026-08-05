"""Strict configuration models for the ``shieldfont/v1`` contract."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _default_containers() -> list[Literal["ttf", "woff2"]]:
    return ["ttf", "woff2"]


def _default_output_formats() -> list[Literal["ttf", "woff2"]]:
    return ["ttf", "woff2"]


def _default_codec_formats() -> list[Literal["esm", "cjs", "iife"]]:
    return ["esm", "cjs"]


def _default_verification_levels() -> list[
    Literal["structural", "shaping", "codec", "browser"]
]:
    return ["structural", "shaping", "codec", "browser"]


def _default_browsers() -> list[Literal["chromium", "firefox", "webkit"]]:
    return ["chromium", "firefox", "webkit"]


def _default_output_dir() -> Path:
    return Path("dist")


def _default_source_path() -> Path:
    return Path(".fonts/Source.ttf")


def _default_css_file() -> Path:
    return Path("shieldfont.css")


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ConfigModel(BaseModel):
    """Base model with deterministic aliases and strict fields."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
    )


class ProjectSection(ConfigModel):
    id: str = "shieldfont-project"
    version: str = "0.1.0"
    output_dir: Path = Field(default_factory=_default_output_dir)
    reproducible: bool = True
    source_date_epoch: int | None = None


class InstanceSection(ConfigModel):
    axes: dict[str, float] = Field(default_factory=dict)


class SourceSection(ConfigModel):
    path: Path = Field(default_factory=_default_source_path)
    required_outline: Literal["glyf"] = "glyf"
    allowed_containers: list[Literal["ttf", "woff2"]] = Field(
        default_factory=_default_containers
    )
    instance: InstanceSection = Field(default_factory=InstanceSection)


class NeutralFaceSection(ConfigModel):
    enabled: bool = True
    family: str = "ShieldFont Text"


class ShieldFaceSection(ConfigModel):
    family: str = "ShieldFont"


class FontSection(ConfigModel):
    family: str = "ShieldFont"
    description: str = "ShieldFont derivative"
    output_formats: list[Literal["ttf", "woff2"]] = Field(
        default_factory=_default_output_formats
    )
    shield_face: ShieldFaceSection = Field(default_factory=ShieldFaceSection)
    neutral_face: NeutralFaceSection = Field(default_factory=NeutralFaceSection)


class LayoutSection(ConfigModel):
    default_feature: str = "ccmp"
    boundary_mode: Literal["fire-then-revert"] = "fire-then-revert"
    max_estimated_subtable_bytes: int = Field(default=40960, gt=0, lt=65536)
    use_extension_lookups: bool = True
    default_scope_policy: Literal["fallback", "error", "no-op"] = "fallback"


class EncoderScopeSection(ConfigModel):
    locales: list[str] = Field(default_factory=list)
    source_scripts: list[str] = Field(default_factory=list)


class ShapingScopeSection(ConfigModel):
    target_scripts: list[str] = Field(default_factory=list)
    open_type_script: str = Field(default="DFLT", min_length=4, max_length=4)
    default_language: bool = True
    languages: list[str] = Field(default_factory=list)


class ScopeSection(ConfigModel):
    id: str
    encoder: EncoderScopeSection = Field(default_factory=EncoderScopeSection)
    shaping: ShapingScopeSection = Field(default_factory=ShapingScopeSection)
    dictionaries: list[Path] = Field(default_factory=list)


class MappingSection(ConfigModel):
    mode: Literal["directed", "bidirectional", "involution"] = "involution"
    duplicate_policy: Literal["error", "first-wins", "last-wins"] = "error"
    target_collision_policy: Literal["error", "warn"] = "error"
    self_map_policy: Literal["error", "keep", "drop-with-warning"] = "drop-with-warning"
    cross_script: bool = False
    case_mode: Literal["auto", "sensitive", "fold"] = "auto"
    normalization: Literal["NFC"] = "NFC"


class CssClassesSection(ConfigModel):
    shield: str = "sf-shield"
    neutral: str = "sf-text"


class CssSection(ConfigModel):
    file: Path = Field(default_factory=_default_css_file)
    asset_base_url: str = "./fonts/"
    font_display: Literal["auto", "block", "swap", "fallback", "optional"] = "block"
    font_synthesis: Literal["none"] = "none"
    embed_font: bool = False
    classes: CssClassesSection = Field(default_factory=CssClassesSection)


class CodecSection(ConfigModel):
    package_name: str = "@shieldfont/project-codec"
    formats: list[Literal["esm", "cjs", "iife"]] = Field(
        default_factory=_default_codec_formats
    )
    browser_build: bool = False
    embed_mappings: bool = False
    unknown_scope_policy: Literal["no-op", "error"] = "no-op"


class HarfBuzzSection(ConfigModel):
    implementation: Literal["uharfbuzz", "binary", "both"] = "both"


class VerificationSection(ConfigModel):
    levels: list[Literal["structural", "shaping", "codec", "browser"]] = Field(
        default_factory=_default_verification_levels
    )
    harfbuzz: HarfBuzzSection = Field(default_factory=HarfBuzzSection)
    browsers: list[Literal["chromium", "firefox", "webkit"]] = Field(
        default_factory=_default_browsers
    )
    fail_on_warning: bool = False


class LicenseSection(ConfigModel):
    policy: Literal["warn", "error", "ignore"] = "warn"


class ShieldFontConfig(ConfigModel):
    """Root ``shieldfont/v1`` configuration."""

    schema_version: Literal["shieldfont/v1"] = Field(
        default="shieldfont/v1", alias="schema"
    )
    project: ProjectSection = Field(default_factory=ProjectSection)
    source: SourceSection = Field(default_factory=SourceSection)
    font: FontSection = Field(default_factory=FontSection)
    layout: LayoutSection = Field(default_factory=LayoutSection)
    scopes: list[ScopeSection] = Field(
        default_factory=lambda: [
            ScopeSection(
                id="default",
                dictionaries=[Path("dictionaries/default.csv")],
            )
        ]
    )
    mapping: MappingSection = Field(default_factory=MappingSection)
    css: CssSection = Field(default_factory=CssSection)
    codec: CodecSection = Field(default_factory=CodecSection)
    verification: VerificationSection = Field(default_factory=VerificationSection)
    license: LicenseSection = Field(default_factory=LicenseSection)
