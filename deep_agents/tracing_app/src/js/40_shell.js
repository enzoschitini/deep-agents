/* Shell: barra lateral, topo (migalhas, ações, intervalo de tempo, atualizar, tema) e o contêiner da view. */
TA.shell = (function () {
  const h = TA.h;
  let crumbsEl, actionsEl, viewEl, navEls = {}, counts = {};

  const NAV = [
    ['dashboard', 'Visão geral', 'dashboard', ''],
    ['runs', 'Traces', 'list', 'runs'],
    ['sessions', 'Sessões', 'chat', 'sessions'],
    ['prompts', 'Prompts', 'layers', 'prompts'],
    ['data', 'Dados', 'db', 'data'],
  ];
  const RANGES = [['1h', 'Última hora'], ['24h', '24 horas'], ['7d', '7 dias'], ['30d', '30 dias'], ['all', 'Tudo']];

  function applyTheme(t) {
    TA.state.theme = t;
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('ta.theme', t); } catch (e) { /* ok */ }
    TA.bus.emit('theme', t);
  }

  function build(root) {
    TA.state.range = TA.util.store.get('range', 'all');
    TA.state.theme = document.documentElement.getAttribute('data-theme') || 'light';

    const nav = NAV.map(([id, label, icon, path]) => {
      const a = h('a', { class: 'nav-item', href: TA.router.hashFor(path, null) }, TA.ui.icon(icon), h('span', null, label), h('span', { class: 'count' }));
      navEls[id] = a;
      return a;
    });
    const sidebar = h('aside', { class: 'sidebar' },
      h('div', { class: 'brand' },
        h('div', { class: 'brand-mark' }, TA.ui.icon('branch')),
        h('div', null, 'Deep Agents', h('small', null, 'Tracing'))),
      nav, h('div', { class: 'sidebar-spacer' }),
      h('div', { class: 'sidebar-foot', id: 'ta-foot' }, 'carregando…'));

    crumbsEl = h('div', { class: 'crumbs' });
    actionsEl = h('div', { class: 'topbar-actions' });
    const range = TA.ui.select({
      options: RANGES.map(([v, l]) => ({ value: v, label: l })), value: TA.state.range, title: 'Intervalo de tempo',
      onChange: (v) => { TA.state.range = v; TA.util.store.set('range', v); TA.bus.emit('refresh', { reason: 'range' }); },
    });
    const themeBtn = h('button', { class: 'btn icon ghost', title: 'Alternar tema', onClick: () => applyTheme(TA.state.theme === 'dark' ? 'light' : 'dark') });
    const paintTheme = () => { TA.util.clear(themeBtn); themeBtn.appendChild(TA.ui.icon(TA.state.theme === 'dark' ? 'sun' : 'moon')); };
    paintTheme(); TA.bus.on('theme', paintTheme);
    const refreshBtn = h('button', { class: 'btn icon ghost', title: 'Atualizar', onClick: () => { loadMeta(); TA.bus.emit('refresh', { reason: 'manual' }); } }, TA.ui.icon('refresh'));

    viewEl = h('main', { class: 'view', id: 'view' });
    root.appendChild(h('div', { class: 'app' }, sidebar,
      h('div', { class: 'main' },
        h('header', { class: 'topbar' }, crumbsEl, h('div', { class: 'topbar-spacer' }), actionsEl, range.el, refreshBtn, themeBtn),
        viewEl)));
    return viewEl;
  }

  async function loadMeta() {
    try {
      const m = await TA.api.meta();
      TA.state.meta = m;
      const foot = document.getElementById('ta-foot');
      if (foot) { TA.util.clear(foot); foot.append(`${TA.fmt.num(m.n_runs)} runs · ${TA.fmt.num(m.n_sessions)} sessões`, h('br'), h('span', { title: m.data_dir }, TA.fmt.trunc(m.data_dir, 38))); }
      const set = (id, n) => { const c = navEls[id] && navEls[id].querySelector('.count'); if (c) c.textContent = n ? TA.fmt.compact(n) : ''; };
      set('runs', m.n_runs); set('sessions', m.n_sessions); set('prompts', m.n_configs);
      TA.bus.emit('meta', m);
    } catch (e) {
      const foot = document.getElementById('ta-foot');
      if (foot) foot.textContent = 'API indisponível: ' + e.message;
    }
  }

  return {
    mount(root) { const v = build(root); loadMeta(); return v; },
    loadMeta,
    setNav(id) { Object.entries(navEls).forEach(([k, el]) => el.classList.toggle('active', k === id)); },
    /** migalhas: [{label, href?}] (o último é o atual) */
    setCrumbs(items) {
      TA.util.clear(crumbsEl);
      (items || []).forEach((it, i) => {
        if (i) crumbsEl.appendChild(h('span', { class: 'sep' }, '/'));
        const last = i === items.length - 1;
        crumbsEl.appendChild(it.href && !last ? h('a', { href: it.href }, it.label) : h('span', { class: 'cur' }, it.label));
      });
    },
    setActions(nodes) { TA.util.clear(actionsEl); (nodes || []).forEach((n) => n && actionsEl.appendChild(n)); },
  };
})();
