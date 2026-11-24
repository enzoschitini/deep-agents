"""Servidor HTTP (só biblioteca padrão): serve `frontend/` e a API do agente.

  GET  /api/state          modelo, sessão atual, mensagens e lista de sessões
  POST /api/chat           {"message": "..."} -> fluxo SSE com os eventos de `ChatService`
  POST /api/model          {"model": "provider:modello"} cambia il modello (come /modello nella CLI)
  POST /api/session/rename {"id", "title"} dà un nome alla sessione (titolo vuoto = automatico)
  POST /api/session/delete {"id": "..."} e /api/session/delete_all eliminano le sessioni (anche per la CLI)
  POST /api/session/new    começa uma sessão vazia
  POST /api/session/resume {"id": "..."} retoma uma sessão salva

Escuta só em 127.0.0.1: o agente gasta crédito de API e tem acesso à pasta do pacote."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from deep_agents.server.chat_service import ChatService

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
MAX_BODY = 64 * 1024


class Handler(SimpleHTTPRequestHandler):
    service: ChatService   # definido em `make_server`

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def log_message(self, format, *args) -> None:   # silencioso: o terminal é do `rich`/logs do agente
        pass

    # ------------------------------------------------------------------ helpers
    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return {}
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _same_origin(self) -> bool:
        """Bloqueia POSTs vindos de outras páginas abertas no navegador (CSRF): o agente tem custo e acesso a arquivos."""
        origin = self.headers.get("Origin")
        return origin is None or origin == f"http://{self.headers.get('Host')}"

    # ------------------------------------------------------------------- rotas
    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/api/state":
            return self._json(self.service.state())
        super().do_GET()

    def do_POST(self) -> None:
        if not self._same_origin():
            return self._json({"error": "origine non consentita"}, HTTPStatus.FORBIDDEN)
        route, body = self.path.split("?")[0], self._body()
        if route == "/api/chat":
            return self._chat(str(body.get("message", "")).strip())
        if route == "/api/model":
            error = self.service.set_model(str(body.get("model", "")))
            return self._json(self.service.state() if error is None else {"error": error}, 200 if error is None else HTTPStatus.CONFLICT)
        if route == "/api/session/rename":
            ok = self.service.rename_session(str(body.get("id", "")), str(body.get("title", "")))
            return self._json(self.service.state() if ok else {"error": "sessione non trovata"}, 200 if ok else HTTPStatus.NOT_FOUND)
        if route == "/api/session/delete":
            ok = self.service.delete_session(str(body.get("id", "")))
            return self._json(self.service.state() if ok else {"error": "sessione non trovata o risposta in corso"}, 200 if ok else HTTPStatus.CONFLICT)
        if route == "/api/session/delete_all":
            ok = self.service.delete_all_sessions()
            return self._json(self.service.state() if ok else {"error": "risposta in corso"}, 200 if ok else HTTPStatus.CONFLICT)
        if route == "/api/session/new":
            ok = self.service.new_session()
            return self._json(self.service.state() if ok else {"error": "risposta in corso"}, 200 if ok else HTTPStatus.CONFLICT)
        if route == "/api/session/resume":
            ok = self.service.resume(str(body.get("id", "")))
            return self._json(self.service.state() if ok else {"error": "sessione non trovata o risposta in corso"}, 200 if ok else HTTPStatus.CONFLICT)
        self._json({"error": "non trovato"}, HTTPStatus.NOT_FOUND)

    def _chat(self, message: str) -> None:
        if not message:
            return self._json({"error": "messaggio vuoto"}, HTTPStatus.BAD_REQUEST)
        events = self.service.send(message)
        if events is None:
            return self._json({"error": "c'è già una risposta in corso"}, HTTPStatus.CONFLICT)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in events:   # se o navegador fechar, o turno termina e é gravado do mesmo jeito
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError):
            for _ in events:   # esgota a fila: a thread do turno não pode ficar bloqueada
                pass
        self.close_connection = True


def make_server(service: ChatService, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"service": service})
    server = _Server((host, port), handler)
    server.daemon_threads = True
    return server


class _Server(ThreadingHTTPServer):
    # No Windows, SO_REUSEADDR deixa DOIS processos escutarem a mesma porta (um deles responde às cegas):
    # desligado, uma segunda instância falha na hora com "porta já em uso".
    allow_reuse_address = False
