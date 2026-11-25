"""Servidor HTTP da interface do rastreamento (só biblioteca padrão, só leitura).

  GET /            o HTML único (`build.build_html()`, montado a cada request: editar `src/` e recarregar basta)
  GET /api/...     JSON (ver README.md): meta, runs, runs/<id>[/trace|/spans/<id>|/files/<nome>], sessions[/<id>], stats,
                   configs[/<hash>|/diff], llm_calls, tool_calls
  erros            `{"error": "mensagem"}` com 400/403/404/405/500 (o 500 não leva stacktrace no corpo; ele vai ao stderr)

Escuta só em 127.0.0.1/localhost/::1 e rejeita `Origin`/`Host` de outro host (como `deep_agents/server/app.py`)."""

from __future__ import annotations

import json
import socket
import sys
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from deep_agents.tracing_app.build import build_html
from deep_agents.tracing_app.repository import ApiError, TraceRepository

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _hostname(netloc: str) -> str:
    """Nome do host de um `Host:`/`Origin:` (sem porta; aceita [::1])."""
    netloc = netloc.strip().lower()
    if netloc.startswith("["):
        return netloc[1: netloc.find("]")] if "]" in netloc else netloc
    return netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 else netloc


class Handler(BaseHTTPRequestHandler):
    repository: TraceRepository   # definido em `make_server`
    server_version = "TracingApp"

    def log_message(self, format, *args) -> None:   # silencioso: sem spam de requests
        pass

    def log_error(self, format, *args) -> None:
        print("tracing_app:", format % args, file=sys.stderr)

    # ------------------------------------------------------------------ respostas
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    # ------------------------------------------------------------------ segurança
    def _allowed(self) -> bool:
        """Só hosts locais (contra DNS rebinding) e, se houver `Origin`, só o mesmo host (contra páginas de outros sites)."""
        if _hostname(self.headers.get("Host", "")) not in LOCAL_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        if origin == "null":
            return False
        return _hostname(urlsplit(origin).netloc) in LOCAL_HOSTS and urlsplit(origin).netloc == self.headers.get("Host")

    # ------------------------------------------------------------------ rotas
    def _handle(self) -> None:
        try:
            if not self._allowed():
                return self._error(HTTPStatus.FORBIDDEN, "origem não permitida")
            url = urlsplit(self.path)
            path = unquote(url.path)
            if path in ("/", "/index.html"):
                return self._send(200, build_html().encode("utf-8"), "text/html; charset=utf-8")
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if path == "/api" or path.startswith("/api/"):
                params = dict(parse_qsl(url.query, keep_blank_values=False))
                return self._json(self.repository.dispatch(path[len("/api"):], params))
            self._error(HTTPStatus.NOT_FOUND, "não encontrado")
        except ApiError as e:
            self._error(e.status, e.message)
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception:   # nunca vaza stacktrace no corpo
            traceback.print_exc(file=sys.stderr)
            try:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "erro interno do servidor")
            except Exception:
                pass

    def do_GET(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def _method_not_allowed(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        body = json.dumps({"error": "só GET (a interface é somente leitura)"}).encode("utf-8")
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_PUT = do_DELETE = do_PATCH = _method_not_allowed


class _Server(ThreadingHTTPServer):
    # No Windows, SO_REUSEADDR deixa DOIS processos escutarem a mesma porta: desligado, a segunda instância falha na hora.
    allow_reuse_address = False
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:   # erros de conexão (cliente fechou) não viram ruído
        exc = sys.exc_info()[1]
        if not isinstance(exc, (BrokenPipeError, ConnectionError)):
            traceback.print_exc(file=sys.stderr)


class _Server6(_Server):
    address_family = socket.AF_INET6


def make_server(data_dir: Path | str, host: str = "127.0.0.1", port: int = 8100) -> ThreadingHTTPServer:
    """Servidor pronto (ainda sem `serve_forever`). `port=0` escolhe uma porta livre (`server.server_address[1]`)."""
    if host not in LOCAL_HOSTS:
        raise ValueError(f"host {host!r} não permitido: use 127.0.0.1, localhost ou ::1 (os dados são locais)")
    handler = type("BoundHandler", (Handler,), {"repository": TraceRepository(Path(data_dir))})
    server = (_Server6 if host == "::1" else _Server)((host, port), handler)
    server.repository = handler.repository   # type: ignore[attr-defined]
    return server
