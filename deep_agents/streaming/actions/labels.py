"""Rótulos em italiano para cada passo (campo `label` do StreamEvent) e resumos de argumentos por tool."""

from __future__ import annotations

from typing import Callable

from deep_agents.streaming.actions.summarize import clip
from deep_agents.streaming.events import EventKind, Phase

# Resumo personalizado por tool: recebe os argumentos da chamada e devolve o texto mostrado ao lado do nome.
TOOL_SUMMARIES: dict[str, Callable[[dict], str]] = {
    "internet_search": lambda args: f"«{args['query']}»" if args.get("query") else "",
}

_GENERIC_KEYS = ("query", "path", "file_path", "url", "pattern")

_FILE_VERBS = {
    "ls": "Elenco", "read_file": "Leggo", "write_file": "Scrivo", "edit_file": "Modifico",
    "glob": "Cerco", "grep": "Cerco",
}
_ASYNC_VERBS = {
    "start": "Avvio un subagent asincrono",
    "check": "Controllo il subagent asincrono",
    "update": "Aggiorno il subagent asincrono",
    "cancel": "Annullo il subagent asincrono",
    "list": "Elenco i subagent asincroni",
}


def tool_hint(name: str | None, args: dict | None, limit: int = 80) -> str:
    """«argomento principale» para mostrar junto ao nome da tool ('' se não houver)."""
    args = args or {}
    custom = TOOL_SUMMARIES.get(name or "")
    if custom is not None:
        try:
            return clip(custom(args), limit)
        except Exception:
            return ""
    for key in _GENERIC_KEYS:
        if isinstance(args.get(key), str) and args[key]:
            return f"«{clip(args[key], limit)}»"
    return ""


def _with(text: str, hint: str) -> str:
    return f"{text} {hint}" if hint else text


def _quoted(text: object, limit: int = 80) -> str:
    return f"«{clip(text, limit)}»" if text else ""


def label(kind: EventKind | str, phase: Phase | str, name: str | None = None,
          args: dict | None = None, data: dict | None = None) -> str:
    """Texto pronto, em italiano, do passo (`kind`/`phase`). `data` é o `data` do evento."""
    kind, phase = EventKind(kind), Phase(phase)
    args, data = args or {}, data or {}
    name = name or "?"
    start, end, error = phase == Phase.START, phase == Phase.END, phase == Phase.ERROR

    if kind == EventKind.MODEL_CALL:
        if data.get("purpose") == "summary":
            return "Riassumo il contesto…" if start else ("Contesto riassunto" if end else "Riassunto non riuscito")
        if start:
            return "Interrogo il modello…"
        if error:
            return "Chiamata al modello non riuscita"
        calls = (data.get("decision") or {}).get("tool_calls") or []
        return f"Il modello decide: {', '.join(c.get('name', '?') for c in calls)}" if calls else "Il modello risponde"
    if kind == EventKind.SUBAGENT:
        if start:
            return f"Consulto il subagent {_with(name, _quoted(data.get('description') or args.get('description')))}…"
        return f"Il subagent {name} ha terminato" if end else f"Il subagent {name} è in errore"
    if kind == EventKind.SUBAGENT_DYNAMIC:
        if start:
            return f"Avvio il subagent dinamico {_with(name, _quoted(data.get('description')))}…"
        if end:
            return f"Subagent dinamico {name} completato"
        return f"Subagent dinamico {name} in errore" if error else f"Subagent dinamico {name}"
    if kind == EventKind.SKILL:
        skill = data.get("skill") or name
        return f"Lettura della skill {skill} non riuscita" if error else f"Leggo la skill {skill}"
    if kind == EventKind.TODOS:
        if error:
            return "Aggiornamento del piano non riuscito"
        done, total = data.get("done"), data.get("total")
        return f"Aggiorno il piano ({done}/{total})" if done is not None and total is not None else "Aggiorno il piano"
    if kind == EventKind.FILE:
        op = data.get("op") or name
        text = _with(_FILE_VERBS.get(op, "Uso"), _quoted(data.get("path") or data.get("pattern")))
        return f"{text} — errore" if error else text
    if kind == EventKind.CODE_EVAL:
        return "Eseguo codice nel REPL (eval)" if start else ("Codice eseguito (eval)" if end else "Errore nel codice (eval)")
    if kind == EventKind.ASYNC_TASK:
        base = _ASYNC_VERBS.get(data.get("action") or "start", "Subagent asincrono")
        return f"{base}…" if start else (f"{base}: fatto" if end else f"{base}: errore")
    if kind == EventKind.SUMMARIZATION:
        if start:
            return "Riassumo il contesto…"
        return "Riassunto non riuscito" if error else "Contesto riassunto"
    if kind == EventKind.INTERRUPT:
        return "In attesa di una conferma…"
    if kind == EventKind.GRAPH_STEP:
        return f"Passo del grafo: {data.get('node') or name}"
    if kind == EventKind.CUSTOM:
        return "Evento personalizzato"
    if kind == EventKind.TOOL:
        if start:
            return f"Consulto lo strumento {_with(name, tool_hint(name, args))}…"
        return f"Strumento {name} completato" if end else f"Strumento {name} in errore"
    return ""
