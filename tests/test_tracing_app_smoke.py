"""Smoke do front-end do tracing_app (QuickJS + DOM falso, sem navegador).

Dois blocos:
- testes do próprio harness (shim, timers virtuais, fetch, captura de erros, mapa de stacks, detecção de view ausente);
- smoke de verdade: gera dados sintéticos com `dev_seed` e exige que todas as rotas passem.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("quickjs_rs")

from deep_agents.tracing_app.smoke import runner as R  # noqa: E402

_RAIZ = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------

@pytest.fixture()
def runtime():
    import quickjs_rs

    rt = quickjs_rs.Runtime(memory_limit=256 * 1024 * 1024)
    yield rt
    rt.close()


class FakeBridge(R.ApiBridge):
    label = "fake"

    def __init__(self, routes: dict[str, tuple[int, object]] | None = None):
        super().__init__()
        self.routes = routes or {}

    def _fetch(self, url):
        path = url.split("?")[0]
        status, body = self.routes.get(path, (404, {"error": "sem rota " + path}))
        return status, json.dumps(body)


def shim_page(runtime, bridge=None, hash_="", extra=None):
    return R.Page(runtime, R.build_bundle(False, extra), bridge, hash_)


def empty_dir_bridge(tmp_path):
    return R.StubBridge(tmp_path)


# ---------------------------------------------------------------------------------------------------------------------
# o shim
# ---------------------------------------------------------------------------------------------------------------------

def test_shim_dom_basico(runtime):
    p = shim_page(runtime)
    assert not p.broken and not p.problems
    js = """
      const a = document.createElement('div'); a.className = 'x y'; a.dataset.fooBar = '1';
      const b = document.createElement('span'); b.textContent = 'oi';
      a.append(b, 'tchau'); document.body.appendChild(a);
      a.classList.toggle('z'); a.classList.remove('x');
      JSON.stringify([a.className, a.getAttribute('data-foo-bar'), a.textContent, a.children.length, a.childNodes.length,
        document.querySelector('div.y > span').textContent, document.querySelectorAll('#app, div.z').length,
        a.closest('body') === document.body, b.nextSibling.nodeType, a.contains(b), typeof document.querySelectorAll('div').map])
    """
    assert json.loads(p.eval(js)) == ["y z", "1", "oitchau", 1, 2, "oi", 2, True, 3, True, "undefined"]


def test_shim_innerhtml_template_e_svg(runtime):
    p = shim_page(runtime)
    out = p.eval("""
      const t = document.createElement('template');
      t.innerHTML = '<svg class="ico" viewBox="0 0 24 24"><path d="M0 0h1"/></svg>';
      const s = t.content.firstChild;
      const d = document.createElement('div'); d.innerHTML = '<p a="1">x &amp; y</p><br><i></i>';
      JSON.stringify([s.localName, s.namespaceURI.endsWith('svg'), s.firstChild.localName, s.getAttribute('viewBox'), d.children.length, d.firstChild.textContent, d.innerHTML])
    """)
    assert json.loads(out) == ["svg", True, "path", "0 0 24 24", 3, "x & y", '<p a="1">x &amp; y</p><br><i></i>']


def test_shim_selects_e_formularios(runtime):
    p = shim_page(runtime)
    out = p.eval("""
      const s = document.createElement('select');
      ['a', 'b', 'c'].forEach((v) => s.appendChild(Object.assign(document.createElement('option'), { value: v })));
      const first = s.value; s.value = 'c';
      const i = document.createElement('input'); i.type = 'checkbox'; i.click();
      JSON.stringify([first, s.value, s.selectedIndex, i.checked, i.type])
    """)
    assert json.loads(out) == ["a", "c", 2, True, "checkbox"]


def test_shim_erros_de_dom_como_no_navegador(runtime):
    p = shim_page(runtime)
    out = p.eval("""
      const r = [];
      try { document.body.appendChild('texto'); } catch (e) { r.push(e.name); }
      try { document.body.removeChild(document.createElement('p')); } catch (e) { r.push(e.name); }
      try { document.querySelector('div['); } catch (e) { r.push(e.name); }
      try { document.createElement('b').classList.add('a b'); } catch (e) { r.push(e.name); }
      JSON.stringify(r)
    """)
    assert json.loads(out) == ["TypeError", "NotFoundError", "SyntaxError", "InvalidCharacterError"]


def test_shim_eventos_propagam_e_listener_async_vira_erro(runtime):
    p = shim_page(runtime)
    p.eval("""
      globalThis.order = [];
      const a = document.createElement('div'), b = document.createElement('button');
      a.appendChild(b); document.body.appendChild(a);
      document.addEventListener('click', () => order.push('doc'));
      a.addEventListener('click', () => order.push('a'));
      b.addEventListener('click', async () => { order.push('b'); throw new Error('async quebrou'); });
      b.click(); 0
    """)
    p.settle()
    p.collect()
    assert json.loads(p.eval("JSON.stringify(order)")) == ["b", "a", "doc"]
    assert any("async quebrou" in e.message for e in p.problems.values())


def test_shim_timers_virtuais_hashchange_e_replacestate(runtime):
    p = shim_page(runtime)
    p.eval("""
      globalThis.log = [];
      addEventListener('hashchange', () => log.push('hash:' + location.hash));
      setTimeout(() => log.push('t2000'), 2000);
      setTimeout(() => log.push('t10'), 10);
      location.hash = '#/runs';
      history.replaceState(null, '', '#/runs?x=1');
      0
    """)
    p.settle(500)
    assert json.loads(p.eval("JSON.stringify(log)")) == ["hash:#/runs?x=1", "t10"] or json.loads(p.eval("JSON.stringify(log)")) == ["hash:#/runs", "t10"]
    p.settle(5000)
    assert json.loads(p.eval("JSON.stringify(log)"))[-1] == "t2000"


def test_shim_url_search_params(runtime):
    p = shim_page(runtime)
    out = p.eval("""
      const q = new URLSearchParams('a=1&b=x+y&a=2');
      JSON.stringify([q.get('b'), q.getAll('a'), Object.fromEntries(new URLSearchParams('span=1&tab=e')), new URLSearchParams({k: 'a b'}).toString(),
        new URL('/api/x?y=1#h', 'http://localhost:1/').pathname])
    """)
    assert json.loads(out) == ["x y", ["1", "2"], {"span": "1", "tab": "e"}, "k=a+b", "/api/x"]


def test_fetch_usa_a_ponte_e_registra_http_de_erro(runtime):
    bridge = FakeBridge({"/api/ok": (200, {"v": 1}), "/api/boom": (500, {"error": "quebrou"})})
    p = shim_page(runtime, bridge)
    p.eval("""
      globalThis.res = [];
      fetch('/api/ok').then((r) => r.json()).then((j) => res.push(j.v));
      fetch('/api/boom').then((r) => res.push(r.status + ':' + r.ok));
      fetch('/api/nada').then((r) => res.push(r.status));
      0
    """)
    p.settle()
    assert sorted(json.loads(p.eval("JSON.stringify(res)")), key=str) == [1, 404, "500:false"]
    kinds = {(x.kind, x.severity) for x in p.problems.values()}
    assert ("api", "erro") in kinds and ("api", "aviso") in kinds   # 5xx = erro (bug do backend); 4xx = aviso


def test_captura_de_erros_console_timer_e_then(runtime):
    p = shim_page(runtime)
    p.eval("""
      console.error('falhou', {a: 1});
      setTimeout(() => { undefinedFunction(); }, 5);
      Promise.resolve().then(() => { throw new TypeError('no then'); }).catch(() => {});
      0
    """)
    p.settle()
    p.collect()
    got = {(x.kind, x.severity) for x in p.problems.values()}
    assert ("console.error", "erro") in got
    assert ("exceção", "erro") in got
    assert ("then", "aviso") in got


# ---------------------------------------------------------------------------------------------------------------------
# o runner sobre o app (dados vazios) com views quebradas de propósito
# ---------------------------------------------------------------------------------------------------------------------

_BAD_VIEW = "TA.views.runs = { mount(ctx) { function explode() { return naoExiste.campo; }\nexplode(); } };\n"


def test_view_quebrada_falha_e_o_stack_aponta_o_arquivo(runtime, tmp_path):
    bundle = R.build_bundle(True, [("99_zz_bad.js", _BAD_VIEW)])
    res = R.run_route(runtime, bundle, empty_dir_bridge(tmp_path), R.Route("#/runs"), max_actions=3)
    assert res.status == "failed"
    texts = " ".join(p.message + p.stack for p in res.errors)
    assert "naoExiste" in texts
    assert "99_zz_bad.js:2" in texts          # `naoExiste.campo` está na linha 1 do arquivo; `explode()` na 2


def test_stack_de_erro_em_arquivo_do_app_mostra_nome_e_linha(runtime, tmp_path):
    bad = "TA.views.runs = { mount(ctx) { ctx.el.appendChild(TA.h('div', null, 'ok')); setTimeout(() => { null.x; }, 10); } };\n"
    bundle = R.build_bundle(True, [("98_timer.js", bad)])
    res = R.run_route(runtime, bundle, empty_dir_bridge(tmp_path), R.Route("#/runs"), max_actions=0)
    assert res.status == "failed"
    assert any("98_timer.js:1" in p.stack for p in res.errors), [p.stack for p in res.errors]


def test_errbox_spinner_e_tela_vazia_sao_falhas(runtime, tmp_path):
    cases = {
        "errbox": "TA.views.runs = { mount(ctx) { ctx.el.appendChild(TA.ui.error(new Error('sem dados'))); } };",
        "spinner": "TA.views.runs = { mount(ctx) { ctx.el.appendChild(TA.ui.loading()); } };",
        "vazia": "TA.views.runs = { mount(ctx) { } };",
    }
    for kind, code in cases.items():
        res = R.run_route(runtime, R.build_bundle(True, [("97_x.js", code)]), empty_dir_bridge(tmp_path), R.Route("#/runs"), max_actions=0)
        assert res.status == "failed", kind
        assert any(p.kind == kind for p in res.errors), (kind, res.problems)


def test_view_ausente_e_pulada_e_texto_esperado_e_conferido(runtime, tmp_path):
    res = R.run_route(runtime, R.build_bundle(True, [("97_x.js", "delete TA.views.data;")]), empty_dir_bridge(tmp_path), R.Route("#/data"), max_actions=0)
    assert res.status == "skipped"
    ok_view = "TA.views.runs = { mount(ctx) { ctx.el.appendChild(TA.h('div', null, 'conteúdo abcdef12')); } };"
    bundle = R.build_bundle(True, [("97_x.js", ok_view)])
    assert R.run_route(runtime, bundle, empty_dir_bridge(tmp_path), R.Route("#/runs", expect="abcdef12", expect_is_error=True), max_actions=0).status == "ok"
    assert R.run_route(runtime, bundle, empty_dir_bridge(tmp_path), R.Route("#/runs", expect="zzzz", expect_is_error=True), max_actions=0).status == "failed"


def test_interacoes_clicam_e_pegam_erro_depois_do_clique(runtime, tmp_path):
    view = """TA.views.runs = { mount(ctx) {
      const b = TA.h('button', { onClick: () => { throw new RangeError('clique quebrado'); } }, 'Quebrar');
      ctx.el.appendChild(TA.h('div', null, 'tela', b));
    } };"""
    res = R.run_route(runtime, R.build_bundle(True, [("97_x.js", view)]), empty_dir_bridge(tmp_path), R.Route("#/runs"), max_actions=5)
    assert res.status == "failed" and res.actions >= 1
    assert any("clique quebrado" in p.message and "Quebrar" in p.phase for p in res.errors)


# ---------------------------------------------------------------------------------------------------------------------
# smoke de verdade (dados sintéticos do dev_seed)
# ---------------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    if importlib.util.find_spec("deep_agents.tracing_app.dev_seed") is None:
        pytest.skip("deep_agents.tracing_app.dev_seed ainda não existe")
    out = tmp_path_factory.mktemp("seed_tracing")
    r = subprocess.run([sys.executable, "-m", "deep_agents.tracing_app.dev_seed", "--out", str(out)], cwd=_RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if r.returncode != 0:
        pytest.fail(f"dev_seed falhou:\n{r.stdout[-800:]}\n{r.stderr[-1500:]}")
    return out


def test_smoke_todas_as_rotas_passam(seeded):
    lines: list[str] = []
    report = R.run(seeded, out=lines.append, max_actions=10, max_runs=3)
    assert report.results, "nenhuma rota testada"
    assert report.ok, "\n" + R.format_report(report)
    assert any(r.status == "ok" for r in report.results)
