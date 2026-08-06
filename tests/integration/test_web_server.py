from __future__ import annotations

import json
import socket
import threading
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

from shieldfont.presentation.web.server import ServerConfig, create_server


def _start_server(tmp_path: Path) -> tuple[Any, threading.Thread]:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<main>ShieldFont</main>", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "report.json").write_text('{"status":"ok"}', encoding="utf-8")

    def actions(action: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"handled": action, "payloadKeys": sorted(payload)}

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = create_server(
        ServerConfig(project_root=tmp_path, port=port, static_root=static),
        actions,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_web_server_exposes_safe_status_action_and_static_routes(
    tmp_path: Path,
) -> None:
    server, thread = _start_server(tmp_path)
    connection = HTTPConnection("127.0.0.1", server.server_port)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200
        assert b"ShieldFont" in response.read()

        connection.request("GET", "/api/status")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["status"] == "ok"
        assert payload["fontsRoot"] == str((tmp_path / ".fonts").resolve())
        assert response.getheader("Content-Security-Policy") is not None

        connection.request("GET", "/api/files?kind=artifact")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["files"][0]["path"] == "dist/report.json"

        connection.request("GET", "/api/workflows")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert "dict-normalize" in payload["actions"]

        connection.request("GET", "/api/actions")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert "css-build" in payload["actions"]
        assert "dict-read" in payload["actions"]
        assert "dict-save" in payload["actions"]
        assert "project-read" in payload["actions"]
        assert "project-save" in payload["actions"]

        connection.request("GET", "/api/config/schema")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        protection = payload["$defs"]["ProtectionSection"]["properties"]
        assert protection["profile"]["default"] == "compatibility"
        assert protection["documentNonce"]["anyOf"][0]["writeOnly"] is True
        assert (
            payload["$defs"]["LayoutSection"]["properties"]["gsubOptimization"][
                "default"
            ]
            == "auto"
        )

        connection.request(
            "POST",
            "/api/action",
            body=json.dumps({"action": "verify"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["handled"] == "verify"
        process_id = payload["process"]["id"]

        connection.request("GET", f"/api/process/{process_id}")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["process"]["status"] == "completed"

        connection.request("GET", "/api/results")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["results"][0]["path"] == "dist/report.json"

        connection.request("GET", "/%2e%2e/secret")
        response = connection.getresponse()
        assert response.status == 404
    finally:
        connection.close()


def test_web_server_uses_configured_fonts_root_for_inventory(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("ShieldFont", encoding="utf-8")
    custom_fonts = tmp_path / "custom-fonts"
    custom_fonts.mkdir()
    (custom_fonts / "selected.ttf").write_bytes(b"font")
    (tmp_path / ".fonts").mkdir()
    (tmp_path / ".fonts" / "ignored.ttf").write_bytes(b"font")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = create_server(
        ServerConfig(
            project_root=tmp_path,
            port=port,
            static_root=static,
            fonts_root=Path("custom-fonts"),
        )
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", port)
    try:
        connection.request("GET", "/api/files?kind=font")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert [entry["path"] for entry in payload["files"]] == [
            "custom-fonts/selected.ttf"
        ]
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_server_serves_selected_source_font_for_comparison(
    tmp_path: Path,
) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("ShieldFont", encoding="utf-8")
    fonts = tmp_path / ".fonts"
    fonts.mkdir()
    (fonts / "profile.ttf").write_bytes(b"profile-font")
    (fonts / "selected.ttf").write_bytes(b"selected-font")
    (tmp_path / "shieldfont.yml").write_text(
        "schema: shieldfont/v1\nsource:\n  path: .fonts/profile.ttf\n",
        encoding="utf-8",
    )

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = create_server(
        ServerConfig(project_root=tmp_path, port=port, static_root=static),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", port)
    try:
        connection.request("GET", "/api/source-font?path=.fonts/selected.ttf")
        response = connection.getresponse()
        assert response.status == 200
        assert response.read() == b"selected-font"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_server_rejects_unknown_actions(tmp_path: Path) -> None:
    server, thread = _start_server(tmp_path)
    connection = HTTPConnection("127.0.0.1", server.server_port)
    try:
        connection.request(
            "POST",
            "/api/action",
            body=b'{"action":"shell"}',
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 400
        assert payload["status"] == "error"
        assert payload["code"] == "SF-INVALID-INPUT"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_server_serves_configured_comparison_assets(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("ShieldFont", encoding="utf-8")
    fonts = tmp_path / ".fonts"
    fonts.mkdir()
    source = fonts / "source.ttf"
    source.write_bytes(b"font")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "shieldfont.css").write_text(
        ".sf-shield { font-family: ShieldFont; }\n",
        encoding="utf-8",
    )
    (tmp_path / "dist" / "fonts").mkdir()
    (tmp_path / "dist" / "fonts" / "SegoeUI Text-Regular.woff2").write_bytes(
        b"generated-font"
    )
    (tmp_path / "shieldfont.yml").write_text(
        """
schema: shieldfont/v1
source:
  path: .fonts/source.ttf
css:
  file: shieldfont.css
""",
        encoding="utf-8",
    )

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = create_server(
        ServerConfig(project_root=tmp_path, port=port, static_root=static)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", port)
    try:
        for path, expected in (
            ("/api/shieldfont.css", b".sf-shield"),
            ("/api/source-font", b"font"),
            ("/api/fonts/source.ttf", b"font"),
            ("/fonts/source.ttf", b"font"),
            ("/api/fonts/SegoeUI%20Text-Regular.woff2", b"generated-font"),
        ):
            connection.request("GET", path)
            response = connection.getresponse()
            assert response.status == 200
            assert expected in response.read()
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_server_rejects_non_font_assets_from_font_routes(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("ShieldFont", encoding="utf-8")
    fonts = tmp_path / ".fonts"
    fonts.mkdir()
    (fonts / "secret.json").write_text("{}", encoding="utf-8")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = create_server(
        ServerConfig(project_root=tmp_path, port=port, static_root=static)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", port)
    try:
        connection.request("GET", "/api/fonts/secret.json")
        response = connection.getresponse()
        assert response.status == 404
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
