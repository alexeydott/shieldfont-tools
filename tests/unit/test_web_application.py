from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shieldfont.application import web
from shieldfont.application.css import CssBuildOptions, CssFace
from shieldfont.application.web import WebActions
from shieldfont.domain.errors import ShieldFontError


def test_web_actions_delegate_build_without_exposing_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Path] = []

    def fake_build(config_path: Path) -> Path:
        captured.append(config_path)
        return tmp_path / "dist"

    monkeypatch.setattr(web, "build_project", fake_build)
    actions = WebActions(tmp_path)
    result = actions("build", {"unexpected": "ignored"})

    assert result == {"outputDir": str(tmp_path / "dist")}
    assert captured == [tmp_path / "shieldfont.yml"]
    assert actions.fonts_root == (tmp_path / ".fonts").resolve()
    assert actions.fonts_root.is_dir()


def test_web_actions_build_with_selected_source_font(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tmp_path / ".fonts" / "selected.ttf"
    selected.parent.mkdir()
    selected.write_bytes(b"selected-font")
    captured: dict[str, object] = {}

    def fake_build(
        config_path: Path,
        *,
        source_path: Path | None = None,
        output_dir: Path | None = None,
    ) -> Path:
        captured["config"] = config_path
        captured["source"] = source_path
        captured["output"] = output_dir
        return tmp_path / "dist"

    monkeypatch.setattr(web, "build_project", fake_build)
    actions = WebActions(tmp_path)

    result = actions("build", {"sourceFont": ".fonts/selected.ttf"})

    assert result == {"outputDir": str(tmp_path / "dist")}
    assert captured == {
        "config": tmp_path / "shieldfont.yml",
        "source": selected.resolve(),
        "output": None,
    }


def test_web_actions_reject_paths_that_escape_project_root(tmp_path: Path) -> None:
    with pytest.raises(ShieldFontError, match="escapes the project root"):
        WebActions(tmp_path)("font-inspect", {"path": "../outside.ttf"})


def test_web_actions_reject_font_paths_outside_fonts_directory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "dist" / "source.ttf"
    source.parent.mkdir()
    source.write_bytes(b"font")
    with pytest.raises(ShieldFontError, match="fonts directory"):
        WebActions(tmp_path)("font-inspect", {"path": "dist/source.ttf"})


def test_web_actions_accept_font_paths_in_custom_fonts_directory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "incoming" / "source.ttf"
    source.parent.mkdir()
    source.write_bytes(b"font")

    actions = WebActions(tmp_path, Path("incoming"))
    assert actions._font_payload_path({"path": "incoming/source.ttf"}, "path") == source


def test_web_actions_uploads_and_validates_source_font(tmp_path: Path) -> None:
    source = (
        Path(__file__).parents[2]
        / "deps"
        / "shieldfont"
        / "packages"
        / "font"
        / "optik-a.woff2"
    )
    actions = WebActions(tmp_path)

    result = actions(
        "font-upload",
        {"filename": "uploaded.woff2", "content": source.read_bytes()},
    )

    uploaded = tmp_path / ".fonts" / "uploaded.woff2"
    assert result["path"] == ".fonts/uploaded.woff2"
    assert result["inspection"]["outlines"]["type"] == "glyf"
    assert uploaded.read_bytes() == source.read_bytes()


def test_web_actions_reject_config_credentials_and_unknown_fields(
    tmp_path: Path,
) -> None:
    actions = WebActions(tmp_path)
    with pytest.raises(ShieldFontError, match="not editable"):
        actions._validate_config_update({"unknown": "value"})


def test_web_config_metadata_redacts_protection_private_inputs(
    tmp_path: Path,
) -> None:
    (tmp_path / "shieldfont.yml").write_text(
        """
schema: shieldfont/v1
protection:
  mappingContract: shieldfont.mapping.v2
  seed: private-seed
  documentNonce: private-nonce
""",
        encoding="utf-8",
    )

    parameters = WebActions(tmp_path)("config-metadata", {})["parameters"]

    assert parameters["protection"]["seed"] == "<redacted>"
    assert parameters["protection"]["documentNonce"] == "<redacted>"


def test_project_editor_redacts_and_preserves_protection_private_inputs(
    tmp_path: Path,
) -> None:
    project = tmp_path / "shieldfont.yml"
    project.write_text(
        """
schema: shieldfont/v1
protection:
  mappingContract: shieldfont.mapping.v2
  seed: private-seed
  documentNonce: private-nonce
""",
        encoding="utf-8",
    )
    actions = WebActions(tmp_path)

    loaded = actions("project-read", {})

    assert "private-seed" not in loaded["content"]
    assert "private-nonce" not in loaded["content"]
    assert loaded["content"].count("<redacted>") == 2

    actions(
        "project-save",
        {
            "content": loaded["content"].replace(
                "schema: shieldfont/v1",
                "schema: shieldfont/v1\nproject:\n  id: updated",
            )
        },
    )

    saved = project.read_text(encoding="utf-8")
    assert "private-seed" in saved
    assert "private-nonce" in saved
    assert "<redacted>" not in saved
    assert "id: updated" in saved


def test_web_actions_validates_generated_default_dictionary_as_directed(
    tmp_path: Path,
) -> None:
    (tmp_path / "shieldfont.yml").write_text(
        "schema: shieldfont/v1\nmapping:\n  mode: directed\n",
        encoding="utf-8",
    )

    result = WebActions(tmp_path)("dict-validate", {})

    assert result["entries"] == 43
    assert result["warnings"] == []


def test_web_actions_reads_and_saves_dictionary_with_default_fallback(
    tmp_path: Path,
) -> None:
    actions = WebActions(tmp_path)

    default = actions("dict-read", {})
    assert default["path"] == "dictionaries/default.csv"
    assert "source,target" in default["content"]

    saved = actions(
        "dict-save",
        {
            "path": "dictionaries/custom.csv",
            "content": "source,target\nleft,right\n",
        },
    )
    assert saved["path"] == "dictionaries/custom.csv"
    assert actions("dict-read", {"path": "dictionaries/custom.csv"})["content"] == (
        "source,target\nleft,right\n"
    )


def test_web_actions_persists_the_server_default_dictionary(
    tmp_path: Path,
) -> None:
    (tmp_path / "shieldfont.yml").write_text(
        "schema: shieldfont/v1\n",
        encoding="utf-8",
    )
    actions = WebActions(tmp_path)
    custom = tmp_path / "dictionaries" / "custom.csv"
    custom.write_text("source,target\nleft,right\n", encoding="utf-8")

    selected = actions("dict-default-set", {"path": "dictionaries/custom.csv"})

    assert selected == {"path": "dictionaries/custom.csv"}
    assert actions("dict-read", {})["path"] == "dictionaries/custom.csv"
    assert actions("config-metadata", {})["defaultDictionary"] == (
        "dictionaries/custom.csv"
    )


def test_web_actions_build_uses_selected_dictionary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "shieldfont.yml").write_text(
        "schema: shieldfont/v1\n",
        encoding="utf-8",
    )
    selected = tmp_path / "dictionaries" / "ru-alpha.csv"
    selected.parent.mkdir(parents=True)
    selected.write_text("source,target\nleft,right\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_build_project(
        config_path: Path,
        *,
        output_dir: Path | None = None,
        source_path: Path | None = None,
        dictionary_path: Path | None = None,
    ) -> Path:
        captured.update(
            {
                "config": config_path,
                "output": output_dir,
                "source": source_path,
                "dictionary": dictionary_path,
            }
        )
        return tmp_path / "dist"

    monkeypatch.setattr(web, "build_project", fake_build_project)

    WebActions(tmp_path)(
        "build",
        {"dictionaryPath": "dictionaries/ru-alpha.csv"},
    )

    assert captured["dictionary"] == selected.resolve()


def test_web_actions_reads_and_saves_project_yaml(tmp_path: Path) -> None:
    project = tmp_path / "shieldfont.yml"
    project.write_text("schema: shieldfont/v1\n", encoding="utf-8")
    actions = WebActions(tmp_path)

    loaded = actions("project-read", {})
    assert loaded["path"] == "shieldfont.yml"
    assert loaded["content"] == "schema: shieldfont/v1\n"

    saved = actions(
        "project-save",
        {
            "content": "schema: shieldfont/v1\nproject:\n  id: demo\n",
        },
    )
    assert saved["path"] == "shieldfont.yml"
    assert project.read_text(encoding="utf-8") == saved["content"]


def test_test_text_encodes_whole_words_without_cascading_replacements(
    tmp_path: Path,
) -> None:
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "ruleset.json").write_text(
        (
            '{"scopes":[{"id":"default","rules":['
            '{"source":"чудное","target":"тягостная"},'
            '{"source":"мгновенье","target":"вечность"},'
            '{"source":"в","target":"вне"}]}]}'
        ),
        encoding="utf-8",
    )

    result = WebActions(tmp_path)(
        "test-text",
        {"text": "Я помню чудное мгновенье:"},
    )

    assert result["shieldFont"] == "Я помню тягостная вечность:"


def test_web_actions_passes_css_build_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "shieldfont.yml").write_text(
        (
            "schema: shieldfont/v1\nfont:\n"
            "  family: Demo_shld\n"
            "  shieldFace:\n"
            "    family: DemoShield\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "dist" / "fonts").mkdir(parents=True)
    (tmp_path / "dist" / "fonts" / "Demo_shld-Regular.woff2").write_bytes(b"font")
    captured: dict[str, object] = {}

    def fake_build_css(
        face: CssFace,
        *,
        options: CssBuildOptions,
        asset_root: Path,
        output_path: Path,
    ) -> dict[str, Path]:
        captured["face"] = face
        captured["options"] = options
        captured["asset_root"] = asset_root
        captured["output"] = output_path
        return {"css": output_path, "sri": output_path.with_name("sri.json")}

    monkeypatch.setattr(web, "build_css", fake_build_css)
    result = WebActions(tmp_path)(
        "css-build",
        {
            "font": "dist/fonts/demo.woff2",
            "output": "dist/demo.css",
            "assetBaseUrl": "/assets/",
            "fontDisplay": "swap",
            "includeTtfFallback": True,
            "embedFont": True,
        },
    )

    options = captured["options"]
    face = captured["face"]
    assert isinstance(face, CssFace)
    assert face.family == "DemoShield"
    assert face.source_path == "Demo_shld-Regular.woff2"
    assert options.asset_base_url == "/assets/"
    assert options.font_display == "swap"
    assert options.include_ttf_fallback is True
    assert options.embed_font is True
    assert captured["asset_root"] == (tmp_path / "dist" / "fonts").resolve()
    assert captured["output"] == (tmp_path / "dist/demo.css").resolve()
    assert result["artifacts"]["css"].endswith(str(Path("dist/demo.css")))


def test_web_actions_css_build_verifies_selected_source_font(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "shieldfont.yml").write_text(
        "schema: shieldfont/v1\nfont:\n  family: Demo_shld\n",
        encoding="utf-8",
    )
    source = tmp_path / ".fonts" / "selected.ttf"
    source.parent.mkdir()
    source.write_bytes(b"selected-font")
    output = tmp_path / "dist"
    (output / "fonts").mkdir(parents=True)
    (output / "fonts" / "Demo_shld-Regular.woff2").write_bytes(b"font")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(
        json.dumps({"source": {"path": source.name, "sha256": f"sha256:{digest}"}}),
        encoding="utf-8",
    )

    def fake_build_css(
        face: CssFace,
        *,
        options: CssBuildOptions,
        asset_root: Path,
        output_path: Path,
    ) -> dict[str, Path]:
        del face, options, asset_root
        return {"css": output_path, "sri": output_path.with_name("sri.json")}

    monkeypatch.setattr(web, "build_css", fake_build_css)
    result = WebActions(tmp_path)(
        "css-build",
        {
            "sourceFont": ".fonts/selected.ttf",
            "output": "dist/demo.css",
        },
    )

    assert result["artifacts"]["css"].endswith(str(Path("dist/demo.css")))


def test_web_actions_css_build_rebuilds_stale_selected_source_font(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "shieldfont.yml").write_text(
        "schema: shieldfont/v1\nfont:\n  family: Demo_shld\n",
        encoding="utf-8",
    )
    source = tmp_path / ".fonts" / "selected.ttf"
    source.parent.mkdir()
    source.write_bytes(b"selected-font")
    output = tmp_path / "dist"
    (output / "fonts").mkdir(parents=True)
    (output / "fonts" / "Demo_shld-Regular.woff2").write_bytes(b"font")

    verification_results = iter([False, True])
    build_calls: list[dict[str, Path | None]] = []

    def fake_assert_css_source_matches(
        output_dir: Path,
        source_path: Path,
    ) -> None:
        del output_dir, source_path
        if not next(verification_results):
            raise ShieldFontError(
                "Generated ShieldFont artifact does not match the selected "
                "source font; run build first",
                code=web.ErrorCode.INVALID_INPUT,
                exit_code=web.ExitCode.INVALID_INPUT,
                stage="web.css.input",
            )

    def fake_build_project(
        config_path: Path,
        *,
        output_dir: Path | None = None,
        source_path: Path | None = None,
    ) -> Path:
        build_calls.append(
            {
                "config": config_path,
                "output": output_dir,
                "source": source_path,
            }
        )
        return output

    def fake_build_css(
        face: CssFace,
        *,
        options: CssBuildOptions,
        asset_root: Path,
        output_path: Path,
    ) -> dict[str, Path]:
        del face, options, asset_root
        return {"css": output_path, "sri": output_path.with_name("sri.json")}

    monkeypatch.setattr(web.WebActions, "_assert_css_source_matches", staticmethod(
        fake_assert_css_source_matches
    ))
    monkeypatch.setattr(web, "build_project", fake_build_project)
    monkeypatch.setattr(web, "build_css", fake_build_css)

    result = WebActions(tmp_path)(
        "css-build",
        {"sourceFont": ".fonts/selected.ttf", "output": "dist/demo.css"},
    )

    assert build_calls == [
        {
            "config": tmp_path / "shieldfont.yml",
            "output": output,
            "source": source.resolve(),
        }
    ]
    assert result["artifacts"]["css"].endswith(str(Path("dist/demo.css")))
