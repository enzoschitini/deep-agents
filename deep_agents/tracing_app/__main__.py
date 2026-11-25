"""python -m deep_agents.tracing_app [--port 8100] [--data-dir PASTA] [--no-browser] | --build saida.html | --check | --smoke [--route R ...]"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from deep_agents.tracing.options import DEFAULT_DIR  # noqa: E402
from deep_agents.tracing_app.build import build_html, check_syntax  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m deep_agents.tracing_app", description="Interface do rastreamento (HTML único + API local).")
    ap.add_argument("--host", default="127.0.0.1", help="só 127.0.0.1/localhost são aceitos (dados locais)")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DIR, help=f"pasta dos JSONs do tracing (padrão: {DEFAULT_DIR})")
    ap.add_argument("--no-browser", action="store_true", help="não abre o navegador")
    ap.add_argument("--build", type=Path, metavar="SAIDA.html", help="só grava o HTML único e sai")
    ap.add_argument("--check", action="store_true", help="valida a sintaxe do JS/CSS e sai")
    ap.add_argument("--smoke", action="store_true", help="roda o front-end sem navegador (QuickJS + DOM falso) em todas as rotas e sai (1 se algo falhar)")
    ap.add_argument("--route", action="append", metavar="ROTA", help="com --smoke: só esta rota (repetível), ex.: '#/runs/{run}?tab=events' ({run} {session} {config} viram ids reais)")
    ap.add_argument("--smoke-verbose", action="store_true", help="com --smoke: mostra todos os avisos e os stacks completos")
    args = ap.parse_args(argv)

    if args.check:
        errors = check_syntax()
        for e in errors:
            print("ERRO", e)
        print("ok: JS/CSS sem erros de sintaxe" if not errors else f"{len(errors)} erro(s)")
        return 1 if errors else 0
    if args.smoke:
        from deep_agents.tracing_app.smoke.runner import run as smoke_run   # import tardio: só --smoke precisa do QuickJS/shim
        report = smoke_run(args.data_dir, routes=args.route, verbose=args.smoke_verbose)
        return 0 if report.ok else 1
    if args.build:
        args.build.write_text(build_html(), encoding="utf-8")
        print(f"HTML gravado em {args.build} ({args.build.stat().st_size / 1024:.0f} KB)")
        return 0

    from deep_agents.tracing_app.server import make_server   # import tardio: --check/--build não precisam do servidor
    server = make_server(args.data_dir, args.host, args.port)
    url = f"http://{args.host}:{server.server_address[1]}/"
    print(f"Tracing em {url}   (dados: {args.data_dir})   Ctrl+C para sair")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
