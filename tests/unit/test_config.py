from __future__ import annotations

from pathlib import Path

import pytest

from shieldfont.application.init_project import (
    InitRequest,
    ensure_default_dictionary,
    ensure_demo_corpus,
    initialize_project,
)
from shieldfont.config.loader import load_config
from shieldfont.config.schema import generate_schema
from shieldfont.domain.errors import ErrorCode, ShieldFontError
from shieldfont.domain.font import FontSummary


def _write_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_load_config_resolves_paths_from_config_directory(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "shieldfont.yml",
        """
schema: shieldfont/v1
source:
  path: fonts/source.ttf
scopes:
  - id: latin-en
    dictionaries:
      - dictionaries/latin.csv
""",
    )

    config = load_config(config_path)

    assert config.source.path == (tmp_path / "fonts/source.ttf").resolve()
    assert config.scopes[0].dictionaries == [
        (tmp_path / "dictionaries/latin.csv").resolve()
    ]
    assert config.schema_version == "shieldfont/v1"


def test_strict_mode_rejects_unknown_fields_and_non_strict_logs_away(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path / "shieldfont.yml",
        """
schema: shieldfont/v1
project:
  unknownField: true
""",
    )

    with pytest.raises(ShieldFontError) as strict_error:
        load_config(config_path)
    assert strict_error.value.code is ErrorCode.CONFIG_INVALID

    config = load_config(config_path, strict=False)
    assert config.project.id == "shieldfont-project"


def test_environment_references_are_rejected(tmp_path: Path) -> None:
    forbidden_path = _write_config(
        tmp_path / "forbidden.yml",
        """
schema: shieldfont/v1
project:
  id: ${ENV:PROJECT_ID}
""",
    )
    with pytest.raises(ShieldFontError) as forbidden_error:
        load_config(forbidden_path)
    assert forbidden_error.value.code is ErrorCode.CONFIG_ENV_REFERENCE


def test_schema_is_published_for_shieldfont_v1() -> None:
    schema = generate_schema()

    assert schema["$id"] == "https://shieldfont.dev/schema/shieldfont-v1.schema.json"
    assert schema["properties"]["schema"]["const"] == "shieldfont/v1"

def test_schema_describes_every_configuration_element() -> None:
    schema = generate_schema()
    missing = []
    for property_name, property_schema in schema["properties"].items():
        if not property_schema.get("description"):
            missing.append(f"ShieldFontConfig.{property_name}")
    for definition_name, definition in schema["$defs"].items():
        if not definition.get("description"):
            missing.append(definition_name)
        for property_name, property_schema in definition.get("properties", {}).items():
            if not property_schema.get("description"):
                missing.append(f"{definition_name}.{property_name}")

    assert not missing
    assert "Affects the generated font asset family and filename." in (
        schema["$defs"]["FontSection"]["properties"]["family"]["description"]
    )
    assert (
        schema["$defs"]["FontSection"]["properties"]["shieldFace"]["description"]
        == "Affects the local CSS family name for the generated ShieldFont face."
    )
    assert (
        schema["$defs"]["ShieldFaceSection"]["properties"]["family"]["description"]
        == (
            "Affects the local family name exposed by the generated "
            "ShieldFont face in CSS."
        )
    )


def test_initialize_project_creates_template_and_uses_font_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.ttf"
    source.write_bytes(b"font fixture")

    def inspect(path: Path) -> FontSummary:
        assert path == source.resolve()
        return FontSummary(
            family="Source Family",
            subfamily="Medium",
            weight=500,
            style="normal",
            has_glyf=True,
            variable=True,
            axes={"wght": 400.0},
        )

    config_path = initialize_project(
        InitRequest(
            project_dir=tmp_path / "project",
            font_path=source,
            scripts=("DFLT", "latn"),
        ),
        inspect_font=inspect,
    )

    assert config_path.exists()
    assert (tmp_path / "project/.fonts/source.ttf").read_bytes() == b"font fixture"
    dictionary_path = tmp_path / "project/dictionaries/default.csv"
    assert dictionary_path.read_text(encoding="utf-8").splitlines()[:2] == [
        "source,target",
        "чудное,тягостная",
    ]
    assert (tmp_path / "project/texts/demo.txt").read_text(
        encoding="utf-8"
    ).startswith("Я помню чудное мгновенье:")
    assert (tmp_path / "project/dictionaries").is_dir()
    config = load_config(config_path)
    assert config.font.family == "SourceFamily_shld"
    assert config.font.shield_face.family == "ShieldFont"
    assert config.mapping.mode == "directed"
    font_config = config.model_dump(mode="json", by_alias=True)["font"]
    assert "subfamily" not in font_config
    assert "typographicFamily" not in font_config
    assert "typographicSubfamily" not in font_config
    assert "postScriptName" not in font_config
    assert "postTable" not in font_config
    assert "preserveExistingLayout" not in font_config
    assert "version" not in font_config
    assert config.source.instance.axes == {"wght": 400.0}
    assert [scope.shaping.open_type_script for scope in config.scopes] == [
        "DFLT",
        "latn",
    ]

    custom_config_path = initialize_project(
        InitRequest(
            project_dir=tmp_path / "custom-project",
            font_path=source,
            postfix="_demo",
        ),
        inspect_font=inspect,
    )
    assert load_config(custom_config_path).font.family == "SourceFamily_demo"
    generated_profile = custom_config_path.read_text(encoding="utf-8")
    assert (
        "# Source-font input and variable-font selection settings."
        in generated_profile
    )
    assert (
        "# Generated family name; affects font filenames, names, and manifest metadata."
        in generated_profile
    )
    assert (
        "# CSV mappings consumed by the scope; they change generated substitutions."
        in generated_profile
    )


def test_default_dictionary_is_created_only_when_dictionary_files_are_missing(
    tmp_path: Path,
) -> None:
    dictionary_path = ensure_default_dictionary(tmp_path)

    assert dictionary_path == tmp_path / "dictionaries/default.csv"
    original = dictionary_path.read_text(encoding="utf-8")
    assert ensure_default_dictionary(tmp_path) is None
    assert dictionary_path.read_text(encoding="utf-8") == original

    existing = tmp_path / "existing.csv"
    existing.write_text("source,target\none,two\n", encoding="utf-8")
    other_root = tmp_path / "with-existing"
    dictionaries = other_root / "dictionaries"
    dictionaries.mkdir(parents=True)
    (dictionaries / existing.name).write_text(
        existing.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert ensure_default_dictionary(other_root) is None
    assert not (dictionaries / "default.csv").exists()


def test_demo_corpus_is_preserved_when_text_files_already_exist(tmp_path: Path) -> None:
    corpus_path = ensure_demo_corpus(tmp_path)

    assert corpus_path == tmp_path / "texts/demo.txt"
    original = corpus_path.read_text(encoding="utf-8")
    assert ensure_demo_corpus(tmp_path) is None
    assert corpus_path.read_text(encoding="utf-8") == original
