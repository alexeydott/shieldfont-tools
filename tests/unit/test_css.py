from __future__ import annotations

import json
from pathlib import Path

from shieldfont.application.css import CssBuildOptions, CssFace, build_css


def test_css_build_uses_woff2_only_by_default_and_emits_sri(tmp_path: Path) -> None:
    artifacts = build_css(
        CssFace("Project Shield", "ProjectShield-Regular.woff2"),
        neutral_face=CssFace("Project Text", "ProjectText-Regular.woff2"),
        options=CssBuildOptions(asset_base_url="/assets/fonts"),
        output_path=tmp_path / "shieldfont.css",
    )

    css = artifacts["css"].read_text(encoding="utf-8")
    sri = json.loads(artifacts["sri"].read_text(encoding="utf-8"))
    assert 'format("woff2")' in css
    assert 'format("truetype")' not in css
    assert ".sf-shield" in css
    assert sri["mappingEmbedded"] is False


def test_css_build_can_embed_woff2_and_ttf_as_base64(tmp_path: Path) -> None:
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    (fonts / "ProjectShield-Regular.woff2").write_bytes(b"woff2-data")
    (fonts / "ProjectShield-Regular.ttf").write_bytes(b"ttf-data")

    artifacts = build_css(
        CssFace("Project Shield", "ProjectShield-Regular.woff2"),
        options=CssBuildOptions(
            include_ttf_fallback=True,
            embed_font=True,
        ),
        asset_root=fonts,
        output_path=tmp_path / "shieldfont.css",
    )

    css = artifacts["css"].read_text(encoding="utf-8")
    sri = json.loads(artifacts["sri"].read_text(encoding="utf-8"))
    assert 'url("./fonts/ProjectShield-Regular.woff2")' not in css
    assert "data:font/woff2;base64,d29mZjItZGF0YQ==" in css
    assert "data:font/ttf;base64,dHRmLWRhdGE=" in css
    assert sri["fontsEmbedded"] is True
