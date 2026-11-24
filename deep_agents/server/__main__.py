import argparse
import sys
from pathlib import Path

# Permite rodar direto (botão Play / `python arquivo.py`): coloca a raiz do repo no sys.path.
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from deep_agents.bootstrap import MODEL, build_backend  # noqa: E402
from deep_agents.server.app import make_server  # noqa: E402
from deep_agents.server.chat_service import ChatService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Interfaccia web per l'agente (stesso agente e stessa memoria della CLI).")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1", help="default: solo questo computer")
    args = parser.parse_args()

    try:
        backend = build_backend(MODEL)
    except Exception as e:
        sys.exit(f"Errore nella creazione dell'agente con {MODEL.spec}: {type(e).__name__}: {e}")
    server = make_server(ChatService(backend), args.host, args.port)
    print(f"Agente pronto ({backend.gateway.config.spec}). Apri http://{args.host}:{args.port}  (Ctrl+C per uscire)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrivederci.")
    finally:
        server.server_close()


# python -m deep_agents.server
if __name__ == "__main__":
    main()
