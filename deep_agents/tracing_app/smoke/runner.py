"""Smoke test do front-end do tracing_app SEM navegador.

    python -m deep_agents.tracing_app --smoke [--data-dir PASTA] [--route '#/runs/{run}?tab=events' ...]

Monta o JS de `src/js/*.js` (mesma ordem do build, um único script como no HTML final) dentro do QuickJS (`quickjs_rs`)
com um DOM falso (`dom_shim.js`) e uma ponte de `fetch('/api/...')` para o backend (o servidor real em outra thread, ou,
se ele ainda não existir, um stub que lê os JSONs direto). Cada rota roda numa página nova (contexto novo, como abrir a
URL direto) e é verificada: exceções não tratadas, `console.error`, `.errbox`, spinner preso, tela vazia, texto esperado.
Depois percorre interações simples (cliques, abas, selects, hover, tema, atualizar, intervalo, resize) e confere de novo.
Por fim navega por todas as rotas numa única página (pega vazamento de estado/timers entre views).

Stacks: o QuickJS embutido não propaga o nome do arquivo (todo frame vem como `eval_script:L:C`); como o build junta tudo
num bloco, o runner mantém a tabela de linhas de cada arquivo e reescreve os frames para `NN_nome.js:linha:coluna`.

Limitações do shim (ver também o cabeçalho de dom_shim.js): sem layout (getBoundingClientRect fixo 800x600, tudo
"visível"), sem CSS (nada de display:none por folha de estilo; só a classe `.hidden` é tratada pelo driver ao clicar),
NodeList/HTMLCollection são instantâneos (não "vivos"), sem Intl/locale (`toLocaleString` do QuickJS ignora pt-BR),
sem shadow DOM/Web Components/Canvas real, rejeições de Promise não tratadas só aparecem se vierem de listeners/timers
async (o resto vira "aviso: exceção em callback .then" ou, se a view fica parada, spinner preso).
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

_HERE = Path(__file__).resolve().parent
_APP = _HERE.parent
_JS_DIR = _APP / "src" / "js"

STATIC_ROUTES = ["#/", "#/runs", "#/sessions", "#/prompts", "#/data", "#/data/llm", "#/data/tools", "#/data/files"]
RUN_TABS = ["conversation", "events", "sources", "errors", "files", "config"]


# ---------------------------------------------------------------------------------------------------------------------
# bundle (shim + app + driver) e mapeamento de stacks
# ---------------------------------------------------------------------------------------------------------------------

class Bundle:
    """Um único script com a tabela de linhas de cada arquivo (para traduzir os frames dos stacks)."""

    def __init__(self, parts: list[tuple[str, str]]):
        self.parts = parts
        self.source = "\n".join(text for _, text in parts) + "\n;0"
        self.starts: list[tuple[int, str]] = []
        line = 1
        for name, text in parts:
            self.starts.append((line, name))
            line += text.count("\n") + 1
        self.total_lines = line

    def locate(self, line: int) -> tuple[str, int] | None:
        found = None
        for start, name in self.starts:
            if line >= start:
                found = (name, line - start + 1)
        return found if line < self.total_lines else None

    _FRAME = re.compile(r"eval_script:(\d+):(\d+)")

    def map_stack(self, stack: str, max_frames: int = 8, internal: bool = False) -> str:
        """Reescreve `eval_script:L:C` como `arquivo:linha:coluna`; esconde frames do harness se houver frames do app."""
        out: list[tuple[str, bool]] = []   # (linha, é_do_harness)
        for raw in str(stack or "").splitlines():
            m = self._FRAME.search(raw)
            if not m:
                if raw.strip():
                    out.append((raw.rstrip(), False))
                continue
            if "<eval>" in raw:
                continue
            loc = self.locate(int(m.group(1)))
            harness = False
            if loc:
                raw = self._FRAME.sub(f"{loc[0]}:{loc[1]}:{m.group(2)}", raw)
                harness = loc[0] in ("dom_shim.js", "driver.js")
            out.append((raw.rstrip(), harness))
        if not internal and any(not h and ln.strip().startswith("at ") for ln, h in out):
            out = [(ln, h) for ln, h in out if not h]
        lines = [ln for ln, _ in out]
        if len(lines) > max_frames:
            lines = lines[:max_frames] + [f"    ... (+{len(lines) - max_frames} frames)"]
        return "\n".join(lines)


def build_bundle(include_app: bool = True, extra: list[tuple[str, str]] | None = None) -> Bundle:
    parts: list[tuple[str, str]] = [("dom_shim.js", (_HERE / "dom_shim.js").read_text(encoding="utf-8"))]
    if include_app:
        for p in sorted(_JS_DIR.glob("*.js")):
            parts.append((p.name, p.read_text(encoding="utf-8")))
    parts.append(("driver.js", (_HERE / "driver.js").read_text(encoding="utf-8")))
    parts.extend(extra or [])
    return Bundle(parts)


# ---------------------------------------------------------------------------------------------------------------------
# ponte da API (fetch do JS -> backend)
# ---------------------------------------------------------------------------------------------------------------------

class ApiBridge:
    """`get(url)` -> (status, texto JSON). Respostas ficam em cache (os dados não mudam durante o smoke)."""

    label = "?"

    def __init__(self) -> None:
        self._cache: dict[str, tuple[int, str]] = {}
        self.calls: list[tuple[str, int]] = []

    def get(self, url: str) -> tuple[int, str]:
        if url not in self._cache:
            parts = urlsplit(url)
            if not parts.path.startswith("/api/"):
                self._cache[url] = (404, json.dumps({"error": f"fora da API: {parts.path}"}))
            else:
                try:
                    self._cache[url] = self._fetch(url)
                except Exception as e:   # falha do backend = 500 para a view tratar
                    self._cache[url] = (500, json.dumps({"error": f"{type(e).__name__}: {e}"}))
        res = self._cache[url]
        self.calls.append((url, res[0]))
        return res

    def get_json(self, url: str) -> Any:
        status, text = self.get(url)
        try:
            return json.loads(text) if status < 400 else None
        except ValueError:
            return None

    def _fetch(self, url: str) -> tuple[int, str]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class HttpBridge(ApiBridge):
    """Sobe o servidor REAL (`server.make_server`) numa thread em porta livre e fala com ele por HTTP."""

    def __init__(self, data_dir: Path):
        super().__init__()
        from deep_agents.tracing_app.server import make_server   # ImportError -> o chamador cai no stub

        self._server = make_server(Path(data_dir), "127.0.0.1", 0)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.label = f"servidor real (127.0.0.1:{self._port})"

    def _fetch(self, url: str) -> tuple[int, str]:
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._port}{url}", timeout=60) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass


class StubBridge(ApiBridge):
    """Provisório: lê os JSONs de `data_dir` direto (sem filtros/ordenação). Usado só se o servidor real não existir."""

    def __init__(self, data_dir: Path, reason: str = ""):
        super().__init__()
        self.dir = Path(data_dir)
        self.label = "STUB (JSONs direto)" + (f" - servidor real indisponível: {reason}" if reason else "")

    def _read(self, *parts: str) -> Any:
        p = self.dir.joinpath(*parts)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _runs(self) -> list[dict]:
        idx = self._read("index.json") or {}
        return list(idx.get("runs") or [])

    def _fetch(self, url: str) -> tuple[int, str]:
        parts = urlsplit(url)
        segs = [unquote(s) for s in parts.path.split("/") if s][1:]   # sem "api"
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}

        def ok(o: Any) -> tuple[int, str]:
            return 200, json.dumps(o)

        def nf(msg: str) -> tuple[int, str]:
            return 404, json.dumps({"error": msg})

        if segs == ["meta"]:
            runs = self._runs()
            sess = (self._read("sessions.json") or {}).get("sessions") or {}
            cfgs = sorted((self.dir / "configs").glob("*.json")) if (self.dir / "configs").exists() else []
            starts = sorted(r.get("started_at") or "" for r in runs)
            models = sorted({r.get("model") for r in runs if r.get("model")})
            return ok({"data_dir": str(self.dir), "n_runs": len(runs), "n_sessions": len(sess), "n_configs": len(cfgs),
                       "first_run_at": starts[0] if starts else None, "last_run_at": starts[-1] if starts else None,
                       "models": models, "origins": sorted({r.get("origin") for r in runs if r.get("origin")}),
                       "statuses": sorted({r.get("status") for r in runs if r.get("status")}), "generated_at": None})
        if segs == ["runs"]:
            runs = sorted(self._runs(), key=lambda r: r.get("started_at") or "", reverse=True)
            limit, offset = int(q.get("limit", 50)), int(q.get("offset", 0))
            items = [dict({"tools": [], "skills_used": [], "ttft_s": None, "cache_read_tokens": 0, "total_tokens": (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)}, **r) for r in runs]
            return ok({"total": len(items), "limit": limit, "offset": offset, "items": items[offset:offset + limit], "facets": {"status": {}, "model": {}, "origin": {}, "session": {}}})
        if len(segs) >= 2 and segs[0] == "runs":
            rid = segs[1]
            base = Path("runs") / rid
            if len(segs) == 2:
                d = self._read(*base.parts, "run.json")
                return ok(d) if d else nf(f"run {rid} não encontrado")
            if segs[2] == "trace":
                run, sp = self._read(*base.parts, "run.json"), self._read(*base.parts, "spans.json")
                if not run or not sp:
                    return nf(f"run {rid} não encontrado")
                spans = [dict(s, brief={}, offset_s=s.get("start_offset_s"), duration_s=s.get("duration_s")) for s in sp.get("spans", [])]
                return ok({"run": run, "root_ids": sp.get("root_ids", []), "spans": spans})
            if segs[2] == "spans" and len(segs) == 4:
                sp = self._read(*base.parts, "spans.json") or {}
                span = next((s for s in sp.get("spans", []) if s.get("span_id") == segs[3]), None)
                return ok({"span": span, "parent_chain": []}) if span else nf("span não encontrado")
            if segs[2] == "files" and len(segs) == 4:
                d = self._read(*base.parts, segs[3])
                return ok(d) if d is not None else nf("arquivo não encontrado")
        if segs == ["sessions"]:
            sess = (self._read("sessions.json") or {}).get("sessions") or {}
            return ok({"items": [dict(s, first_message="", n_errors=0, duration_s=0, statuses={}, totals=s.get("totals") or {}) for s in sess.values()]})
        if len(segs) == 2 and segs[0] == "sessions":
            sess = (self._read("sessions.json") or {}).get("sessions") or {}
            s = sess.get(segs[1])
            if not s:
                return nf("sessão não encontrada")
            runs = [r for r in self._runs() if r.get("session_id") == segs[1]]
            return ok({"session": s, "runs": runs, "messages": []})
        if segs == ["configs"]:
            items = []
            for p in sorted((self.dir / "configs").glob("*.json")) if (self.dir / "configs").exists() else []:
                c = json.loads(p.read_text(encoding="utf-8"))
                items.append({"hash": p.stem, "model": (c.get("model") or {}).get("spec"), "provider": None, "created_at": c.get("created_at"),
                              "system_prompt_chars": 0, "n_rules": 0, "n_skills": 0, "n_subagents": 0, "runs": 0, "first_used_at": None, "last_used_at": None})
            return ok({"items": items})
        if len(segs) == 2 and segs[0] == "configs":
            c = self._read("configs", segs[1] + ".json")
            return ok(dict(c, runs=[])) if c else nf("config não encontrada")
        if segs == ["stats"]:
            return ok({"range": {"from": None, "to": None, "bucket": "day"}, "kpis": {}, "series": [], "status_counts": {}, "by_model": [], "by_tool": [],
                       "by_agent": [], "latency_hist": {"edges": [], "counts": []}, "tokens_hist": {"edges": [], "counts": []}, "slowest_runs": [], "recent_errors": []})
        if segs in (["llm_calls"], ["tool_calls"]):
            return ok({"total": 0, "items": []})
        return nf(f"rota de API desconhecida (stub): {parts.path}")


def open_bridge(data_dir: Path, mode: str = "auto") -> ApiBridge:
    """mode: 'auto' (servidor real se existir, senão stub), 'server' (exige o real) ou 'stub'."""
    if mode == "stub":
        return StubBridge(data_dir)
    try:
        return HttpBridge(data_dir)
    except Exception as e:
        if mode == "server":
            raise
        return StubBridge(data_dir, f"{type(e).__name__}: {str(e)[:80]}")


# ---------------------------------------------------------------------------------------------------------------------
# problemas e resultados
# ---------------------------------------------------------------------------------------------------------------------

@dataclass
class Problem:
    severity: str          # "erro" | "aviso"
    kind: str              # console.error | exceção | errbox | spinner | vazia | texto | api | harness | ...
    message: str
    stack: str = ""
    phase: str = ""
    count: int = 1

    def key(self) -> tuple:
        return (self.severity, self.kind, self.message[:200], self.stack.splitlines()[:3].__str__() if self.stack else "")


@dataclass
class RouteResult:
    route: str
    status: str = "ok"             # ok | failed | skipped
    problems: list[Problem] = field(default_factory=list)
    elapsed_s: float = 0.0
    actions: int = 0
    note: str = ""

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == "erro"]

    @property
    def warnings(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == "aviso"]


@dataclass
class Report:
    results: list[RouteResult] = field(default_factory=list)
    api_label: str = ""
    data_dir: str = ""
    strict: bool = False

    def failed(self) -> list[RouteResult]:
        return [r for r in self.results if r.status == "failed"]

    @property
    def ok(self) -> bool:
        return not self.failed()

    def counts(self) -> dict[str, int]:
        c = {"ok": 0, "skipped": 0, "failed": 0}
        for r in self.results:
            c[r.status] += 1
        return c


@dataclass
class Route:
    hash: str
    expect: str | None = None
    expect_is_error: bool = False
    skip_actions: bool = False


# ---------------------------------------------------------------------------------------------------------------------
# página (um contexto QuickJS)
# ---------------------------------------------------------------------------------------------------------------------

class Page:
    def __init__(self, runtime, bundle: Bundle, bridge: ApiBridge | None, hash_: str = "", timeout: float = 120.0, verbose: bool = False):
        import quickjs_rs

        self._qjs = quickjs_rs
        self.rt = runtime
        self.bundle = bundle
        self.bridge = bridge
        self.timeout = timeout
        self.verbose = verbose
        self.problems: dict[tuple, Problem] = {}
        self.broken = False
        self.ctx = runtime.new_context(timeout=timeout)
        self.ctx.register("__host_fetch", self._host_fetch)
        self.ctx.eval(f"globalThis.__SMOKE_HASH = {json.dumps(hash_)}; 0")
        try:
            self.ctx.eval(bundle.source, filename="bundle.js")
        except quickjs_rs.JSError as e:
            self.broken = True
            self._add_js_error("carga", "erro ao carregar os scripts", e)
        except Exception as e:
            self.broken = True
            self.add(Problem("erro", "harness", f"falha ao carregar o bundle: {type(e).__name__}: {e}", phase="carga"))

    # -- util
    def close(self) -> None:
        try:
            self.ctx.close()
        except Exception:
            pass

    def add(self, p: Problem) -> None:
        k = p.key()
        if k in self.problems:
            self.problems[k].count += 1
        else:
            self.problems[k] = p

    def _add_js_error(self, phase: str, what: str, e: Exception) -> None:
        stack = self.bundle.map_stack(getattr(e, "stack", "") or "")
        msg = f"{what}: {getattr(e, 'name', type(e).__name__)}: {getattr(e, 'message', e)}"
        self.add(Problem("erro", "exceção", msg, stack, phase))

    def _host_fetch(self, url: str, method: str = "GET"):
        if self.bridge is None:
            return [404, json.dumps({"error": "sem backend"})]
        if method != "GET":
            return [405, json.dumps({"error": "somente leitura"})]
        status, text = self.bridge.get(str(url))
        if status >= 400:
            sev = "erro" if status >= 500 else "aviso"
            try:
                msg = json.loads(text).get("error", "")
            except Exception:
                msg = text[:120]
            self.add(Problem(sev, "api", f"GET {url} -> HTTP {status}: {msg}", phase=self.phase))
        return [status, text]

    phase = ""

    def eval(self, js: str, phase: str | None = None):
        try:
            return self.ctx.eval(js + "\n;")
        except self._qjs.JSError as e:
            self._add_js_error(phase or self.phase, f"erro no harness ao executar `{js[:60]}`", e)
        except Exception as e:
            self.add(Problem("erro", "harness", f"{type(e).__name__}: {e} ao executar `{js[:60]}`", phase=phase or self.phase))
        return None

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self.eval(f"__smoke.setPhase({json.dumps(phase)}); 0")

    # -- microtasks e timers virtuais
    def drain(self) -> None:
        eng = getattr(self.ctx, "_engine_ctx", None)
        if eng is None:
            return
        self.rt._deadline = time.monotonic() + self.timeout
        try:
            for _ in range(200_000):
                if not eng.run_pending_jobs():
                    return
            self.add(Problem("erro", "loop", "fila de microtasks não esvaziou (loop de Promises?)", phase=self.phase))
        except Exception as e:
            self.add(Problem("erro", "harness", f"{type(e).__name__} ao processar microtasks: {e}", phase=self.phase))
        finally:
            self.rt._deadline = None

    def settle(self, budget_ms: int = 3000, max_steps: int = 4000) -> None:
        """Esvazia microtasks e roda os timers virtuais (fetch, debounce, rAF, hashchange...) por até `budget_ms` de relógio virtual."""
        self.drain()
        now = self.eval("__smoke.now") or 0
        limit = int(now) + budget_ms
        for _ in range(max_steps):
            ran = self.eval(f"__smoke.runNext({limit})")
            self.drain()
            if not ran:
                return
        self.add(Problem("aviso", "timers", f"mais de {max_steps} timers no mesmo intervalo (setInterval muito rápido?)", phase=self.phase))

    # -- coleta do que o JS capturou
    def collect(self) -> None:
        raw = self.eval("__smoke.takeErrors()")
        if not raw:
            return
        data = json.loads(raw)
        for e in data["errors"]:
            stack = self.bundle.map_stack(e.get("stack", ""), internal=self.verbose)
            if e["kind"] == "console.error":
                self.add(Problem("erro", "console.error", e["message"][:500], stack, e.get("phase", "")))
            else:
                where = f" ({e['where']})" if e.get("where") else ""
                self.add(Problem("erro", "exceção", f"{e['name']}: {e['message']}{where}"[:500], stack, e.get("phase", "")))
        for e in data["soft"]:
            stack = self.bundle.map_stack(e.get("stack", ""), internal=self.verbose)
            self.add(Problem("aviso", "then", f"exceção em callback .then/.catch: {e['name']}: {e['message']}"[:400], stack, e.get("phase", "")))
        for w in data["warnings"]:
            self.add(Problem("aviso", "console.warn", w["text"][:300], self.bundle.map_stack(w.get("stack", ""), max_frames=4), w.get("phase", "")))

    def state(self) -> dict | None:
        raw = self.eval("JSON.stringify(__smoke.state())")
        return json.loads(raw) if raw else None

    def quick(self) -> dict:
        raw = self.eval("__smoke.quick()")
        return json.loads(raw) if raw else {"path": "", "errboxes": [], "notFound": False}


# ---------------------------------------------------------------------------------------------------------------------
# verificações e interações
# ---------------------------------------------------------------------------------------------------------------------

def _route_path(h: str) -> str:
    return re.sub(r"^#/?", "", h).split("?")[0]


def _check_state(page: Page, route: Route | None, label: str) -> str:
    """Verifica a tela atual; devolve 'ok' | 'skipped'."""
    st = page.state()
    if not st:
        return "ok"
    ph = label
    if st["construction"]:
        return "skipped"
    if not st["hasView"]:
        page.add(Problem("erro", "vazia", "contêiner #view não existe (o shell não montou)", phase=ph))
        return "ok"
    if st["notFound"]:
        page.add(Problem("erro", "rota", f"'Página não encontrada' em {st['hash']}", phase=ph))
    for t in st["errboxes"]:
        page.add(Problem("erro", "errbox", t, phase=ph))
    if st["loading"]:
        page.add(Problem("erro", "spinner", f"{st['loading']} indicador(es) de carregamento ainda na tela após esperar (carga que não terminou ou view que travou)", phase=ph))
    if st["viewChars"] == 0:
        page.add(Problem("erro", "vazia", "a view não renderizou nenhum texto", phase=ph))
    for s in st["suspicious"]:
        page.add(Problem("aviso", "texto", f"texto suspeito na tela: ...{s}...", phase=ph))
    if st["missingModule"]:
        page.add(Problem("aviso", "módulo", f"módulo ausente: {st['missingModule']}", phase=ph))
    if route and route.expect:
        if not page.eval(f"__smoke.hasText({json.dumps(route.expect)})"):
            page.add(Problem("erro" if route.expect_is_error else "aviso", "texto", f"texto esperado ausente na tela: {route.expect!r}", phase=ph))
    return "ok"


def _do_actions(page: Page, route_hash: str, max_actions: int, label: str) -> int:
    """Percorre cliques/abas/selects/inputs da view. Se uma ação navega para outra rota, confere e volta."""
    n = 0
    base = _route_path(route_hash)
    seen_err: set[str] = set()
    for _ in range(max_actions):
        act = page.eval("__smoke.nextAction()")
        if not act:
            break
        desc = act["desc"]
        page.set_phase(f"{label}: {desc}")
        page.eval("__smoke.perform()")
        page.settle(1500)
        page.collect()
        n += 1
        q = page.quick()
        for t in q["errboxes"]:
            if t not in seen_err:
                seen_err.add(t)
                page.add(Problem("erro", "errbox", t, phase=page.phase))
        if q["path"] != base:
            if q["notFound"]:
                page.add(Problem("erro", "rota", f"'Página não encontrada' após {desc} (#/{q['path']})", phase=page.phase))
            else:
                page.settle(3000)
                page.collect()
                _check_state(page, None, f"{page.phase} -> #/{q['path']}")
                page.collect()
            page.set_phase(f"{label}: voltar à rota")
            page.eval(f"__smoke.visit({json.dumps(route_hash)}); 0")
            page.settle(3000)
            page.collect()
    return n


def _do_extras(page: Page, label: str) -> None:
    """hover, teclado, resize, tema, atualizar e intervalo de tempo."""
    steps = [
        ("hover", "__smoke.hover(30)"),
        ("teclado", "__smoke.keys()"),
        ("resize (480px)", "__smoke.resize(480)"),
        ("resize (1280px)", "__smoke.resize(1280)"),
        ("tema escuro", "__smoke.globalAction('theme')"),
        ("tema claro", "__smoke.globalAction('theme')"),
        ("atualizar", "__smoke.globalAction('refresh')"),
        ("intervalo 7d", "__smoke.globalAction('range')"),
        ("intervalo tudo", "__smoke.globalAction('range-restore')"),
    ]
    for name, js in steps:
        page.set_phase(f"{label}: {name}")
        res = page.eval(js)
        page.settle(2500)
        page.collect()
        if isinstance(res, str) and "ausente" in res:
            page.add(Problem("aviso", "shell", f"{name}: {res}", phase=page.phase))
        q = page.quick()
        for t in q["errboxes"]:
            page.add(Problem("erro", "errbox", t, phase=page.phase))


def run_route(runtime, bundle: Bundle, bridge: ApiBridge | None, route: Route, max_actions: int, verbose: bool = False) -> RouteResult:
    t0 = time.monotonic()
    res = RouteResult(route.hash)
    page = Page(runtime, bundle, bridge, route.hash, verbose=verbose)
    try:
        status = "ok"
        if not page.broken:
            page.set_phase("carga da página")
            page.eval("__smoke.load(); 0")
            page.settle(4000)
            page.collect()
            status = _check_state(page, route, "carga da página")
            page.collect()
            if status == "ok" and not route.skip_actions and not page.broken:
                res.actions = _do_actions(page, route.hash, max_actions, "interação")
                _do_extras(page, "interação")
                page.settle(3000)
                page.collect()
        res.problems = list(page.problems.values())
        res.status = "skipped" if status == "skipped" else ("failed" if res.errors else "ok")
        if res.status == "skipped":
            res.note = "view ausente ('Em construção')"
    finally:
        page.close()
        res.elapsed_s = time.monotonic() - t0
    return res


def run_sequence(runtime, bundle: Bundle, bridge: ApiBridge, routes: list[Route], verbose: bool = False) -> RouteResult:
    """Todas as rotas numa só página, uma após a outra (hashchange), com algumas ações em cada."""
    t0 = time.monotonic()
    res = RouteResult("(sequência de navegação)")
    page = Page(runtime, bundle, bridge, "", verbose=verbose)
    try:
        if not page.broken:
            page.set_phase("carga da página")
            page.eval("__smoke.load(); 0")
            page.settle(4000)
            page.collect()
            for r in routes:
                label = f"sequência {r.hash}"
                page.set_phase(label)
                page.eval(f"__smoke.visit({json.dumps(r.hash)}); 0")
                page.settle(4000)
                page.collect()
                if _check_state(page, r, label) == "skipped":
                    continue
                page.collect()
                if not r.skip_actions:
                    res.actions += _do_actions(page, r.hash, 3, label)
            page.settle(3000)
            page.collect()
        res.problems = list(page.problems.values())
        res.status = "failed" if res.errors else "ok"
    finally:
        page.close()
        res.elapsed_s = time.monotonic() - t0
    return res


# ---------------------------------------------------------------------------------------------------------------------
# descoberta de rotas
# ---------------------------------------------------------------------------------------------------------------------

def discover(bridge: ApiBridge, max_runs: int = 4) -> tuple[list[Route], dict]:
    """Monta a lista de rotas a partir dos dados (usa ids reais). Devolve (rotas, ids)."""
    ids: dict[str, Any] = {"runs": [], "sessions": [], "configs": [], "spans": {}}
    routes = [Route(h, skip_actions=False) for h in STATIC_ROUTES]

    data = bridge.get_json("/api/runs?limit=500") or {}
    items = [i for i in (data.get("items") or []) if i.get("run_id")]
    chosen: list[dict] = []

    def pick(pred: Callable[[dict], bool], key: Callable[[dict], Any] | None = None) -> None:
        pool = [i for i in items if pred(i) and i not in chosen]
        if pool:
            chosen.append(max(pool, key=key) if key else pool[0])

    pick(lambda i: i.get("status") == "completed")   # o primeiro (e o que vale para {run}) é um run concluído
    pick(lambda i: (i.get("errors") or 0) > 0)
    pick(lambda i: (i.get("subagent_calls") or 0) > 0, key=lambda i: i.get("subagent_calls") or 0)
    pick(lambda i: i.get("status") not in ("completed", "error", None))
    pick(lambda i: True, key=lambda i: i.get("total_tokens") or 0)
    chosen = chosen[:max_runs]

    for n, it in enumerate(chosen):
        rid = it["run_id"]
        ids["runs"].append(rid)
        short = rid[:8]
        routes.append(Route(f"#/runs/{rid}", expect=short, expect_is_error=True))
        trace = bridge.get_json(f"/api/runs/{rid}/trace") or {}
        spans = trace.get("spans") or []

        def first(pred: Callable[[dict], bool]) -> str | None:
            return next((s.get("span_id") for s in spans if pred(s)), None)

        picks = [
            first(lambda s: s.get("type") == "llm"),
            first(lambda s: s.get("type") == "tool" and (s.get("brief") or {}).get("kind") not in ("subagent",)),
            first(lambda s: (s.get("brief") or {}).get("kind") == "subagent" or s.get("name") == "task"),
        ]
        sel = [p for i, p in enumerate(dict.fromkeys(x for x in picks if x)) if i < (3 if n < 2 else 1)]
        ids["spans"][rid] = sel
        for sid in sel:
            routes.append(Route(f"#/runs/{rid}?span={sid}", expect=short, expect_is_error=True))
        if n < 2:
            for tab in RUN_TABS:
                routes.append(Route(f"#/runs/{rid}?tab={tab}", expect=short, expect_is_error=True))

    sess = (bridge.get_json("/api/sessions") or {}).get("items") or []
    for s in sess[:2]:
        sid = s.get("session_id")
        if sid:
            ids["sessions"].append(sid)
            routes.append(Route(f"#/sessions/{sid}", expect=str(sid)[:8]))
    cfgs = (bridge.get_json("/api/configs") or {}).get("items") or []
    for c in cfgs[:2]:
        h = c.get("hash")
        if h:
            ids["configs"].append(h)
            routes.append(Route(f"#/prompts/{h}", expect=str(h)[:8]))
    return routes, ids


def _expand_user_route(raw: str, ids: dict) -> Route:
    h = raw.strip()
    if not h.startswith("#"):
        h = "#/" + h.lstrip("/")
    for key, name in (("runs", "run"), ("sessions", "session"), ("configs", "config")):
        if "{" + name + "}" in h:
            if not ids[key]:
                raise SystemExit(f"--route {raw}: não há {name} nos dados")
            h = h.replace("{" + name + "}", ids[key][0])
    return Route(h)


# ---------------------------------------------------------------------------------------------------------------------
# relatório
# ---------------------------------------------------------------------------------------------------------------------

def _fmt_problem(p: Problem, verbose: bool) -> list[str]:
    tag = "erro " if p.severity == "erro" else "aviso"
    cnt = f" (x{p.count})" if p.count > 1 else ""
    lines = [f"      [{tag}] {p.kind}: {p.message}{cnt}"]
    if p.phase:
        lines.append(f"             durante: {p.phase}")
    if p.stack:
        stack = p.stack.splitlines()
        shown = stack if verbose else stack[:6]
        lines.extend("             " + s.strip() for s in shown)
        if len(shown) < len(stack):
            lines.append(f"             ... (+{len(stack) - len(shown)} linhas; use --smoke-verbose)")
    return lines


def format_result(r: RouteResult, verbose: bool = False, strict: bool = False) -> str:
    tag = {"ok": "OK     ", "failed": "FALHOU ", "skipped": "PULADA "}[r.status]
    extra = f"{r.elapsed_s:.1f}s"
    if r.actions:
        extra += f", {r.actions} ações"
    head = f"  {tag} {r.route}  ({extra})"
    if r.note:
        head += f"  {r.note}"
    lines = [head]
    probs = r.problems
    if r.status == "ok" and not verbose:
        if probs:
            lines[0] += f"  [{len(r.warnings)} aviso(s)]"
        return "\n".join(lines)
    ordered = sorted(probs, key=lambda p: (p.severity != "erro",))
    limit = len(ordered) if verbose else 8
    for p in ordered[:limit]:
        lines.extend(_fmt_problem(p, verbose))
    if len(ordered) > limit:
        lines.append(f"      ... (+{len(ordered) - limit} problemas)")
    return "\n".join(lines)


def format_report(rep: Report, verbose: bool = False) -> str:
    out = [f"Smoke do tracing_app  (dados: {rep.data_dir}; API: {rep.api_label})"]
    out.extend(format_result(r, verbose) for r in rep.results)
    c = rep.counts()
    out.append(f"Resumo: {c['ok']} OK, {c['skipped']} puladas, {c['failed']} FALHARAM  ({len(rep.results)} rotas)")
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------------------------------
# entrada
# ---------------------------------------------------------------------------------------------------------------------

def run(data_dir: Path, routes: list[str] | None = None, out: Callable[[str], Any] | None = None, api: str = "auto",
        max_actions: int = 40, max_runs: int = 4, verbose: bool = False, strict: bool = False, sequence: bool = True) -> Report:
    """Roda o smoke; imprime cada rota ao terminar (`out`, padrão print) e devolve o `Report` (`.ok` = nada falhou).
    `strict=True` conta avisos como falhas."""
    import quickjs_rs

    if out is None:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
        except Exception:
            pass
        out = print
    data_dir = Path(data_dir)
    bridge = open_bridge(data_dir, api)
    rep = Report(api_label=bridge.label, data_dir=str(data_dir), strict=strict)
    out(f"Smoke do tracing_app  (dados: {data_dir}; API: {bridge.label})")
    bundle = build_bundle(True)
    runtime = quickjs_rs.Runtime(memory_limit=512 * 1024 * 1024, stack_limit=2 * 1024 * 1024)
    try:
        found, ids = discover(bridge, max_runs)
        todo = [_expand_user_route(r, ids) for r in routes] if routes else found
        if not ids["runs"]:
            out("  (aviso: nenhum run nos dados; só as rotas estáticas serão testadas)")
        for route in todo:
            res = run_route(runtime, bundle, bridge, route, max_actions, verbose)
            if strict and res.status == "ok" and res.warnings:
                res.status = "failed"
            rep.results.append(res)
            out(format_result(res, verbose, strict))
        runnable = [r for r, res in zip(todo, rep.results) if res.status != "skipped"]
        if sequence and len(runnable) >= 2:
            seq = run_sequence(runtime, bundle, bridge, runnable, verbose)
            if strict and seq.status == "ok" and seq.warnings:
                seq.status = "failed"
            rep.results.append(seq)
            out(format_result(seq, verbose, strict))
    finally:
        bridge.close()
        try:
            runtime.close()
        except Exception:
            pass
    c = rep.counts()
    out(f"Resumo: {c['ok']} OK, {c['skipped']} puladas, {c['failed']} FALHARAM  ({len(rep.results)} rotas)")
    return rep
