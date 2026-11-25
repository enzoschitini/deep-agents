/* Roteador por hash: `#/runs/abc?span=x&tab=y`. Monta a view da rota em #view e chama a limpeza da anterior. */
TA.router = (function () {
  // [padrão, nome da view, item do menu]
  const ROUTES = [
    ['', 'dashboard', 'dashboard'],
    ['runs', 'runs', 'runs'],
    ['runs/:id', 'trace', 'runs'],
    ['sessions', 'sessions', 'sessions'],
    ['sessions/:id', 'session', 'sessions'],
    ['prompts', 'prompts', 'prompts'],
    ['prompts/:hash', 'prompt', 'prompts'],
    ['data', 'data', 'data'],
    ['data/:kind', 'data', 'data'],
  ];
  let cleanups = [];
  let refreshers = [];
  let current = null;
  let container = null;

  function parse() {
    const raw = (location.hash || '#/').replace(/^#\/?/, '');
    const [pathPart, queryPart] = raw.split('?');
    const segs = pathPart.split('/').filter(Boolean).map(decodeURIComponent);
    return { segs, path: segs.join('/'), query: Object.fromEntries(new URLSearchParams(queryPart || '')) };
  }

  function match(segs) {
    for (const [pattern, view, nav] of ROUTES) {
      const ps = pattern.split('/').filter(Boolean);
      if (ps.length !== segs.length) continue;
      const params = {};
      let ok = true;
      ps.forEach((p, i) => { if (p.startsWith(':')) params[p.slice(1)] = segs[i]; else if (p !== segs[i]) ok = false; });
      if (ok) return { view, nav, params };
    }
    return null;
  }

  function hashFor(path, query) {
    const p = path.split('/').filter(Boolean).map(encodeURIComponent).join('/');
    return '#/' + p + TA.util.qs(query);
  }

  function teardown() {
    cleanups.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
    cleanups = []; refreshers = [];
    TA.ui.tipHide();
  }

  function render() {
    const { segs, query } = parse();
    const m = match(segs);
    teardown();
    TA.util.clear(container);
    TA.shell.setCrumbs([]); TA.shell.setActions([]);
    if (!m) { TA.shell.setNav('');   container.appendChild(TA.ui.empty('Página não encontrada', '#/' + segs.join('/'))); return; }
    TA.shell.setNav(m.nav);
    current = { ...m, query };
    const view = TA.views[m.view];
    if (!view) { container.appendChild(TA.ui.empty('Em construção', `A view "${m.view}" ainda não foi carregada.`)); return; }
    const ctx = {
      el: container, params: m.params, query,
      nav: (path, q) => { location.hash = hashFor(path, q); },
      setQuery(obj) {
        const merged = { ...current.query, ...obj };
        Object.keys(merged).forEach((k) => { if (merged[k] === null || merged[k] === undefined || merged[k] === '') delete merged[k]; });
        current.query = merged;
        history.replaceState(null, '', hashFor(segs.join('/'), merged));
      },
      crumbs: (c) => TA.shell.setCrumbs(c),
      actions: (a) => TA.shell.setActions(a),
      onCleanup: (fn) => cleanups.push(fn),
      onRefresh: (fn) => refreshers.push(fn),
      range: () => ({ key: TA.state.range, since: TA.util.sinceOf(TA.state.range) }),
    };
    try {
      const out = view.mount(ctx);
      if (typeof out === 'function') cleanups.push(out);
      else if (out && typeof out.then === 'function') out.then((fn) => { if (typeof fn === 'function') cleanups.push(fn); }).catch((e) => showError(e));
    } catch (e) { showError(e); }
  }

  function showError(e) {
    console.error(e);
    TA.util.clear(container);
    container.appendChild(TA.ui.error(e));
  }

  return {
    start(el) {
      container = el;
      window.addEventListener('hashchange', render);
      TA.bus.on('refresh', () => refreshers.slice().forEach((fn) => { try { fn(); } catch (e) { console.error(e); } }));
      render();
    },
    parse, hashFor,
    go(path, query) { location.hash = hashFor(path, query); },
    /** link (<a>) para uma rota */
    link(path, query, ...children) { return TA.h('a', { href: hashFor(path, query) }, ...children); },
  };
})();
