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

    serialized = yaml.safe_dump(
        config.model_dump(mode="json", by_alias=True, exclude_none=True),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
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
