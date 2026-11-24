"""Uso manual: `python -m deep_agents.streaming "pergunta" [--level primary|secondary|debug] [--jsonl saida.jsonl]`.

Roda o agente real (bootstrap) e imprime os eventos como linhas de texto; a resposta sai palavra a palavra."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from deep_agents.streaming import AgentStreamer, EventKind, Phase, Visibility  # noqa: E402
from deep_agents.streaming.adapters import JsonlSink  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m deep_agents.streaming")
    ap.add_argument("question")
    ap.add_argument("--level", choices=[v.value for v in Visibility], default="secondary")
    ap.add_argument("--jsonl", help="grava todos os eventos (JSON por linha) neste arquivo")
    args = ap.parse_args(argv)

    from deep_agents.bootstrap import STREAMING, build_backend   # import tardio: --help não monta o agente

    backend = build_backend()
    sinks = [JsonlSink(args.jsonl)] if args.jsonl else []
    streamer = AgentStreamer(backend.agent, backend.gateway, options=STREAMING,
                             channel=backend.toolkit.channel, sinks=sinks)
    limit = Visibility(args.level)
    handle = streamer.start([{"role": "user", "content": args.question}])
    try:
        for ev in handle:
            if ev.visibility > limit:
                continue
            if ev.kind is EventKind.RESPONSE and ev.phase is Phase.DELTA:
                print(ev.data.get("text", ""), end="", flush=True)
                continue
            ind = "  " * ev.depth
            print(f"\n{ind}[{ev.seq}] {ev.kind.value}/{ev.phase.value} {ev.label or ev.name or ''}", end="", flush=True)
    except KeyboardInterrupt:
        handle.cancel()
    print()
    res = handle.join()
    for sink in sinks:
        sink.close()
    if res.error:
        print(f"ERRORE: {res.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
