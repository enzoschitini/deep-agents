"""TraceRepository: leitura (só leitura) dos JSONs do `tracing/` e cálculo de listas, filtros e agregados da API.

A fonte de verdade são os `runs/*/run.json` (o `index.json` pode estar defasado e só serve de reserva se um `run.json`
estiver ilegível). Os demais arquivos de um run são lidos sob demanda. Tudo é tolerante: JSON corrompido, run em andamento
(só `run.json` parcial) ou campo ausente nunca derrubam uma listagem. Cache por (caminho, mtime, tamanho), thread-safe.

Rotas: `TraceRepository.dispatch(path, params)` recebe o caminho depois de `/api` (ex.: `"/runs/abc/trace"`) e os parâmetros
da query (dict nome -> texto) e devolve o objeto JSON; erros viram `ApiError` (400/404). O servidor só serializa.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_FILE = re.compile(r"^[A-Za-z0-9._-]+\.json$")
_REL = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhdw])$", re.I)
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
PREVIEW = 160
RUN_SORTS = ("started_at", "duration_s", "total_tokens", "input_tokens", "output_tokens", "cost_usd", "llm_calls", "tool_calls", "ttft_s")
LLM_SORTS = ("started_at", "agent", "purpose", "model", "status", "input_tokens", "output_tokens", "cache_read_tokens", "cost_usd",
             "latency_s", "ttft_s", "run_id")
TOOL_SORTS = ("started_at", "name", "kind", "agent", "status", "duration_s", "output_chars", "run_id")
_MISSING = object()


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def _bad(msg: str) -> ApiError:
    return ApiError(400, msg)


def _nf(msg: str) -> ApiError:
    return ApiError(404, msg)


# ------------------------------------------------------------------------------------------------- utilidades
def _epoch(value: Any) -> float | None:
    """ISO-8601 (com ou sem fuso; sem fuso = UTC) -> epoch; None se não der."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="milliseconds")


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return v


def _r(v: float | None, n: int = 4) -> float | None:
    return None if v is None else round(v, n)


def _pct(values: list[float], q: float) -> float | None:
    """Percentil `q` (0..100) com interpolação linear."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _text_of(content: Any) -> str:
    """Texto de um `content` do LangChain (str, lista de blocos ou dict)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                t = b.get("text")
                if isinstance(t, str):
                    parts.append(t)
                elif b.get("type") in ("function_call", "tool_use"):
                    parts.append(f"[{b.get('name', 'tool')}]")
                elif b.get("type") == "thinking" or b.get("type") == "reasoning":
                    continue
                else:
                    parts.append(f"[{b.get('type', 'bloco')}]")
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        t = content.get("text")
        return t if isinstance(t, str) else json.dumps(content, ensure_ascii=False, default=str)
    return str(content)


def _preview(text: Any, n: int = PREVIEW) -> str:
    s = re.sub(r"\s+", " ", text if isinstance(text, str) else _text_of(text)).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _flag(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on", "sim")


def _safe_name(value: str, what: str) -> str:
    if not isinstance(value, str) or not _NAME.match(value) or ".." in value or value.startswith("."):
        raise _bad(f"{what} inválido")
    return value


def _int_param(params: Mapping[str, str], key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(float(params.get(key, default)))
    except (TypeError, ValueError):
        raise _bad(f"parâmetro {key} inválido") from None
    return max(lo, min(hi, v))


def _float_param(params: Mapping[str, str], key: str) -> float | None:
    raw = params.get(key)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError:
        raise _bad(f"parâmetro {key} inválido") from None


def parse_time(value: str | None, now: float | None = None) -> float | None:
    """`since`/`until`: ISO-8601 ou relativo (`30m`, `1h`, `24h`, `7d`, `30d`, `2w`) a partir de agora."""
    if value in (None, "", "all"):
        return None
    m = _REL.match(value.strip())
    if m:
        return (now if now is not None else time.time()) - float(m.group(1)) * _UNIT[m.group(2).lower()]
    ts = _epoch(value)
    if ts is None:
        raise _bad(f"data inválida: {value!r} (use ISO-8601 ou 1h/24h/7d/30d)")
    return ts


def _sort_key_none_last(rows: list[dict], key: str, order: str) -> list[dict]:
    present = [r for r in rows if r.get(key) is not None]
    absent = [r for r in rows if r.get(key) is None]
    present.sort(key=lambda r: (str(r[key]).lower() if isinstance(r[key], str) else r[key]), reverse=(order != "asc"))
    return present + absent


# ----------------------------------------------------------------------------------------------- cache de JSON
class _JsonCache:
    """LRU de JSONs lidos, chave = (caminho, mtime, tamanho); o limite é a soma dos tamanhos dos arquivos em disco."""

    def __init__(self, max_bytes: int = 160 * 1024 * 1024) -> None:
        self._d: OrderedDict[str, tuple[int, int, Any]] = OrderedDict()
        self._bytes = 0
        self._max = max_bytes
        self._lock = threading.Lock()

    def get(self, path: Path) -> Any:
        """Objeto do JSON, ou `_MISSING` se o arquivo não existe / está ilegível / não é JSON."""
        try:
            st = path.stat()
        except OSError:
            return _MISSING
        key = str(path)
        with self._lock:
            hit = self._d.get(key)
            if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
                self._d.move_to_end(key)
                return hit[2]
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _MISSING
        with self._lock:
            old = self._d.pop(key, None)
            if old:
                self._bytes -= old[1]
            self._d[key] = (st.st_mtime_ns, st.st_size, obj)
            self._bytes += st.st_size
            while self._bytes > self._max and len(self._d) > 1:
                _, (_, size, _) = self._d.popitem(last=False)
                self._bytes -= size
        return obj


# ------------------------------------------------------------------------------------------------ repositório
class TraceRepository:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self._json = _JsonCache()
        self._items: dict[str, tuple[int, int, dict, str]] = {}   # run.json -> (mtime, size, item, texto de busca)
        self._derived: dict[tuple[str, str], tuple[int, int, Any]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------------------------------ arquivos
    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    def _read(self, path: Path, default: Any = None) -> Any:
        obj = self._json.get(path)
        return default if obj is _MISSING else obj

    def _run_dir(self, run_id: str) -> Path:
        _safe_name(run_id, "run_id")
        d = self.runs_dir / run_id
        if not d.is_dir():
            raise _nf(f"run não encontrado: {run_id}")
        return d

    def _run_file(self, run_id: str, name: str, default: Any = None) -> Any:
        return self._read(self._run_dir(run_id) / name, default)

    def _index_entries(self) -> dict[str, dict]:
        idx = self._read(self.data_dir / "index.json", {})
        runs = idx.get("runs") if isinstance(idx, dict) else None
        return {r["run_id"]: r for r in runs if isinstance(r, dict) and isinstance(r.get("run_id"), str)} if isinstance(runs, list) else {}

    # ------------------------------------------------------------------------------------------ itens de run
    def _build_item(self, run_id: str, run: dict | None, entry: dict | None) -> dict:
        run = run if isinstance(run, dict) else {}
        entry = entry if isinstance(entry, dict) else {}
        ie = run.get("index_entry") if isinstance(run.get("index_entry"), dict) else entry
        totals = run.get("totals") if isinstance(run.get("totals"), dict) else {}
        timing = run.get("timing") if isinstance(run.get("timing"), dict) else {}
        inp = run.get("input") if isinstance(run.get("input"), dict) else {}
        out = run.get("output") if isinstance(run.get("output"), dict) else {}
        model = run.get("model") if isinstance(run.get("model"), dict) else {}
        by_tool = run.get("by_tool") if isinstance(run.get("by_tool"), dict) else {}

        def pick(key: str, *alts: Any) -> Any:
            if key in totals and totals[key] is not None:
                return totals[key]
            if ie.get(key) is not None:
                return ie[key]
            return alts[0] if alts else None

        tin, tout = _num(pick("input_tokens")), _num(pick("output_tokens"))
        total = _num(totals.get("total_tokens"))
        if total is None and (tin is not None or tout is not None):
            total = (tin or 0) + (tout or 0)
        answer = out.get("answer") if isinstance(out.get("answer"), str) else None
        user_message = inp.get("user_message") if isinstance(inp.get("user_message"), str) else (ie.get("user_message") or "")
        duration = _num(run.get("duration_s"))
        if duration is None:
            duration = _num(ie.get("duration_s"))
        if duration is None:
            duration = _num(timing.get("wall_time_s"))
        skills = run.get("skills_used") if isinstance(run.get("skills_used"), list) else []
        item = {
            "run_id": run_id,
            "session_id": run.get("session_id", ie.get("session_id")),
            "turn": run.get("turn", ie.get("turn")),
            "origin": run.get("origin", ie.get("origin")),
            "status": run.get("status") or ie.get("status") or "unfinished",
            "started_at": run.get("started_at") or ie.get("started_at"),
            "ended_at": run.get("ended_at"),
            "duration_s": duration,
            "label": run.get("label"),
            "user_message": user_message if len(user_message) <= 1000 else user_message[:1000] + "…",
            "answer_preview": (answer[:300] + ("…" if len(answer) > 300 else "")) if answer is not None else ie.get("answer_preview"),
            "model": model.get("spec") or ie.get("model"),
            "config_hash": run.get("config_hash") or ie.get("config_hash"),
            "input_tokens": tin,
            "output_tokens": tout,
            "total_tokens": total,
            "cache_read_tokens": _num(totals.get("cache_read_tokens")),
            "reasoning_tokens": _num(totals.get("reasoning_tokens")),
            "cost_usd": _num(pick("cost_usd")),
            "llm_calls": pick("llm_calls"),
            "tool_calls": pick("tool_calls"),
            "subagent_calls": pick("subagent_calls"),
            "errors": pick("errors"),
            "ttft_s": _num(timing.get("time_to_first_llm_token_s")),
            "tools": [str(k) for k in by_tool],
            "skills_used": [str(s) for s in skills],
            "path": ie.get("path") or f"runs/{run_id}",
        }
        item["_ts"] = _epoch(item["started_at"])
        return item

    def _run_records(self) -> list[tuple[dict, str]]:
        """(item, texto de busca) de cada run em `runs/`, mais antigo -> mais recente não garantido (ordene depois)."""
        out: list[tuple[dict, str]] = []
        try:
            entries = [e for e in self.runs_dir.iterdir() if e.is_dir() and _NAME.match(e.name)]
        except OSError:
            return out
        index: dict[str, dict] | None = None
        for d in entries:
            path = d / "run.json"
            try:
                st = path.stat()
            except OSError:
                continue
            key = str(path)
            with self._lock:
                hit = self._items.get(key)
            if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
                out.append((hit[2], hit[3]))
                continue
            run = self._read(path, None)
            if not isinstance(run, dict):   # ilegível (corrompido ou sendo gravado): usa a linha do índice, se houver
                if index is None:
                    index = self._index_entries()
                if d.name not in index:
                    continue
                item = self._build_item(d.name, None, index[d.name])
                item["corrupt"] = True
            else:
                item = self._build_item(d.name, run, None)
            answer = ((run or {}).get("output") or {}).get("answer") if isinstance(run, dict) else None
            blob = " ".join([d.name, item["user_message"] or "", answer if isinstance(answer, str) else (item["answer_preview"] or ""),
                             item["label"] or ""]).lower()
            with self._lock:
                self._items[key] = (st.st_mtime_ns, st.st_size, item, blob)
            out.append((item, blob))
        return out

    @staticmethod
    def _public(item: dict) -> dict:
        return {k: v for k, v in item.items() if not k.startswith("_")}

    # ------------------------------------------------------------------------------------------ filtros
    def _filters(self, params: Mapping[str, str], now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.time()
        multi = lambda k: {x for x in str(params.get(k, "")).split(",") if x} or None  # noqa: E731
        return {
            "since": parse_time(params.get("since"), now), "until": parse_time(params.get("until"), now),
            "status": multi("status"), "model": multi("model"), "session": multi("session"), "origin": multi("origin"),
            "q": (params.get("q") or "").strip().lower() or None, "has_errors": _flag(params.get("has_errors", "")),
            "tool": (params.get("tool") or "").strip() or None, "min_duration": _float_param(params, "min_duration"),
        }

    @staticmethod
    def _match(item: dict, blob: str, f: Mapping[str, Any], skip: str | None = None) -> bool:
        ts = item.get("_ts")
        if f["since"] is not None and (ts is None or ts < f["since"]):
            return False
        if f["until"] is not None and (ts is None or ts > f["until"]):
            return False
        for key in ("status", "model", "session", "origin"):
            if key != skip and f[key] is not None:
                field = "session_id" if key == "session" else key
                if str(item.get(field)) not in f[key]:
                    return False
        if f["q"] and f["q"] not in blob:
            return False
        if f["has_errors"] and not ((item.get("errors") or 0) > 0 or item.get("status") == "error"):
            return False
        if f["tool"] and f["tool"] not in item.get("tools", []):
            return False
        if f["min_duration"] is not None and (item.get("duration_s") is None or item["duration_s"] < f["min_duration"]):
            return False
        return True

    def _filtered(self, params: Mapping[str, str], skip: str | None = None, now: float | None = None) -> list[dict]:
        f = self._filters(params, now)
        return [it for it, blob in self._run_records() if self._match(it, blob, f, skip)]

    # ---------------------------------------------------------------------------------------------- meta
    def meta(self) -> dict[str, Any]:
        recs = [it for it, _ in self._run_records()]
        stamps = sorted(it["_ts"] for it in recs if it.get("_ts") is not None)
        try:
            n_configs = len(list((self.data_dir / "configs").glob("*.json")))
        except OSError:
            n_configs = 0
        return {
            "data_dir": str(self.data_dir), "n_runs": len(recs), "n_sessions": len({it["session_id"] for it in recs if it.get("session_id")}),
            "n_configs": n_configs, "first_run_at": _iso(stamps[0]) if stamps else None, "last_run_at": _iso(stamps[-1]) if stamps else None,
            "models": sorted({it["model"] for it in recs if it.get("model")}), "origins": sorted({it["origin"] for it in recs if it.get("origin")}),
            "statuses": sorted({it["status"] for it in recs if it.get("status")}), "generated_at": _iso(time.time()),
        }

    # ---------------------------------------------------------------------------------------------- runs
    def runs(self, params: Mapping[str, str]) -> dict[str, Any]:
        sort = params.get("sort") or "started_at"
        if sort not in RUN_SORTS:
            raise _bad(f"sort inválido: {sort} (use {', '.join(RUN_SORTS)})")
        order = "asc" if params.get("order") == "asc" else "desc"
        limit, offset = _int_param(params, "limit", 50, 1, 500), _int_param(params, "offset", 0, 0, 10**9)
        now = time.time()
        f = self._filters(params, now)
        records = self._run_records()
        rows = [it for it, blob in records if self._match(it, blob, f)]
        rows = _sort_key_none_last(rows, "_ts" if sort == "started_at" else sort, order)
        facets: dict[str, dict[str, int]] = {}
        for name in ("status", "model", "origin", "session"):
            counts: dict[str, int] = {}
            for it, blob in records:
                if self._match(it, blob, f, skip=name):
                    v = it.get("session_id" if name == "session" else name)
                    if v not in (None, ""):
                        counts[str(v)] = counts.get(str(v), 0) + 1
            facets[name] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:300])
        page = [self._public(it) for it in rows[offset: offset + limit]]
        return {"total": len(rows), "limit": limit, "offset": offset, "items": page, "facets": facets}

    def run(self, run_id: str) -> Any:
        d = self._run_dir(run_id)
        run = self._read(d / "run.json", _MISSING)
        if run is _MISSING:
            raise _nf(f"run.json de {run_id} ausente ou ilegível")
        return run

    def run_file(self, run_id: str, name: str) -> Any:
        if not _FILE.match(name or "") or ".." in name:
            raise _bad("nome de arquivo inválido")
        path = self._run_dir(run_id) / name
        obj = self._read(path, _MISSING)
        if obj is _MISSING:
            raise _nf(f"arquivo não encontrado ou ilegível: {name}")
        return obj

    # ---------------------------------------------------------------------------------------------- trace
    def _calls_index(self, run_id: str) -> tuple[dict, dict, dict]:
        llm_doc = self._run_file(run_id, "llm_calls.json", {})
        tool_doc = self._run_file(run_id, "tool_calls.json", {})
        llm = {c.get("llm_call_id"): c for c in (llm_doc.get("calls") or []) if isinstance(c, dict)} if isinstance(llm_doc, dict) else {}
        tools = {}
        if isinstance(tool_doc, dict):
            for c in tool_doc.get("calls") or []:
                if isinstance(c, dict):
                    tools[c.get("tool_call_id")] = c
                    tools.setdefault("span:" + str(c.get("span_id")), c)
        return llm, tools, (llm_doc if isinstance(llm_doc, dict) else {})

    @staticmethod
    def _llm_brief(c: dict) -> dict[str, Any]:
        model = c.get("model") if isinstance(c.get("model"), dict) else {}
        usage = c.get("usage") if isinstance(c.get("usage"), dict) else {}
        resp = c.get("response") if isinstance(c.get("response"), dict) else {}
        req = c.get("request") if isinstance(c.get("request"), dict) else {}
        return {
            "model": model.get("returned") or model.get("requested"), "purpose": c.get("purpose"),
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"), "cost_usd": c.get("cost_usd"),
            "latency_s": c.get("latency_s"), "ttft_s": c.get("ttft_s"), "finish_reason": resp.get("finish_reason"),
            "n_messages": req.get("n_messages"), "tool_names": c.get("tool_names") or [],
            "requested_tools": [tc.get("name") for tc in (resp.get("tool_calls") or []) if isinstance(tc, dict)],
        }

    @staticmethod
    def _tool_brief(c: dict) -> dict[str, Any]:
        inp = c.get("input")
        out = c.get("output") if isinstance(c.get("output"), dict) else {}
        brief = {
            "name": c.get("name"), "kind": c.get("kind"), "status": c.get("status"), "duration_s": c.get("duration_s"),
            "input_preview": _preview(c.get("input_str") or (json.dumps(inp, ensure_ascii=False, default=str) if inp is not None else "")),
            "output_preview": _preview(out.get("text") if out.get("text") is not None else out.get("content")),
            "tool_call_id": c.get("tool_call_id"),
        }
        if c.get("name") == "task" and isinstance(inp, dict) and inp.get("subagent_type"):
            brief["subagent_type"] = inp["subagent_type"]
        return brief

    def trace(self, run_id: str) -> dict[str, Any]:
        run = self.run(run_id)
        doc = self._run_file(run_id, "spans.json", {})
        llm, tools, _ = self._calls_index(run_id)
        spans_in = doc.get("spans") if isinstance(doc, dict) and isinstance(doc.get("spans"), list) else []
        run_dur = _num(run.get("duration_s")) if isinstance(run, dict) else None
        out = []
        for s in spans_in:
            if not isinstance(s, dict):
                continue
            span = dict(s)
            ref = s.get("ref") if isinstance(s.get("ref"), dict) else {}
            brief: dict[str, Any] = {}
            if s.get("type") == "llm":
                c = llm.get(ref.get("llm_call_id")) or llm.get(s.get("span_id"))
                brief = self._llm_brief(c) if c else {}
            elif s.get("type") == "tool":
                c = tools.get(ref.get("tool_call_id")) or tools.get("span:" + str(s.get("span_id")))
                brief = self._tool_brief(c) if c else {}
            off = _num(s.get("start_offset_s")) or 0.0
            dur = _num(s.get("duration_s"))
            if dur is None:   # span sem fim (run em andamento/interrompido): vai até o fim do run, se conhecido
                dur = max(0.0, run_dur - off) if run_dur is not None else 0.0
            span["brief"], span["offset_s"], span["duration_s"] = brief, float(off), float(dur)
            out.append(span)
        return {"run": run, "root_ids": doc.get("root_ids", []) if isinstance(doc, dict) else [], "spans": out}

    def span(self, run_id: str, span_id: str) -> dict[str, Any]:
        _safe_name(span_id, "span_id")
        self._run_dir(run_id)
        doc = self._run_file(run_id, "spans.json", {})
        spans = [s for s in (doc.get("spans") or []) if isinstance(s, dict)] if isinstance(doc, dict) else []
        by_id = {s.get("span_id"): s for s in spans}
        span = by_id.get(span_id)
        if span is None:
            raise _nf(f"span não encontrado: {span_id}")
        chain, cur, seen = [], span, set()
        while cur is not None and cur.get("span_id") not in seen:
            seen.add(cur.get("span_id"))
            chain.append(cur)
            cur = by_id.get(cur.get("parent_id"))
        result: dict[str, Any] = {"span": span, "parent_chain": chain}
        ref = span.get("ref") if isinstance(span.get("ref"), dict) else {}
        llm, tools, llm_doc = self._calls_index(run_id)
        call = llm.get(ref.get("llm_call_id")) if ref.get("llm_call_id") else (llm.get(span_id) if span.get("type") == "llm" else None)
        if call is not None:
            call = dict(call)
            pool = llm_doc.get("tool_schemas") if isinstance(llm_doc.get("tool_schemas"), dict) else {}
            call["tool_schemas"] = pool.get(call.get("tools_hash")) or []
            result["llm_call"] = call
        tcall = tools.get(ref.get("tool_call_id")) if ref.get("tool_call_id") else tools.get("span:" + span_id)
        if tcall is not None:
            result["tool_call"] = tcall
            if tcall.get("name") == "task" or tcall.get("kind") == "subagent":
                sub = self._run_file(run_id, "subagents.json", {})
                for d in (sub.get("delegations") or []) if isinstance(sub, dict) else []:
                    if isinstance(d, dict) and d.get("id") == tcall.get("tool_call_id"):
                        result["delegation"] = d
                        break
        return result

    # ----------------------------------------------------------------------------------------- sessões
    def _session_groups(self, params: Mapping[str, str]) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = {}
        for it in self._filtered(params):
            if it.get("session_id"):
                groups.setdefault(str(it["session_id"]), []).append(it)
        for runs in groups.values():
            runs.sort(key=lambda r: ((r.get("turn") if isinstance(r.get("turn"), (int, float)) else 10**9), r.get("_ts") or 0))
        return groups

    @staticmethod
    def _session_summary(sid: str, runs: list[dict]) -> dict[str, Any]:
        stamps = [r["_ts"] for r in runs if r.get("_ts") is not None]
        statuses: dict[str, int] = {}
        for r in runs:
            statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        costs = [r["cost_usd"] for r in runs if r.get("cost_usd") is not None]
        by_time = sorted(runs, key=lambda r: r.get("_ts") or 0)
        durs = [r["duration_s"] for r in runs if r.get("duration_s") is not None]
        return {
            "session_id": sid, "started_at": _iso(min(stamps)) if stamps else None, "last_run_at": _iso(max(stamps)) if stamps else None,
            "n_runs": len(runs), "models": sorted({r["model"] for r in runs if r.get("model")}),
            "origins": sorted({r["origin"] for r in runs if r.get("origin")}),
            "totals": {"llm_calls": sum(r.get("llm_calls") or 0 for r in runs), "tool_calls": sum(r.get("tool_calls") or 0 for r in runs),
                       "input_tokens": sum(r.get("input_tokens") or 0 for r in runs), "output_tokens": sum(r.get("output_tokens") or 0 for r in runs),
                       "cost_usd": round(sum(costs), 6) if costs else None},
            "first_message": by_time[0].get("user_message") if by_time else None,
            "n_errors": sum(1 for r in runs if r["status"] == "error"), "duration_s": round(sum(durs), 4) if durs else None,
            "statuses": statuses,
        }

    def sessions(self, params: Mapping[str, str]) -> dict[str, Any]:
        items = [self._session_summary(sid, runs) for sid, runs in self._session_groups(params).items()]
        items.sort(key=lambda s: s["last_run_at"] or "", reverse=True)
        return {"items": items}

    def session(self, session_id: str) -> dict[str, Any]:
        _safe_name(session_id, "session_id")
        runs = self._session_groups({}).get(session_id)
        if not runs:
            raise _nf(f"sessão não encontrada: {session_id}")
        messages = []
        for it in runs:
            run = self._read(self.runs_dir / it["run_id"] / "run.json", {})
            run = run if isinstance(run, dict) else {}
            user = (run.get("input") or {}).get("user_message") if isinstance(run.get("input"), dict) else None
            answer = (run.get("output") or {}).get("answer") if isinstance(run.get("output"), dict) else None
            user = user if isinstance(user, str) else it.get("user_message")
            if user:
                messages.append({"role": "user", "content": user, "run_id": it["run_id"], "at": it.get("started_at")})
            if isinstance(answer, str) and answer:
                messages.append({"role": "assistant", "content": answer, "run_id": it["run_id"], "at": it.get("ended_at") or it.get("started_at")})
        return {"session": self._session_summary(session_id, runs), "runs": [self._public(r) for r in runs], "messages": messages}

    # ----------------------------------------------------------------------------------------- configs
    def _config_files(self) -> dict[str, Path]:
        d = self.data_dir / "configs"
        try:
            return {p.stem: p for p in sorted(d.glob("*.json")) if _NAME.match(p.stem)}
        except OSError:
            return {}

    def _usage_by_config(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for it, _ in self._run_records():
            if it.get("config_hash"):
                out.setdefault(str(it["config_hash"]), []).append(it)
        return out

    @staticmethod
    def _config_meta(h: str, path: Path, cfg: Any, runs: list[dict]) -> dict[str, Any]:
        cfg = cfg if isinstance(cfg, dict) else {}
        prompts = cfg.get("prompts") if isinstance(cfg.get("prompts"), dict) else {}
        model = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
        subs = cfg.get("subagents") if isinstance(cfg.get("subagents"), dict) else {}
        stamps = sorted(r["_ts"] for r in runs if r.get("_ts") is not None)
        try:
            created = _iso(path.stat().st_mtime)
        except OSError:
            created = None
        sp = prompts.get("system_prompt")
        return {
            "hash": h, "model": model.get("spec"), "provider": model.get("provider"), "created_at": created,
            "system_prompt_chars": len(sp) if isinstance(sp, str) else 0,
            "n_rules": len(prompts.get("rules") or []) if isinstance(prompts.get("rules"), list) else 0,
            "n_skills": len(prompts.get("skills") or []) if isinstance(prompts.get("skills"), list) else 0,
            "n_subagents": sum(1 for s in subs.values() if isinstance(s, dict) and s.get("enabled", True)),
            "runs": len(runs), "first_used_at": _iso(stamps[0]) if stamps else None, "last_used_at": _iso(stamps[-1]) if stamps else None,
        }

    def configs(self) -> dict[str, Any]:
        usage = self._usage_by_config()
        items = []
        for h, path in self._config_files().items():
            cfg = self._read(path, None)
            items.append(self._config_meta(h, path, cfg, usage.get(h, [])))
        items.sort(key=lambda c: c["created_at"] or "", reverse=True)
        return {"items": items}

    def config(self, h: str) -> dict[str, Any]:
        _safe_name(h, "hash")
        path = self._config_files().get(h)
        if path is None:
            raise _nf(f"config não encontrada: {h}")
        cfg = self._read(path, _MISSING)
        if not isinstance(cfg, dict):
            raise _nf(f"config ilegível: {h}")
        runs = sorted(self._usage_by_config().get(h, []), key=lambda r: r.get("_ts") or 0, reverse=True)
        meta = self._config_meta(h, path, cfg, runs)
        return {**cfg, "hash": h, "created_at": meta["created_at"], "first_used_at": meta["first_used_at"],
                "last_used_at": meta["last_used_at"], "runs": [self._public(r) for r in runs]}

    @staticmethod
    def _config_sections(cfg: dict) -> dict[str, str]:
        prompts = cfg.get("prompts") if isinstance(cfg.get("prompts"), dict) else {}
        dump = lambda o: json.dumps(o, ensure_ascii=False, indent=2, sort_keys=True, default=str)  # noqa: E731
        sec: dict[str, str] = {}
        sec["model"] = dump(cfg.get("model") or {})
        sec["system_prompt"] = str(prompts.get("system_prompt") or "")
        sec["summary_prompt"] = str(prompts.get("summary_prompt") or "")
        sec["harness_profile"] = dump(prompts.get("harness_profile") or {})
        sec["memory_files"] = "\n".join(str(x) for x in prompts.get("memory_files") or [])
        for r in prompts.get("rules") or []:
            if isinstance(r, dict):
                sec[f"regra: {r.get('path', '?')}"] = str(r.get("text") or "")
        for s in prompts.get("skills") or []:
            if isinstance(s, dict):
                sec[f"skill: {s.get('path', '?')}"] = str(s.get("text") or "")
        subs = cfg.get("subagents") if isinstance(cfg.get("subagents"), dict) else {}
        for name in sorted(subs):
            s = subs[name] if isinstance(subs[name], dict) else {}
            head = {k: v for k, v in s.items() if k != "system_prompt"}
            sec[f"subagent: {name}"] = dump(head) + "\n\n--- system_prompt ---\n" + str(s.get("system_prompt") or "")
        for key in ("toolkit", "dynamic_subagents", "limits", "streaming"):
            sec[key] = dump(cfg.get(key) or {})
        sec["skills_dirs"] = "\n".join(str(x) for x in prompts.get("skills_dirs") or [])
        sec["permissions"] = dump(prompts.get("permissions") or [])
        return sec

    def config_diff(self, a: str, b: str) -> dict[str, Any]:
        if not a or not b:
            raise _bad("informe a e b (hashes das configs)")
        docs = []
        for h in (a, b):
            _safe_name(h, "hash")
            path = self._config_files().get(h)
            cfg = self._read(path, None) if path else None
            if not isinstance(cfg, dict):
                raise _nf(f"config não encontrada: {h}")
            docs.append(self._config_sections(cfg))
        sa, sb = docs
        names = list(sa) + [n for n in sb if n not in sa]
        sections = []
        for name in names:
            ta, tb = sa.get(name), sb.get(name)
            la = ta.splitlines() if ta is not None else []
            lb = tb.splitlines() if tb is not None else []
            if ta is None:
                status, lines = "added", [{"op": "+", "text": x} for x in lb]
            elif tb is None:
                status, lines = "removed", [{"op": "-", "text": x} for x in la]
            elif ta == tb:
                status, lines = "same", [{"op": " ", "text": x} for x in la]
            else:
                status, lines = "changed", []
                for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
                    if tag == "equal":
                        lines += [{"op": " ", "text": x} for x in la[i1:i2]]
                    else:
                        lines += [{"op": "-", "text": x} for x in la[i1:i2]] + [{"op": "+", "text": x} for x in lb[j1:j2]]
            sections.append({"name": name, "status": status, "lines": lines})
        return {"a": a, "b": b, "sections": sections}

    # ---------------------------------------------------------------------------------------- chamadas
    def _call_runs(self, params: Mapping[str, str]) -> list[dict]:
        """Runs candidatos a conter chamadas do período (filtros de sessão/origem/run; o tempo é checado por chamada)."""
        f = self._filters({k: v for k, v in params.items() if k in ("session", "origin")})
        only = params.get("run")
        since, until = parse_time(params.get("since")), parse_time(params.get("until"))
        runs = []
        for it, _ in self._run_records():
            if only and it["run_id"] != only:
                continue
            if not self._match(it, "", f):
                continue
            ts = it.get("_ts")
            end = ts + (it.get("duration_s") or 0) if ts is not None else None
            if since is not None and end is not None and end < since:
                continue
            if until is not None and ts is not None and ts > until:
                continue
            runs.append(it)
        return runs

    def _derived_for(self, kind: str, run_id: str, fname: str, build: Callable[[dict, str], list[dict]]) -> list[dict]:
        path = self.runs_dir / run_id / fname
        try:
            st = path.stat()
        except OSError:
            return []
        key = (kind, str(path))
        with self._lock:
            hit = self._derived.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        doc = self._read(path, None)
        rows = build(doc, run_id) if isinstance(doc, dict) else []
        with self._lock:
            self._derived[key] = (st.st_mtime_ns, st.st_size, rows)
        return rows

    @staticmethod
    def _llm_rows(doc: dict, run_id: str) -> list[dict]:
        rows = []
        for c in doc.get("calls") or []:
            if not isinstance(c, dict):
                continue
            usage = c.get("usage") if isinstance(c.get("usage"), dict) else {}
            model = c.get("model") if isinstance(c.get("model"), dict) else {}
            resp = c.get("response") if isinstance(c.get("response"), dict) else {}
            req = c.get("request") if isinstance(c.get("request"), dict) else {}
            msgs = [m for m in (req.get("messages") or []) if isinstance(m, dict)]
            last_in = next((m for m in reversed(msgs) if m.get("type") != "system"), msgs[-1] if msgs else {})
            requested = [tc.get("name") for tc in (resp.get("tool_calls") or []) if isinstance(tc, dict)]
            text_out = resp.get("text") or ""
            rows.append({
                "llm_call_id": c.get("llm_call_id"), "span_id": c.get("span_id"), "run_id": run_id, "started_at": c.get("started_at"),
                "agent": c.get("agent"), "purpose": c.get("purpose"), "model": model.get("returned") or model.get("requested"),
                "status": c.get("status"), "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                "cache_read_tokens": usage.get("cache_read_tokens"), "cost_usd": c.get("cost_usd"), "latency_s": c.get("latency_s"),
                "ttft_s": c.get("ttft_s"), "finish_reason": resp.get("finish_reason"), "requested_tools": requested,
                "preview_in": _preview(last_in.get("content")), "preview_out": _preview(text_out) or (("→ " + ", ".join(requested)) if requested else ""),
                "_ts": _epoch(c.get("started_at")),
            })
        return rows

    @staticmethod
    def _tool_rows(doc: dict, run_id: str) -> list[dict]:
        rows = []
        for c in doc.get("calls") or []:
            if not isinstance(c, dict):
                continue
            out = c.get("output") if isinstance(c.get("output"), dict) else {}
            inp = c.get("input")
            rows.append({
                "tool_call_id": c.get("tool_call_id"), "span_id": c.get("span_id"), "run_id": run_id, "started_at": c.get("started_at"),
                "name": c.get("name"), "kind": c.get("kind"), "agent": c.get("agent"), "status": c.get("status"),
                "duration_s": c.get("duration_s"),
                "input_preview": _preview(c.get("input_str") or (json.dumps(inp, ensure_ascii=False, default=str) if inp is not None else "")),
                "output_preview": _preview(out.get("text") if out.get("text") is not None else out.get("content")),
                "output_chars": c.get("output_chars"), "_ts": _epoch(c.get("started_at")),
            })
        return rows

    def _call_search(self, kind: str, run_id: str, q: str) -> set[str]:
        """Ids das chamadas do run cujo conteúdo completo contém `q` (requisição/resposta/args/saída)."""
        fname = "llm_calls.json" if kind == "llm" else "tool_calls.json"
        doc = self._read(self.runs_dir / run_id / fname, None)
        hits: set[str] = set()
        for c in (doc.get("calls") or []) if isinstance(doc, dict) else []:
            if not isinstance(c, dict):
                continue
            try:
                blob = json.dumps(c.get("request") if kind == "llm" else c.get("input"), ensure_ascii=False, default=str)
                blob += json.dumps(c.get("response") if kind == "llm" else c.get("output"), ensure_ascii=False, default=str)
                if kind == "tool":
                    blob += str(c.get("name") or "") + str(c.get("input_str") or "")
            except (TypeError, ValueError):
                continue
            if q in blob.lower():
                hits.add(str(c.get("llm_call_id" if kind == "llm" else "tool_call_id")))
        return hits

    def _calls(self, kind: str, params: Mapping[str, str]) -> dict[str, Any]:
        llm = kind == "llm"
        sorts = LLM_SORTS if llm else TOOL_SORTS
        sort = params.get("sort") or "started_at"
        if sort not in sorts:
            raise _bad(f"sort inválido: {sort} (use {', '.join(sorts)})")
        order = "asc" if params.get("order") == "asc" else "desc"
        limit, offset = _int_param(params, "limit", 50, 1, 500), _int_param(params, "offset", 0, 0, 10**9)
        since, until = parse_time(params.get("since")), parse_time(params.get("until"))
        q = (params.get("q") or "").strip().lower()
        minimum = _float_param(params, "min_latency" if llm else "min_duration")
        eq = {k: set(str(params[k]).split(",")) for k in (("agent", "purpose", "model", "status") if llm else ("name", "kind", "agent", "status"))
              if params.get(k)}
        field_min = "latency_s" if llm else "duration_s"
        rows: list[dict] = []
        for run in self._call_runs(params):
            fname = "llm_calls.json" if llm else "tool_calls.json"
            derived = self._derived_for(kind, run["run_id"], fname, self._llm_rows if llm else self._tool_rows)
            cand = []
            for r in derived:
                if since is not None and (r["_ts"] is None or r["_ts"] < since):
                    continue
                if until is not None and (r["_ts"] is None or r["_ts"] > until):
                    continue
                if any(str(r.get(k)) not in v for k, v in eq.items()):
                    continue
                if minimum is not None and (r.get(field_min) is None or r[field_min] < minimum):
                    continue
                cand.append(r)
            if q and cand:
                ids = self._call_search(kind, run["run_id"], q)
                cand = [r for r in cand if str(r["llm_call_id" if llm else "tool_call_id"]) in ids]
            rows.extend(cand)
        if sort == "started_at":
            rows = _sort_key_none_last([dict(r, _k=r["_ts"]) for r in rows], "_k", order)
        else:
            rows = _sort_key_none_last(rows, sort, order)
        page = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows[offset: offset + limit]]
        return {"total": len(rows), "limit": limit, "offset": offset, "items": page}

    def llm_calls(self, params: Mapping[str, str]) -> dict[str, Any]:
        return self._calls("llm", params)

    def tool_calls(self, params: Mapping[str, str]) -> dict[str, Any]:
        return self._calls("tool", params)

    # ------------------------------------------------------------------------------------------- stats
    @staticmethod
    def _nice_edges(values: list[float], ladder: list[float]) -> dict[str, list]:
        if not values:
            return {"edges": [], "counts": []}
        lo, hi = min(values), max(values)
        start = max([e for e in ladder if e <= lo] or [0])
        top = ladder[-1]
        while top < hi:
            top *= 2
            ladder = ladder + [top]
        end = next(e for e in ladder if e > hi)
        edges = [e for e in ladder if start <= e <= end]
        counts = [0] * (len(edges) - 1)
        for v in values:
            for i in range(len(edges) - 1):
                if edges[i] <= v < edges[i + 1]:
                    counts[i] += 1
                    break
        return {"edges": edges, "counts": counts}

    @staticmethod
    def _kpis(items: list[dict]) -> dict[str, Any]:
        n = len(items)
        s = lambda k: sum(i.get(k) or 0 for i in items)  # noqa: E731
        costs = [i["cost_usd"] for i in items if i.get("cost_usd") is not None]
        durs = [i["duration_s"] for i in items if i.get("duration_s") is not None]
        ttfts = [i["ttft_s"] for i in items if i.get("ttft_s") is not None]
        errors = sum(1 for i in items if i.get("status") == "error")
        tin, cache = s("input_tokens"), s("cache_read_tokens")
        lat = {"avg": _r(_avg(durs)), "p50": _r(_pct(durs, 50)), "p95": _r(_pct(durs, 95)), "p99": _r(_pct(durs, 99))}
        kp = {
            "runs": n, "errors": errors, "error_rate": _r(errors / n, 6) if n else 0.0,
            "cancelled": sum(1 for i in items if i.get("status") == "cancelled"),
            "input_tokens": tin, "output_tokens": s("output_tokens"), "total_tokens": s("total_tokens"), "cache_read_tokens": cache,
            "cache_hit_rate": _r(cache / tin, 6) if tin else 0.0, "reasoning_tokens": s("reasoning_tokens"),
            "cost_usd": round(sum(costs), 6) if costs else None,
            "avg_ttft_s": _r(_avg(ttfts)), "ttft_avg_s": _r(_avg(ttfts)),
            "llm_calls": s("llm_calls"), "tool_calls": s("tool_calls"), "subagent_calls": s("subagent_calls"),
            "avg_tokens_per_run": _r(s("total_tokens") / n, 2) if n else 0.0,
        }
        for k, v in lat.items():
            kp[f"latency_{k}_s"] = v      # nome usado pelo dashboard
            kp[f"{k}_latency_s"] = v      # alias
        return kp

    def stats(self, params: Mapping[str, str]) -> dict[str, Any]:
        """Agregados do dashboard (`GET /api/stats`). Filtros comuns + `bucket` (auto|hour|day). Campos devolvidos:

        range         {from, to, bucket}  ISO; `from` = since (ou o 1º run), `to` = until (ou agora); bucket = hour|day (UTC)
        kpis          {runs, errors, error_rate (0..1), cancelled, input_tokens, output_tokens, total_tokens, cache_read_tokens,
                       cache_hit_rate (cache_read/input), reasoning_tokens, cost_usd (None se nenhum custo), latency_avg_s,
                       latency_p50_s, latency_p95_s, latency_p99_s (+ aliases avg_/p50_/p95_/p99_latency_s), avg_ttft_s (= ttft_avg_s),
                       llm_calls, tool_calls, subagent_calls, avg_tokens_per_run}      (None onde não há dado)
        prev_kpis     kpis do período anterior de mesma duração; só existe quando há `since`; senão null
        series[]      um por bucket (vazios com zeros): {t (ISO do início do bucket), runs, errors, ok (completed), cancelled,
                       input_tokens, output_tokens, total_tokens, cost_usd (0 em bucket vazio; None se nenhum run do filtro tem custo),
                       p50_s, p95_s (+ latency_p50_s, latency_p95_s; None em bucket vazio), avg_ttft_s (None em vazio), llm_calls, tool_calls}
        status_counts {status: n}
        by_model[]    {model, runs, errors, input_tokens, output_tokens, total_tokens, cost_usd, avg_latency_s (= latency_avg_s),
                       latency_p50_s, latency_p95_s, llm_calls}
        by_tool[]     {name, calls, errors, avg_s, p95_s, max_s, total_s} (alias avg_duration_s = avg_s), por calls desc
        by_agent[]    {agent, is_main, runs, llm_calls, tool_calls, input_tokens, output_tokens, total_tokens, cost_usd, llm_time_s}
        latency_hist  {edges[], counts[]}  duration_s dos runs; len(edges) = len(counts) + 1; bordas "bonitas" (0.5, 1, 2, 5, 10...)
        tokens_hist   {edges[], counts[]}  total_tokens por run
        slowest_runs[] top 8 por duration_s: {run_id, user_message, duration_s, total_tokens, status, started_at, model, cost_usd}
        recent_errors[] top 10 (mais recentes) de errors.json: {run_id, at, where, name, type, message, span_id}
        """
        now = time.time()
        items = self._filtered(params, now=now)
        f = self._filters(params, now)
        bucket_req = (params.get("bucket") or "auto").lower()
        if bucket_req not in ("auto", "hour", "day"):
            raise _bad("bucket inválido (auto|hour|day)")
        stamps = [i["_ts"] for i in items if i.get("_ts") is not None]
        t_from = f["since"] if f["since"] is not None else (min(stamps) if stamps else now)
        t_to = f["until"] if f["until"] is not None else now
        t_to = max(t_to, t_from)
        span = t_to - t_from
        bucket = bucket_req if bucket_req != "auto" else ("hour" if span <= 4 * 86400 else "day")
        step = 3600 if bucket == "hour" else 86400
        if span / step > 800:
            bucket, step = "day", 86400
        first_b = t_from - (t_from % step)
        last_b = t_to - (t_to % step)
        if stamps:
            last_b = max(last_b, max(stamps) - (max(stamps) % step)) if f["until"] is None else last_b
        n_buckets = int((last_b - first_b) // step) + 1
        buckets: list[list[dict]] = [[] for _ in range(n_buckets)]
        for it in items:
            if it.get("_ts") is None:
                continue
            k = int((it["_ts"] - (it["_ts"] % step) - first_b) // step)
            if 0 <= k < n_buckets:
                buckets[k].append(it)
        any_cost = any(i.get("cost_usd") is not None for i in items)
        series = []
        for k, rs in enumerate(buckets):
            durs = [r["duration_s"] for r in rs if r.get("duration_s") is not None]
            ttfts = [r["ttft_s"] for r in rs if r.get("ttft_s") is not None]
            p50, p95 = _r(_pct(durs, 50)), _r(_pct(durs, 95))
            series.append({
                "t": _iso(first_b + k * step), "runs": len(rs), "errors": sum(1 for r in rs if r["status"] == "error"),
                "ok": sum(1 for r in rs if r["status"] == "completed"), "cancelled": sum(1 for r in rs if r["status"] == "cancelled"),
                "input_tokens": sum(r.get("input_tokens") or 0 for r in rs), "output_tokens": sum(r.get("output_tokens") or 0 for r in rs),
                "total_tokens": sum(r.get("total_tokens") or 0 for r in rs),
                "cost_usd": (round(sum(r.get("cost_usd") or 0 for r in rs), 6) if any_cost else None),
                "p50_s": p50, "p95_s": p95, "latency_p50_s": p50, "latency_p95_s": p95, "avg_ttft_s": _r(_avg(ttfts)),
                "llm_calls": sum(r.get("llm_calls") or 0 for r in rs), "tool_calls": sum(r.get("tool_calls") or 0 for r in rs),
            })
        prev = None
        if f["since"] is not None:
            width = t_to - f["since"]
            prev_items = [it for it, blob in self._run_records()
                          if self._match(it, blob, {**f, "since": None, "until": None})
                          and it.get("_ts") is not None and f["since"] - width <= it["_ts"] < f["since"]]
            prev = self._kpis(prev_items)

        status_counts: dict[str, int] = {}
        for it in items:
            status_counts[it["status"]] = status_counts.get(it["status"], 0) + 1

        by_model = []
        groups: dict[str, list[dict]] = {}
        for it in items:
            groups.setdefault(it.get("model") or "(desconhecido)", []).append(it)
        for model, rs in groups.items():
            durs = [r["duration_s"] for r in rs if r.get("duration_s") is not None]
            costs = [r["cost_usd"] for r in rs if r.get("cost_usd") is not None]
            by_model.append({
                "model": model, "runs": len(rs), "errors": sum(1 for r in rs if r["status"] == "error"),
                "input_tokens": sum(r.get("input_tokens") or 0 for r in rs), "output_tokens": sum(r.get("output_tokens") or 0 for r in rs),
                "total_tokens": sum(r.get("total_tokens") or 0 for r in rs), "cost_usd": round(sum(costs), 6) if costs else None,
                "avg_latency_s": _r(_avg(durs)), "latency_avg_s": _r(_avg(durs)), "latency_p50_s": _r(_pct(durs, 50)),
                "latency_p95_s": _r(_pct(durs, 95)), "llm_calls": sum(r.get("llm_calls") or 0 for r in rs),
            })
        by_model.sort(key=lambda m: -m["runs"])

        # tools e agentes: do run.json (rápido) e, com poucos runs, os tempos individuais do tool_calls.json (p95)
        tool_acc: dict[str, dict[str, Any]] = {}
        agent_acc: dict[str, dict[str, Any]] = {}
        for it in items:
            run = self._read(self.runs_dir / it["run_id"] / "run.json", {})
            run = run if isinstance(run, dict) else {}
            tc_rows = None
            if len(items) <= 400:
                doc = self._read(self.runs_dir / it["run_id"] / "tool_calls.json", None)
                if isinstance(doc, dict):
                    tc_rows = [c for c in doc.get("calls") or [] if isinstance(c, dict)]
            if tc_rows is not None:
                for c in tc_rows:
                    a = tool_acc.setdefault(str(c.get("name")), {"calls": 0, "errors": 0, "durs": [], "total": 0.0, "max": 0.0})
                    a["calls"] += 1
                    a["errors"] += 1 if c.get("status") == "error" or c.get("error") else 0
                    d = _num(c.get("duration_s"))
                    if d is not None:
                        a["durs"].append(d)
                        a["total"] += d
                        a["max"] = max(a["max"], d)
            else:
                for name, t in (run.get("by_tool") or {}).items():
                    if not isinstance(t, dict):
                        continue
                    a = tool_acc.setdefault(str(name), {"calls": 0, "errors": 0, "durs": [], "total": 0.0, "max": 0.0})
                    a["calls"] += int(t.get("calls") or 0)
                    a["errors"] += int(t.get("errors") or 0)
                    a["total"] += float(t.get("total_s") or 0)
                    a["max"] = max(a["max"], float(t.get("max_s") or 0))
                    if t.get("avg_s") is not None and t.get("calls"):
                        a["durs"].append(float(t["avg_s"]))
            for name, ag in (run.get("by_agent") or {}).items():
                if not isinstance(ag, dict):
                    continue
                a = agent_acc.setdefault(str(name), {"runs": 0, "llm_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                     "cost": [], "llm_time_s": 0.0})
                a["runs"] += 1
                a["llm_calls"] += int(ag.get("llm_calls") or 0)
                a["tool_calls"] += int(ag.get("tool_calls") or 0)
                a["input_tokens"] += int(ag.get("input_tokens") or 0)
                a["output_tokens"] += int(ag.get("output_tokens") or 0)
                a["llm_time_s"] += float(ag.get("llm_time_s") or 0)
                if ag.get("cost_usd") is not None:
                    a["cost"].append(float(ag["cost_usd"]))
        by_tool = []
        for name, a in tool_acc.items():
            avg = a["total"] / a["calls"] if a["calls"] and a["total"] else (_avg(a["durs"]) if a["durs"] else None)
            avg = _r(avg)
            by_tool.append({"name": name, "calls": a["calls"], "errors": a["errors"], "avg_s": avg, "avg_duration_s": avg,
                            "p95_s": _r(_pct(a["durs"], 95)), "max_s": _r(a["max"]), "total_s": _r(a["total"])})
        by_tool.sort(key=lambda t: -t["calls"])
        by_agent = [{"agent": n, "is_main": n == "main", "runs": a["runs"], "llm_calls": a["llm_calls"], "tool_calls": a["tool_calls"],
                     "input_tokens": a["input_tokens"], "output_tokens": a["output_tokens"], "total_tokens": a["input_tokens"] + a["output_tokens"],
                     "cost_usd": round(sum(a["cost"]), 6) if a["cost"] else None, "llm_time_s": _r(a["llm_time_s"])}
                    for n, a in agent_acc.items()]
        by_agent.sort(key=lambda a: -a["total_tokens"])

        lat_ladder = [0, 0.5, 1, 2, 3, 5, 7.5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300, 600, 1200, 1800, 3600]
        tok_ladder = [0, 500, 1000, 2000, 3000, 5000, 7500, 10_000, 15_000, 20_000, 30_000, 50_000, 75_000, 100_000, 150_000, 200_000, 300_000,
                      500_000, 1_000_000, 2_000_000]
        durs_all = [i["duration_s"] for i in items if i.get("duration_s") is not None]
        toks_all = [i["total_tokens"] for i in items if i.get("total_tokens") is not None]
        slowest = sorted((i for i in items if i.get("duration_s") is not None), key=lambda i: -i["duration_s"])[:8]
        slowest_out = [{k: i.get(k) for k in ("run_id", "user_message", "duration_s", "total_tokens", "status", "started_at", "model", "cost_usd")}
                       for i in slowest]
        return {
            "range": {"from": _iso(t_from), "to": _iso(t_to), "bucket": bucket},
            "kpis": self._kpis(items), "prev_kpis": prev, "series": series, "status_counts": status_counts, "by_model": by_model,
            "by_tool": by_tool, "by_agent": by_agent, "latency_hist": self._nice_edges(durs_all, lat_ladder),
            "tokens_hist": self._nice_edges(toks_all, tok_ladder), "slowest_runs": slowest_out,
            "recent_errors": self._recent_errors(items),
        }

    def _recent_errors(self, items: list[dict], limit: int = 10) -> list[dict]:
        out: list[dict] = []
        bad = [i for i in items if (i.get("errors") or 0) > 0 or i.get("status") == "error"]
        bad.sort(key=lambda i: i.get("_ts") or 0, reverse=True)
        for it in bad[:40]:
            doc = self._read(self.runs_dir / it["run_id"] / "errors.json", None)
            seen: set[tuple] = set()
            rows = []
            for e in (doc.get("errors") or []) if isinstance(doc, dict) else []:
                if not isinstance(e, dict):
                    continue
                sig = (e.get("type"), e.get("message"))
                if sig in seen:
                    continue
                seen.add(sig)
                rows.append({"run_id": it["run_id"], "at": e.get("at") or it.get("started_at"), "where": e.get("where"), "name": e.get("name"),
                             "type": e.get("type"), "message": _preview(e.get("message"), 400), "span_id": e.get("span_id")})
            if not rows and it.get("status") == "error":
                run = self._read(self.runs_dir / it["run_id"] / "run.json", {})
                err = run.get("error") if isinstance(run, dict) and isinstance(run.get("error"), dict) else {}
                rows.append({"run_id": it["run_id"], "at": it.get("ended_at") or it.get("started_at"), "where": "run", "name": None,
                             "type": err.get("type"), "message": _preview(err.get("message"), 400), "span_id": None})
            out.extend(rows)
        out.sort(key=lambda e: e.get("at") or "", reverse=True)
        return out[:limit]

    # --------------------------------------------------------------------------------------- roteamento
    def dispatch(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        """`path` = parte da URL depois de `/api` (ex.: `/runs/abc/spans/def`). Levanta `ApiError`."""
        params = params or {}
        parts = [p for p in path.split("/") if p]
        if not parts:
            raise _nf("rota não encontrada")
        head, rest = parts[0], parts[1:]
        if head == "meta" and not rest:
            return self.meta()
        if head == "stats" and not rest:
            return self.stats(params)
        if head == "llm_calls" and not rest:
            return self.llm_calls(params)
        if head == "tool_calls" and not rest:
            return self.tool_calls(params)
        if head == "runs":
            if not rest:
                return self.runs(params)
            if len(rest) == 1:
                return self.run(rest[0])
            if len(rest) == 2 and rest[1] == "trace":
                return self.trace(rest[0])
            if len(rest) == 3 and rest[1] == "spans":
                return self.span(rest[0], rest[2])
            if len(rest) == 3 and rest[1] == "files":
                return self.run_file(rest[0], rest[2])
        if head == "sessions":
            if not rest:
                return self.sessions(params)
            if len(rest) == 1:
                return self.session(rest[0])
        if head == "configs":
            if not rest:
                return self.configs()
            if rest == ["diff"]:
                return self.config_diff(params.get("a", ""), params.get("b", ""))
            if len(rest) == 1:
                return self.config(rest[0])
        raise _nf(f"rota não encontrada: /api{path}")
