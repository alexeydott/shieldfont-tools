"""Offline-first HTTP server for the local ShieldFont GUI."""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from shieldfont.config.loader import load_config
from shieldfont.config.schema import generate_schema
from shieldfont.domain.errors import ErrorCode, ExitCode, ShieldFontError
from shieldfont.infrastructure.logging import log_event

LOGGER = logging.getLogger("shieldfont.web")
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESULT_BYTES = 128 * 1024
VENDOR_PACKAGES = frozenset(
    {
        "@monaco-editor/loader",
        "@vscode/l10n",
        "jsonc-parser",
        "monaco-editor",
        "monaco-languageserver-types",
        "monaco-marker-data-provider",
        "monaco-types",
        "monaco-worker-manager",
        "monaco-yaml",
        "path-browserify",
        "prettier",
        "proxy-disposable",
        "state-local",
        "vscode-languageserver-textdocument",
        "vscode-languageserver-types",
        "vscode-uri",
        "yaml",
    }
)
VENDOR_IMPORTS = {
    "@vscode/l10n": "/vendor/@vscode/l10n/dist/browser.js",
    "jsonc-parser": "/vendor/jsonc-parser/lib/esm/main.js",
    "monaco-languageserver-types": (
        "/vendor/monaco-languageserver-types/dist/index.js"
    ),
    "monaco-editor/esm/": "/vendor/monaco-editor/esm/",
    "monaco-editor/esm/vs/editor/editor.worker.js": (
        "/vendor/monaco-editor/esm/vs/editor/editor.worker.js"
    ),
    "monaco-marker-data-provider": (
        "/vendor/monaco-marker-data-provider/dist/monaco-marker-data-provider.js"
    ),
    "monaco-types": "/vendor/monaco-types/index.js",
    "monaco-worker-manager": "/vendor/monaco-worker-manager/index.js",
    "monaco-worker-manager/worker": "/vendor/monaco-worker-manager/worker.js",
    "path-browserify": "/vendor/path-browserify/index.js",
    "prettier/standalone": "/vendor/prettier/standalone.mjs",
    "prettier/plugins/estree": "/vendor/prettier/plugins/estree.mjs",
    "prettier/plugins/yaml": "/vendor/prettier/plugins/yaml.mjs",
    "proxy-disposable": "/vendor/proxy-disposable/lib/proxy-disposable.js",
    "state-local": "/vendor/state-local/lib/es/state-local.js",
    "vscode-languageserver-textdocument": (
        "/vendor/vscode-languageserver-textdocument/lib/esm/main.js"
    ),
    "vscode-languageserver-types": (
        "/vendor/vscode-languageserver-types/lib/esm/main.js"
    ),
    "vscode-uri": "/vendor/vscode-uri/lib/esm/index.mjs",
    "yaml": "/vendor/yaml/browser/index.js",
}
FONT_CONTENT_TYPES = {
    ".otf": "font/otf",
    ".ttf": "font/ttf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}
ALLOWED_ACTIONS = frozenset(
    {
        "build",
        "verify",
        "font-inspect",
        "font-select",
        "font-upload",
        "dict-validate",
        "dict-normalize",
        "dict-read",
        "dict-default-set",
        "dict-save",
        "project-read",
        "project-save",
        "css-build",
        "config-metadata",
        "config-update",
        "test-text",
    }
)
ACTION_SCHEMAS: dict[str, dict[str, Any]] = {
    "build": {"method": "POST", "required": [], "optional": ["outputDir"]},
    "verify": {"method": "POST", "required": [], "optional": []},
    "font-inspect": {"method": "POST", "required": [], "optional": ["path"]},
    "font-select": {"method": "POST", "required": ["path"], "optional": []},
    "font-upload": {
        "method": "POST",
        "required": ["filename", "content"],
        "optional": [],
    },
    "dict-validate": {
        "method": "POST",
        "required": [],
        "optional": ["path", "inputs"],
    },
    "dict-normalize": {
        "method": "POST",
        "required": [],
        "optional": ["path", "inputs", "outputDir"],
    },
    "dict-read": {
        "method": "POST",
        "required": [],
        "optional": ["path"],
    },
    "dict-default-set": {
        "method": "POST",
        "required": ["path"],
        "optional": [],
    },
    "dict-save": {
        "method": "POST",
        "required": ["content"],
        "optional": ["path"],
    },
    "project-read": {
        "method": "POST",
        "required": [],
        "optional": ["path"],
    },
    "project-save": {
        "method": "POST",
        "required": ["content"],
        "optional": ["path"],
    },
    "css-build": {
        "method": "POST",
        "required": [],
        "optional": [
            "font",
            "output",
            "assetBaseUrl",
            "fontDisplay",
            "includeTtfFallback",
        ],
    },
    "config-metadata": {"method": "POST", "required": [], "optional": []},
    "config-update": {
        "method": "POST",
        "required": ["updates"],
        "optional": ["field", "value"],
    },
    "test-text": {
        "method": "POST",
        "required": ["text"],
        "optional": ["scope", "ruleset"],
    },
}


class ActionHandler(Protocol):
    """Application boundary used by the HTTP presentation adapter."""

    def __call__(self, action: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Execute one explicitly allowed action."""


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Safe local-server settings."""

    project_root: Path = Path(".")
    host: str = "127.0.0.1"
    port: int = 8765
    static_root: Path | None = None
    fonts_root: Path = Path(".fonts")
    max_process_records: int = 64

    def resolved(self) -> ServerConfig:
        root = self.project_root.resolve()
        static = self.static_root
        if static is None:
            project_static = root / "src/shieldfont/presentation/web/static"
            static = project_static if project_static.is_dir() else (
                Path(__file__).with_name("static")
            )
        static = static.resolve()
        fonts = self.fonts_root
        if not fonts.is_absolute():
            fonts = root / fonts
        fonts = fonts.resolve()
        if not 1 <= self.port <= 65535:
            raise ShieldFontError(
                "Web server port is outside the valid range",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.config",
                details={"port": self.port},
            )
        if not 1 <= self.max_process_records <= 256:
            raise ShieldFontError(
                "Web process record limit is outside the valid range",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.config",
                details={"maxProcessRecords": self.max_process_records},
            )
        if not static.is_dir():
            raise ShieldFontError(
                "Web server static root does not exist",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.config",
                details={"staticRoot": str(static)},
            )
        try:
            fonts.relative_to(root)
        except ValueError as error:
            raise ShieldFontError(
                "Web fonts directory must be inside the project root",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.config",
                details={"fontsRoot": str(fonts)},
            ) from error
        fonts.mkdir(parents=True, exist_ok=True)
        return ServerConfig(
            project_root=root,
            host=self.host,
            port=self.port,
            static_root=static,
            fonts_root=fonts,
            max_process_records=self.max_process_records,
        )


@dataclass(frozen=True, slots=True)
class ProcessRecord:
    """Bounded, secret-free lifecycle record for one synchronous action."""

    id: str
    action: str
    status: str
    started_at: float
    completed_at: float | None = None
    result: Mapping[str, Any] | None = None
    error: Mapping[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "status": self.status,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
            "result": dict(self.result or {}),
            "error": dict(self.error or {}),
        }


class ProcessStore:
    """Small in-memory process history retained only for this server lifetime."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._records: dict[str, ProcessRecord] = {}
        self._lock = threading.Lock()

    def start(self, action: str) -> ProcessRecord:
        record = ProcessRecord(uuid4().hex, action, "running", time.time())
        with self._lock:
            self._records[record.id] = record
            self._trim()
        return record

    def complete(
        self,
        record: ProcessRecord,
        result: Mapping[str, Any],
    ) -> ProcessRecord:
        updated = ProcessRecord(
            record.id,
            record.action,
            "completed",
            record.started_at,
            time.time(),
            dict(result),
            None,
        )
        with self._lock:
            self._records[record.id] = updated
        return updated

    def fail(
        self,
        record: ProcessRecord,
        *,
        code: str,
        message: str,
    ) -> ProcessRecord:
        updated = ProcessRecord(
            record.id,
            record.action,
            "failed",
            record.started_at,
            time.time(),
            None,
            {"code": code, "message": message},
        )
        with self._lock:
            self._records[record.id] = updated
        return updated

    def get(self, record_id: str) -> ProcessRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def all(self) -> tuple[ProcessRecord, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._records.values(),
                    key=lambda item: item.started_at,
                    reverse=True,
                )
            )

    def _trim(self) -> None:
        while len(self._records) > self.limit:
            oldest = min(
                self._records,
                key=lambda key: self._records[key].started_at,
            )
            del self._records[oldest]


class ShieldFontWebServer(ThreadingHTTPServer):
    """HTTP server carrying immutable project and action context."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        config: ServerConfig,
        action_handler: ActionHandler | None = None,
    ) -> None:
        resolved = config.resolved()
        self.config = resolved
        self.action_handler = action_handler
        self.process_store = ProcessStore(resolved.max_process_records)
        super().__init__(
            (resolved.host, resolved.port),
            _RequestHandler,
        )


def create_server(
    config: ServerConfig,
    action_handler: ActionHandler | None = None,
) -> ShieldFontWebServer:
    """Create a configured server without entering its blocking loop."""

    log_event(
        LOGGER,
        logging.DEBUG,
        "Creating web server",
        stage="web.create",
        details={
            "host": config.host,
            "port": config.port,
            "projectRoot": str(config.project_root.resolve()),
        },
    )
    return ShieldFontWebServer(config, action_handler)


def serve(
    config: ServerConfig,
    action_handler: ActionHandler | None = None,
) -> None:
    """Serve the local GUI until interrupted."""

    server = create_server(config, action_handler)
    log_event(
        LOGGER,
        logging.INFO,
        "Web server started",
        stage="web.serve",
        details={"host": server.config.host, "port": server.config.port},
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        log_event(LOGGER, logging.INFO, "Web server stopped", stage="web.serve")


class _RequestHandler(BaseHTTPRequestHandler):
    server: ShieldFontWebServer

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def log_message(self, format: str, *args: object) -> None:
        log_event(
            LOGGER,
            logging.DEBUG,
            "HTTP request",
            stage="web.http",
            details={"message": format % args},
        )

    def _dispatch(self, method: str) -> None:
        started = time.perf_counter()
        path = unquote(urlsplit(self.path).path)
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        try:
            if method == "GET" and path == "/api/status":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "projectRoot": str(self.server.config.project_root),
                        "fontsRoot": str(self.server.config.fonts_root),
                        "actions": sorted(ALLOWED_ACTIONS),
                    },
                )
                status = HTTPStatus.OK
            elif method == "GET" and path in {"/api/actions", "/api/workflows"}:
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "actions": sorted(ALLOWED_ACTIONS),
                        "schemas": ACTION_SCHEMAS,
                    },
                )
                status = HTTPStatus.OK
            elif method == "GET" and path in {
                "/api/files",
                "/api/files/inventory",
                "/api/inventory",
            }:
                self._send_json(HTTPStatus.OK, self._file_inventory())
                status = HTTPStatus.OK
            elif method == "GET" and path in {"/api/config", "/api/config/metadata"}:
                self._send_json(
                    HTTPStatus.OK,
                    dict(self._invoke_action("config-metadata", {})),
                )
                status = HTTPStatus.OK
            elif method == "GET" and path == "/api/config/schema":
                self._send_json(HTTPStatus.OK, generate_schema())
                status = HTTPStatus.OK
            elif method == "GET" and path.startswith("/api/monaco-worker/"):
                status = self._serve_monaco_worker(
                    path.removeprefix("/api/monaco-worker/"),
                )
            elif method == "GET" and path.startswith("/vendor/"):
                status = self._serve_vendor_asset(path.removeprefix("/vendor/"))
            elif method == "GET" and path == "/monaco-yaml/yaml.worker.js":
                status = self._serve_monaco_worker("yaml")
            elif method == "GET" and path in {"/api/processes", "/api/process"}:
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "processes": [
                            item.to_dict()
                            for item in self.server.process_store.all()
                        ]
                    },
                )
                status = HTTPStatus.OK
            elif method == "GET" and path.startswith("/api/process/"):
                status = self._process_view(path.removeprefix("/api/process/"))
            elif method == "GET" and path in {"/api/results", "/api/result"}:
                query = parse_qs(urlsplit(self.path).query)
                result_path = query.get("path", [None])[0]
                if result_path:
                    status = self._result_view(result_path)
                else:
                    self._send_json(HTTPStatus.OK, self._result_inventory())
                    status = HTTPStatus.OK
            elif method == "GET" and path.startswith("/api/results/"):
                status = self._result_view(path.removeprefix("/api/results/"))
            elif method == "GET" and path == "/api/shieldfont.css":
                query = parse_qs(urlsplit(self.path).query)
                status = self._serve_configured_file(
                    "css",
                    query.get("path", [None])[0],
                )
            elif method == "GET" and path == "/api/source-font":
                query = parse_qs(urlsplit(self.path).query)
                status = self._serve_configured_file(
                    "source",
                    query.get("path", [None])[0],
                )
            elif method == "GET" and path.startswith("/api/fonts/"):
                status = self._serve_font_asset(path.removeprefix("/api/fonts/"))
            elif method == "GET" and path.startswith("/fonts/"):
                status = self._serve_font_asset(path.removeprefix("/fonts/"))
            elif method == "POST" and path in {
                "/api/config",
                "/api/config/update",
            }:
                status = self._handle_action("config-update")
            elif method == "POST" and path == "/api/files/select":
                status = self._handle_action("font-select")
            elif method == "POST" and path == "/api/files/upload":
                status = self._handle_font_upload()
            elif method == "POST" and path == "/api/action":
                status = self._handle_action()
            elif method == "GET":
                status = self._send_static(path)
            else:
                self._send_error(
                    HTTPStatus.NOT_FOUND,
                    ErrorCode.INVALID_INPUT.value,
                    "Route not found",
                )
                status = HTTPStatus.NOT_FOUND
        except ShieldFontError as error:
            status = HTTPStatus.BAD_REQUEST
            self._send_error(status, error.code.value, str(error))
        except ConnectionError as error:
            status = HTTPStatus.BAD_REQUEST
            log_event(
                LOGGER,
                logging.DEBUG,
                "Web client disconnected during response",
                stage="web.http",
                details={"path": path, "error": type(error).__name__},
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            status = HTTPStatus.BAD_REQUEST
            log_event(
                LOGGER,
                logging.WARNING,
                "Web request rejected",
                code=ErrorCode.INVALID_INPUT.value,
                stage="web.http",
                details={"path": path, "error": type(error).__name__},
            )
            self._send_error(
                status,
                ErrorCode.INVALID_INPUT.value,
                "Invalid request",
            )
        except Exception:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            log_event(
                LOGGER,
                logging.ERROR,
                "Unhandled web request failure",
                code=ErrorCode.GENERIC.value,
                stage="web.http",
                details={"path": path},
                exc_info=True,
            )
            self._send_error(
                status,
                ErrorCode.GENERIC.value,
                "Internal server error",
            )
        finally:
            log_event(
                LOGGER,
                logging.DEBUG,
                "Web request completed",
                stage="web.http",
                details={
                    "method": method,
                    "path": path,
                    "status": status.value,
                    "durationMs": round((time.perf_counter() - started) * 1000, 3),
                },
            )

    def _serve_monaco_worker(self, worker_name: str) -> HTTPStatus:
        if worker_name == "yaml":
            static_root = self.server.config.static_root
            if static_root is None:
                self._send_error(
                    HTTPStatus.NOT_FOUND,
                    ErrorCode.INVALID_INPUT.value,
                    "Monaco YAML worker not found",
                )
                return HTTPStatus.NOT_FOUND
            candidate = (
                static_root / "vendor/monaco-yaml.worker.js"
            ).resolve()
            static_root = static_root.resolve()
            if not _is_within(candidate, static_root) or not candidate.is_file():
                self._send_error(
                    HTTPStatus.NOT_FOUND,
                    ErrorCode.INVALID_INPUT.value,
                    "Monaco YAML worker not found",
                )
                return HTTPStatus.NOT_FOUND
            body = candidate.read_bytes()
            self.send_response(HTTPStatus.OK)
            self._send_headers(
                "application/javascript; charset=utf-8",
                len(body),
            )
            self.end_headers()
            self.wfile.write(body)
            return HTTPStatus.OK
        worker_paths = {
            "editor": Path("monaco-editor/min/vs/base/worker/workerMain.js"),
        }
        relative = worker_paths.get(worker_name)
        if relative is None:
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Unknown Monaco worker",
            )
            return HTTPStatus.NOT_FOUND
        candidate = (
            self.server.config.project_root / "node_modules" / relative
        ).resolve()
        node_modules = (self.server.config.project_root / "node_modules").resolve()
        if not _is_within(candidate, node_modules) or not candidate.is_file():
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Monaco worker not found",
            )
            return HTTPStatus.NOT_FOUND
        source = candidate.read_text(encoding="utf-8")
        if worker_name == "editor":
            source = (
                "self.MonacoEnvironment = {baseUrl: "
                "'/vendor/monaco-editor/min/'};\n"
                + source
            )
        else:
            source = _rewrite_vendor_imports(source)
        body = source.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._send_headers("application/javascript; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)
        return HTTPStatus.OK

    def _serve_vendor_asset(self, relative_name: str) -> HTTPStatus:
        if _unsafe_relative_path(relative_name):
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Vendor resource not found",
            )
            return HTTPStatus.NOT_FOUND
        relative_path = Path(relative_name)
        if not relative_path.parts:
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Vendor resource not found",
            )
            return HTTPStatus.NOT_FOUND
        package_name = (
            f"{relative_path.parts[0]}/{relative_path.parts[1]}"
            if relative_path.parts[0].startswith("@") and len(relative_path.parts) > 1
            else relative_path.parts[0]
        )
        if package_name not in VENDOR_PACKAGES:
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Vendor resource not found",
            )
            return HTTPStatus.NOT_FOUND
        candidate = (
            self.server.config.project_root / "node_modules" / relative_path
        ).resolve()
        node_modules = (self.server.config.project_root / "node_modules").resolve()
        if not candidate.is_file():
            js_candidate = Path(f"{candidate}.js")
            if js_candidate.is_file():
                candidate = js_candidate
        if not _is_within(candidate, node_modules) or not candidate.is_file():
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Vendor resource not found",
            )
            return HTTPStatus.NOT_FOUND
        body = candidate.read_bytes()
        content_type = (
            "application/javascript; charset=utf-8"
            if candidate.suffix in {".js", ".mjs"}
            else (
                FONT_CONTENT_TYPES.get(candidate.suffix.lower())
                or mimetypes.guess_type(candidate.name)[0]
                or "application/octet-stream"
            )
        )
        if candidate.suffix in {".js", ".mjs"}:
            body = _rewrite_vendor_imports(body.decode("utf-8")).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._send_headers(content_type, len(body))
        self.end_headers()
        self.wfile.write(body)
        return HTTPStatus.OK

    def _handle_action(self, forced_action: str | None = None) -> HTTPStatus:
        payload = self._read_json()
        action = forced_action or payload.get("action")
        if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
            log_event(
                LOGGER,
                logging.WARNING,
                "Unsupported web action rejected",
                code=ErrorCode.INVALID_INPUT.value,
                stage="web.action",
                details={
                    "action": action if isinstance(action, str) else None,
                    "allowedActions": sorted(ALLOWED_ACTIONS),
                },
            )
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                ErrorCode.INVALID_INPUT.value,
                "Unsupported action",
            )
            return HTTPStatus.BAD_REQUEST
        if self.server.action_handler is None:
            self._send_error(
                HTTPStatus.NOT_IMPLEMENTED,
                ErrorCode.GENERIC.value,
                "Action handling is not configured",
            )
            return HTTPStatus.NOT_IMPLEMENTED
        record = self.server.process_store.start(action)
        log_event(
            LOGGER,
            logging.INFO,
            "Web process started",
            stage="web.process.start",
            details={"action": action, "processId": record.id},
        )
        try:
            result = self.server.action_handler(action, payload)
        except ShieldFontError as error:
            failed = self.server.process_store.fail(
                record,
                code=error.code.value,
                message=str(error),
            )
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "status": "error",
                    "code": error.code.value,
                    "message": str(error),
                    "process": failed.to_dict(),
                },
            )
            return HTTPStatus.BAD_REQUEST
        except Exception:
            self.server.process_store.fail(
                record,
                code=ErrorCode.GENERIC.value,
                message="Internal action failure",
            )
            raise
        completed = self.server.process_store.complete(record, result)
        self._send_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "action": action,
                "process": completed.to_dict(),
                **dict(result),
            },
        )
        return HTTPStatus.OK

    def _handle_font_upload(self) -> HTTPStatus:
        query = parse_qs(urlsplit(self.path).query)
        filename = query.get("name", [None])[0]
        if not isinstance(filename, str) or not filename:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                ErrorCode.INVALID_INPUT.value,
                "Uploaded font filename is required",
            )
            return HTTPStatus.BAD_REQUEST
        content = self._read_binary_upload()
        if self.server.action_handler is None:
            self._send_error(
                HTTPStatus.NOT_IMPLEMENTED,
                ErrorCode.GENERIC.value,
                "Action handling is not configured",
            )
            return HTTPStatus.NOT_IMPLEMENTED
        record = self.server.process_store.start("font-upload")
        try:
            result = self.server.action_handler(
                "font-upload",
                {"filename": filename, "content": content},
            )
        except ShieldFontError as error:
            failed = self.server.process_store.fail(
                record,
                code=error.code.value,
                message=str(error),
            )
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "status": "error",
                    "code": error.code.value,
                    "message": str(error),
                    "process": failed.to_dict(),
                },
            )
            return HTTPStatus.BAD_REQUEST
        completed = self.server.process_store.complete(record, result)
        self._send_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "action": "font-upload",
                "process": completed.to_dict(),
                **dict(result),
            },
        )
        return HTTPStatus.OK

    def _invoke_action(
        self,
        action: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if self.server.action_handler is None:
            raise ShieldFontError(
                "Action handling is not configured",
                code=ErrorCode.GENERIC,
                exit_code=ExitCode.GENERIC_FAILURE,
                stage="web.action",
            )
        return self.server.action_handler(action, payload)

    def _process_view(self, process_id: str) -> HTTPStatus:
        record = self.server.process_store.get(process_id)
        if record is None:
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Process not found",
            )
            return HTTPStatus.NOT_FOUND
        self._send_json(HTTPStatus.OK, {"process": record.to_dict()})
        return HTTPStatus.OK

    def _file_inventory(self) -> dict[str, Any]:
        query = parse_qs(urlsplit(self.path).query)
        requested_kind = query.get("kind", ["all"])[0]
        requested_kind = {
            "fonts": "font",
            "dictionaries": "dictionary",
            "corpora": "corpus",
            "artifacts": "artifact",
        }.get(requested_kind, requested_kind)
        if requested_kind not in {"all", "font", "dictionary", "corpus", "artifact"}:
            raise ShieldFontError(
                "Unsupported file inventory kind",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.files",
            )
        root = self.server.config.project_root
        entries: list[dict[str, Any]] = []
        ignored = {".git", ".ai-factory", ".shieldfont", "node_modules", "__pycache__"}
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if any(part in ignored for part in relative.parts):
                continue
            kind = _file_kind(
                relative,
                self.server.config.fonts_root.relative_to(root),
            )
            if requested_kind != "all" and kind != requested_kind:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            entries.append(
                {"path": relative.as_posix(), "kind": kind, "size": size}
            )
        return {"files": entries, "kind": requested_kind}

    def _result_inventory(self) -> dict[str, Any]:
        root = self.server.config.project_root / "dist"
        if not root.is_dir():
            return {"results": []}
        results: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink() or _sensitive_result(path):
                continue
            relative = path.relative_to(self.server.config.project_root)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            results.append(
                {
                    "path": relative.as_posix(),
                    "kind": _file_kind(relative),
                    "size": size,
                }
            )
        return {"results": results}

    def _result_view(self, encoded_path: str) -> HTTPStatus:
        relative = Path(unquote(encoded_path))
        root = self.server.config.project_root / "dist"
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or _sensitive_result(relative)
        ):
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Result not found",
            )
            return HTTPStatus.NOT_FOUND
        candidate = (self.server.config.project_root / relative).resolve()
        if not _is_within(candidate, root.resolve()) or not candidate.is_file():
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Result not found",
            )
            return HTTPStatus.NOT_FOUND
        current = self.server.config.project_root
        if any(
            (current := current / part_name).is_symlink()
            for part_name in relative.parts
        ):
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Result not found",
            )
            return HTTPStatus.NOT_FOUND
        try:
            body = candidate.read_bytes()
        except OSError:
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Result not found",
            )
            return HTTPStatus.NOT_FOUND
        if len(body) > MAX_RESULT_BYTES:
            self._send_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                ErrorCode.INVALID_INPUT.value,
                "Result is too large to view",
            )
            return HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        if candidate.suffix.lower() == ".json":
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_error(
                    HTTPStatus.NOT_FOUND,
                    ErrorCode.INVALID_INPUT.value,
                    "Result is not readable",
                )
                return HTTPStatus.NOT_FOUND
            self._send_json(
                HTTPStatus.OK,
                {"path": relative.as_posix(), "result": payload},
            )
            return HTTPStatus.OK
        self._send_json(
            HTTPStatus.OK,
            {
                "path": relative.as_posix(),
                "content": body.decode("utf-8", errors="replace"),
            },
        )
        return HTTPStatus.OK

    def _read_json(self) -> dict[str, Any]:
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit() or int(length) > MAX_REQUEST_BYTES:
            raise ShieldFontError(
                "Request body is missing or too large",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.request",
            )
        raw = self.rfile.read(int(length))
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ShieldFontError(
                "Request body must be a JSON object",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.request",
            )
        return payload

    def _read_binary_upload(self) -> bytes:
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit():
            raise ShieldFontError(
                "Uploaded font size is missing",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.upload",
            )
        size = int(length)
        if size <= 0 or size > 32 * 1024 * 1024:
            raise ShieldFontError(
                "Uploaded font is empty or too large",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.upload",
            )
        content = self.rfile.read(size)
        if len(content) != size:
            raise ShieldFontError(
                "Uploaded font body is incomplete",
                code=ErrorCode.INVALID_INPUT,
                exit_code=ExitCode.INVALID_INPUT,
                stage="web.font.upload",
            )
        return content

    def _send_static(self, request_path: str) -> HTTPStatus:
        static_root = self.server.config.static_root
        if static_root is None:
            raise RuntimeError("resolved server config has no static root")
        relative = "index.html" if request_path == "/" else unquote(request_path[1:])
        if _unsafe_relative_path(relative):
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Resource not found",
            )
            return HTTPStatus.NOT_FOUND
        candidate = (static_root / relative).resolve()
        if not _is_within(candidate, static_root):
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Resource not found",
            )
            return HTTPStatus.NOT_FOUND
        if not candidate.is_file():
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Resource not found",
            )
            return HTTPStatus.NOT_FOUND
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or (
            "application/octet-stream"
        )
        self.send_response(HTTPStatus.OK)
        self._send_headers(content_type, len(body))
        self.end_headers()
        self.wfile.write(body)
        return HTTPStatus.OK

    def _serve_configured_file(
        self,
        kind: str,
        requested_path: str | None = None,
    ) -> HTTPStatus:
        config = load_config(self.server.config.project_root / "shieldfont.yml")
        candidate = (
            Path(requested_path)
            if requested_path and kind in {"css", "source"}
            else config.project.output_dir / "shieldfont.css"
            if kind == "css"
            else config.source.path
        )
        if not candidate.is_absolute():
            candidate = self.server.config.project_root / candidate
        candidate = candidate.resolve()
        if kind == "css" and candidate.suffix.lower() != ".css":
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Configured resource not found",
            )
            return HTTPStatus.NOT_FOUND
        if kind == "source" and candidate.suffix.lower() not in {
            ".ttf",
            ".woff",
            ".woff2",
            ".otf",
        }:
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Configured resource not found",
            )
            return HTTPStatus.NOT_FOUND
        if (
            not _is_within(candidate, self.server.config.project_root)
            or not candidate.is_file()
        ):
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Configured resource not found",
            )
            return HTTPStatus.NOT_FOUND
        if kind == "source" and not _is_within(
            candidate,
            self.server.config.fonts_root.resolve(),
        ):
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Configured resource not found",
            )
            return HTTPStatus.NOT_FOUND
        content_type = (
            "text/css; charset=utf-8"
            if kind == "css"
            else mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        )
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._send_headers(content_type, len(body))
        self.end_headers()
        self.wfile.write(body)
        return HTTPStatus.OK

    def _serve_font_asset(self, relative_name: str) -> HTTPStatus:
        if _unsafe_relative_path(relative_name):
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Font resource not found",
            )
            return HTTPStatus.NOT_FOUND
        relative = Path(relative_name)
        if relative.suffix.lower() not in {".ttf", ".woff", ".woff2", ".otf"}:
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Font resource not found",
            )
            return HTTPStatus.NOT_FOUND
        candidates = (
            self.server.config.project_root / "dist" / "fonts" / relative,
            self.server.config.fonts_root / relative,
        )
        candidate = next(
            (
                path.resolve()
                for path in candidates
                if _is_within(path, self.server.config.project_root) and path.is_file()
            ),
            None,
        )
        if candidate is None:
            self._send_error(
                HTTPStatus.NOT_FOUND,
                ErrorCode.INVALID_INPUT.value,
                "Font resource not found",
            )
            return HTTPStatus.NOT_FOUND
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._send_headers(
            FONT_CONTENT_TYPES.get(candidate.suffix.lower())
            or mimetypes.guess_type(candidate.name)[0]
            or "application/octet-stream",
            len(body),
        )
        self.end_headers()
        self.wfile.write(body)
        return HTTPStatus.OK

    def _send_json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self._send_headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, code: str, message: str) -> None:
        self._send_json(status, {"status": "error", "code": code, "message": message})

    def _send_headers(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "worker-src 'self' blob:; "
            "font-src 'self' data:; "
            "img-src 'self' data:;",
        )
        self.send_header("X-Frame-Options", "DENY")


def _unsafe_relative_path(value: str) -> bool:
    parts = value.replace("\\", "/").split("/")
    return value.startswith(("/", "\\")) or ".." in parts or any(
        not part or part == "." for part in parts
    )


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _rewrite_vendor_imports(source: str) -> str:
    source = re.sub(
        r'^\s*import\s+["\'][^"\']+\.css["\'];?\s*$',
        "",
        source,
        flags=re.MULTILINE,
    )
    return re.sub(
        r'(\bfrom\s+|\bimport\s*)(["\'])([^"\']+)(["\'])',
        lambda match: (
            match.group(0)
            if match.group(2) != match.group(4)
            else (
                f"{match.group(1)}{match.group(2)}"
                f"{VENDOR_IMPORTS.get(match.group(3), match.group(3))}"
                f"{match.group(4)}"
            )
        ),
        source,
    )


def _file_kind(path: Path, fonts_root: Path = Path(".fonts")) -> str:
    suffix = path.suffix.lower()
    root_parts = tuple(part.lower() for part in fonts_root.parts)
    path_parts = tuple(part.lower() for part in path.parts[: len(root_parts)])
    if suffix in {".ttf", ".woff2"} and path_parts == root_parts:
        return "font"
    if suffix == ".csv":
        return "dictionary"
    if suffix in {".txt", ".md", ".markdown", ".html", ".htm"}:
        return "corpus"
    if path.parts and path.parts[0] == "dist":
        return "artifact"
    return "other"


def _sensitive_result(path: Path) -> bool:
    lowered = path.name.lower()
    return (
        "maps" in {part.lower() for part in path.parts}
        or "mapping" in lowered
        or lowered in {"ruleset.json", "sha256sums"}
        or ".inverse." in lowered
        or any(
            marker in lowered
            for marker in ("candidate", "approved", "reviewed")
        )
    )
