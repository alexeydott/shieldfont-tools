from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shieldfont.application.generation_profile import resolve_generation_profile
from shieldfont.config.models import ShieldFontConfig
from shieldfont.domain.errors import ErrorCode, ShieldFontError
from shieldfont.domain.font import FontSummary
from shieldfont.presentation.cli import generate as generate_cli


def _write_profile(path: Path) -> Path:
    path.write_text(
        """
schema: shieldfont/v1
project:
  outputDir: dist/profile
source:
  path: fonts/profile.ttf
font:
  family: ProfileFamily
css:
  fontDisplay: block
scopes:
  - id: default
    dictionaries:
      - dictionaries/profile.csv
""",
        encoding="utf-8",
    )
    return path


def test_profile_overrides_are_applied_relative_to_profile(
    tmp_path: Path,
) -> None:
    profile = _write_profile(tmp_path / "profile.yml")

    config = resolve_generation_profile(
        profile,
        output_dir=Path("dist/override"),
        source_path=Path("fonts/override.ttf"),
        dictionary_path=Path("dictionaries/override.csv"),
        family="OverrideFamily",
        font_display="swap",
        embed_font=True,
    )

    assert config.project.output_dir == (tmp_path / "dist/override").resolve()
    assert config.source.path == (tmp_path / "fonts/override.ttf").resolve()
    assert config.scopes[0].dictionaries == [
        (tmp_path / "dictionaries/override.csv").resolve()
    ]
    assert config.font.family == "OverrideFamily"
    assert config.css.font_display == "swap"
    assert config.css.embed_font is True


def test_invalid_profile_override_has_stable_error(tmp_path: Path) -> None:
    profile = _write_profile(tmp_path / "profile.yml")

    with pytest.raises(ShieldFontError) as error:
        resolve_generation_profile(profile, font_display="invalid")

    assert error.value.code is ErrorCode.CONFIG_INVALID
    assert error.value.stage == "config.override"


def test_document_bound_overrides_are_validated_and_resolved(
    tmp_path: Path,
) -> None:
    profile = _write_profile(tmp_path / "profile.yml")
    inventory = tmp_path / "content.txt"
    inventory.write_text("alpha", encoding="utf-8")

    config = resolve_generation_profile(
        profile,
        protection_profile="document-bound",
        mapping_seed="private-seed",
        document_nonce="private-nonce",
        tenant_id="private-tenant",
        inventory_paths=[Path("content.txt")],
        reserve_aliases=2,
        scan_public_artifacts=True,
        gsub_optimization="format2",
    )

    assert config.protection.mapping_contract == "shieldfont.mapping.v2"
    assert config.protection.inventory == [inventory.resolve()]
    assert config.protection.seed.get_secret_value() == "private-seed"
    assert config.protection.document_nonce.get_secret_value() == "private-nonce"
    assert config.protection.tenant_id.get_secret_value() == "private-tenant"
    assert config.protection.reserve_aliases == 2
    assert config.protection.scan_public_artifacts is True
    assert config.layout.gsub_optimization == "format2"


def test_postfix_override_uses_original_source_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _write_profile(tmp_path / "profile.yml")
    monkeypatch.setattr(
        "shieldfont.application.generation_profile.inspect_font_for_init",
        lambda path: FontSummary(
            family="Original Family",
            subfamily="Regular",
            weight=400,
            style="normal",
            has_glyf=True,
            variable=False,
        ),
    )

    config = resolve_generation_profile(profile, postfix="_ru")

    assert config.font.family == "OriginalFamily_ru"


def test_empty_postfix_is_rejected(tmp_path: Path) -> None:
    profile = _write_profile(tmp_path / "profile.yml")

    with pytest.raises(ShieldFontError) as error:
        resolve_generation_profile(profile, postfix=" ")

    assert error.value.code is ErrorCode.INVALID_INPUT
    assert error.value.stage == "config.override"


def test_generate_command_passes_resolved_config_to_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _write_profile(tmp_path / "profile.yml")
    captured: dict[str, Path | ShieldFontConfig] = {}

    def fake_build(
        config_path: Path,
        *,
        config_override: ShieldFontConfig,
    ) -> Path:
        captured["config_path"] = config_path
        captured["config"] = config_override
        return tmp_path / "dist/result"

    monkeypatch.setattr(generate_cli, "build_project", fake_build)
    result = CliRunner().invoke(
        generate_cli.generate_app,
        [
            "run",
            str(profile),
            "--family",
            "CliFamily",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["config_path"] == profile
    config = captured["config"]
    assert isinstance(config, ShieldFontConfig)
    assert config.font.family == "CliFamily"
    assert Path(json.loads(result.stdout)["output"]) == tmp_path / "dist/result"


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "--source",
            ".fonts\\segoepr.ttf",
            "--postfix",
            "_ru",
            "--output-dir",
            "build\\ru",
            "--json",
        ],
        [
            "--source",
            ".fonts\\segoepr.ttf",
            "--family",
            "MyShieldFont",
            "--output-dir",
            "build\\custom",
        ],
        [
            "--source",
            ".fonts\\segoepr.ttf",
            "--dictionary",
            "dictionaries\\default.csv",
            "--font-display",
            "swap",
        ],
    ],
)
def test_documented_cli_examples_are_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    profile = _write_profile(tmp_path / "profile.yml")
    monkeypatch.setattr(
        "shieldfont.application.generation_profile.inspect_font_for_init",
        lambda path: FontSummary(
            family="Original Family",
            subfamily="Regular",
            weight=400,
            style="normal",
            has_glyf=True,
            variable=False,
        ),
    )
    monkeypatch.setattr(
        generate_cli,
        "build_project",
        lambda config_path, *, config_override: tmp_path / "dist/result",
    )

    result = CliRunner().invoke(
        generate_cli.generate_app,
        ["run", str(profile), *arguments],
    )

    assert result.exit_code == 0, result.stdout


def test_documented_cli_examples_are_present_in_help() -> None:
    result = CliRunner().invoke(
        generate_cli.generate_app,
        ["run", "--help"],
    )

    assert result.exit_code == 0
    assert "Examples:" in result.stdout
    assert "--postfix _ru" in result.stdout
    assert "--family" in result.stdout
    assert "MyShieldFont" in result.stdout
    assert "--dictionary" in result.stdout
    assert "default.csv" in result.stdout
    assert "--protection-profile" in result.stdout
    assert "--mapping-contract" in result.stdout
    assert "--document-nonce" in result.stdout
    assert "--inventory" in result.stdout
    assert "--gsub-optimization" in result.stdout
    assert (
        ".\\build\\shieldfont-generate.exe serve --port 8765"
        in result.stdout
    )


def test_portable_cli_root_help_exposes_executable_examples() -> None:
    result = CliRunner().invoke(
        generate_cli.generate_app,
        ["--help"],
    )

    assert result.exit_code == 0
    assert ".\\build\\shieldfont-generate.exe run shieldfont.yml" in result.stdout
    assert (
        ".\\build\\shieldfont-generate.exe serve --port 8765"
        in result.stdout
    )


def test_portable_cli_server_help_exposes_port() -> None:
    result = CliRunner().invoke(
        generate_cli.generate_app,
        ["serve", "--help"],
    )

    assert result.exit_code == 0
    assert "--port" in result.stdout
    assert "--project-root" in result.stdout
    assert "--fonts-dir" in result.stdout
