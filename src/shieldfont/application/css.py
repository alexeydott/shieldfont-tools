"""Deterministic CSS and delivery metadata generation."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CssFace:
    """One generated @font-face declaration."""

    family: str
    source_path: str
    weight: str = "400"
    style: str = "normal"
    unicode_range: str | None = None


@dataclass(frozen=True, slots=True)
class CssBuildOptions:
    """CSS delivery defaults and optional neutral face settings."""

    asset_base_url: str = "./fonts/"
    font_display: str = "block"
    font_synthesis: str = "none"
    shield_class: str = "sf-shield"
    neutral_class: str = "sf-text"
    include_ttf_fallback: bool = False
    embed_font: bool = False


def _font_source(
    face: CssFace,
    *,
    extension: str,
    asset_root: Path | None,
    mime_type: str,
) -> str:
    if asset_root is None:
        raise ValueError("asset_root is required when embedding fonts")
    path = asset_root / (
        Path(face.source_path).with_suffix(extension).name
    )
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"url(\"data:{mime_type};base64,{encoded}\")"


def _face_css(
    face: CssFace,
    options: CssBuildOptions,
    *,
    asset_root: Path | None,
) -> str:
    base = options.asset_base_url.rstrip("/") + "/"
    woff2_source = (
        _font_source(
            face,
            extension=".woff2",
            asset_root=asset_root,
            mime_type="font/woff2",
        )
        if options.embed_font
        else f'url("{base}{face.source_path}")'
    )
    sources = [f'{woff2_source} format("woff2")']
    if options.include_ttf_fallback:
        ttf_source = (
            _font_source(
                face,
                extension=".ttf",
                asset_root=asset_root,
                mime_type="font/ttf",
            )
            if options.embed_font
            else f'url("{base}{Path(face.source_path).with_suffix(".ttf").name}")'
        )
        sources.append(f'{ttf_source} format("truetype")')
    lines = [
        "@font-face {",
        f'  font-family: "{face.family}";',
        f"  src: {', '.join(sources)};",
        f"  font-weight: {face.weight};",
        f"  font-style: {face.style};",
        f"  font-display: {options.font_display};",
        f"  font-synthesis: {options.font_synthesis};",
    ]
    if face.unicode_range:
        lines.append(f"  unicode-range: {face.unicode_range};")
    lines.append("}")
    return "\n".join(lines)


def build_css(
    shield_face: CssFace,
    *,
    neutral_face: CssFace | None = None,
    options: CssBuildOptions | None = None,
    asset_root: Path | None = None,
    output_path: Path,
) -> dict[str, Path]:
    """Write CSS plus SRI metadata without embedding mappings."""

    resolved_options = options or CssBuildOptions()
    faces = [
        _face_css(
            shield_face,
            resolved_options,
            asset_root=asset_root,
        )
    ]
    if neutral_face is not None:
        faces.append(
            _face_css(
                neutral_face,
                resolved_options,
                asset_root=asset_root,
            )
        )
    base = resolved_options.asset_base_url.rstrip("/") + "/"
    css = "\n\n".join(faces)
    css += (
        f'\n\n.{resolved_options.shield_class} {{ '
        f'font-family: "{shield_face.family}"; }}'
    )
    if neutral_face is not None:
        css += (
            f'\n.{resolved_options.neutral_class} {{ '
            f'font-family: "{neutral_face.family}"; }}'
        )
    css_path = output_path.resolve()
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css + "\n", encoding="utf-8")
    digest = hashlib.sha256(css.encode("utf-8")).hexdigest()
    sri_path = css_path.with_name("sri.json")
    sri_path.write_text(
        json.dumps(
            {
                "css": {
                    "path": css_path.name,
                    "sha256": f"sha256-{digest}",
                },
                "assetBaseUrl": base,
                "fontsEmbedded": resolved_options.embed_font,
                "mappingEmbedded": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"css": css_path, "sri": sri_path}
