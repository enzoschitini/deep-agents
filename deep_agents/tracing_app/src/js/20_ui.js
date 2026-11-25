/* Componentes compartilhados (TA.ui). Todos devolvem elementos DOM; os que têm estado devolvem {el, ...métodos}. */
(function () {
  const h = TA.h;

  /* ------------------------------------------------------------------ ícones (estilo feather, viewBox 24) */
  const ICONS = {
    dashboard: '<rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    doc: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8"/>',
    db: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>',
    refresh: '<path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    sun: '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>',
    moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
    chevR: '<path d="M9 18l6-6-6-6"/>',
    chevD: '<path d="M6 9l6 6 6-6"/>',
    x: '<path d="M18 6L6 18M6 6l12 12"/>',
    filter: '<path d="M22 3H2l8 9.46V19l4 2v-8.54z"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
    tool: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    bot: '<rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4M8 16h.01M16 16h.01"/>',
    zap: '<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>',
    branch: '<path d="M6 3v12"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/>',
    sortUp: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    sortDown: '<path d="M12 5v14M19 12l-7 7-7-7"/>',
    external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
    user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5z"/>',
    code: '<path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/>',
    file: '<path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M13 2v7h7"/>',
    list2: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  };

  TA.ui.icon = function icon(name, cls) {
    const tpl = document.createElement('template');
    tpl.innerHTML = `<svg class="ico ${cls || ''}" viewBox="0 0 24 24">${ICONS[name] || ''}</svg>`;   // markup estático acima, sem dados externos
    return tpl.content.firstChild;
  };

  /* tipos de span/ação -> {ícone, rótulo}. `kind` vem de `tool_calls.json` (tool, subagent, code_eval, todos, skill, file, async_task, summarization) ou do tipo do span (llm, chain). */
  const KINDS = {
    llm: ['zap', 'LLM'], tool: ['tool', 'Tool'], chain: ['branch', 'Chain'], subagent: ['bot', 'Subagent'], skill: ['layers', 'Skill'],
    file: ['file', 'Arquivo'], todos: ['list2', 'Todos'], code_eval: ['code', 'Código'], async_task: ['bot', 'Async'], summarization: ['book', 'Resumo'],
  };
  TA.ui.kindMeta = (kind) => KINDS[kind] || ['branch', kind || '?'];
  TA.ui.kindIcon = function kindIcon(kind) {
    const [ic] = TA.ui.kindMeta(kind);
    const i = TA.ui.icon(ic);
    i.classList.add('kind-' + kind);
    i.style.color = `var(--k-${({ async_task: 'subagent', summarization: 'chain', code_eval: 'code' })[kind] || kind})`;
    return i;
  };

  /* ------------------------------------------------------------------ pequenos blocos */
  TA.ui.badge = (text, kind, title) => h('span', { class: ['badge', kind], title }, text);
  TA.ui.statusBadge = (status) => h('span', { class: ['badge', TA.util.statusKind(status)] }, h('span', { class: 'dot' }), TA.util.statusLabel(status));
  TA.ui.chip = (text, mono) => h('span', { class: ['chip', mono && 'mono'] }, text);
  TA.ui.kpi = ({ label, value, sub, kind, title }) => h('div', { class: ['card', 'kpi', kind], title },
    h('div', { class: 'label' }, label), h('div', { class: 'value' }, value), sub ? h('div', { class: 'sub' }, sub) : null);
  TA.ui.empty = (title, text) => h('div', { class: 'empty' }, h('div', { class: 'big' }, title), text ? h('div', null, text) : null);
  TA.ui.loading = (text = 'Carregando…') => h('div', { class: 'loading' }, h('span', { class: 'spinner' }), ' ', text);
  TA.ui.error = (err) => h('div', { class: 'errbox' }, h('b', null, 'Erro: '), String((err && err.message) || err));
  TA.ui.card = (title, body, { hint, actions } = {}) => h('div', { class: 'card' },
    title ? h('div', { class: 'card-head' }, h('h3', null, title), hint ? h('span', { class: 'hint' }, hint) : null, h('span', { class: 'spacer' }), actions) : null,
    h('div', { class: 'card-body' }, body));
  /** lista chave/valor; `pairs` = [[chave, valor], ...] (valores nulos viram "—") */
  TA.ui.kv = (pairs) => h('dl', { class: 'kv', style: 'margin:0' }, pairs.flatMap(([k, v]) => [h('dt', null, k), h('dd', null, v === null || v === undefined || v === '' ? '—' : v)]));

  TA.ui.copyBtn = function copyBtn(textOrFn, label) {
    return h('button', { class: 'btn sm ghost copy', title: 'Copiar', onClick: (e) => { e.stopPropagation(); TA.util.copy(typeof textOrFn === 'function' ? textOrFn() : textOrFn); } },
      TA.ui.icon('copy', 'sm'), label || null);
  };
  /** bloco de código/texto com botão de copiar */
  TA.ui.code = function code(text, { maxHeight = 420 } = {}) {
    const str = typeof text === 'string' ? text : TA.util.pretty(text);
    return h('div', { class: 'code' }, TA.ui.copyBtn(str), h('pre', { style: { '--maxh': maxHeight + 'px' } }, str));
  };

  /* ------------------------------------------------------------------ controles */
  TA.ui.seg = function seg({ options, value, onChange }) {
    const btns = options.map((o) => h('button', { type: 'button', class: o.value === value ? 'on' : '', onClick: () => set(o.value, true) }, o.label));
    const el = h('div', { class: 'seg' }, btns);
    function set(v, fire) { btns.forEach((b, i) => b.classList.toggle('on', options[i].value === v)); value = v; if (fire && onChange) onChange(v); }
    return { el, set: (v) => set(v, false), get: () => value };
  };
  TA.ui.select = function select({ options, value, onChange, title }) {
    const el = h('select', { class: 'select', title, onChange: () => onChange && onChange(el.value) },
      options.map((o) => h('option', { value: o.value, selected: o.value === value }, o.label)));
    return { el, set: (v) => { el.value = v; }, get: () => el.value, setOptions(opts, v) { TA.util.clear(el); opts.forEach((o) => el.appendChild(h('option', { value: o.value }, o.label))); el.value = v ?? ''; } };
  };
  TA.ui.searchInput = function searchInput({ placeholder = 'Buscar…', value = '', onInput, delay = 300 }) {
    const input = h('input', { class: 'input search', placeholder, value, onInput: TA.util.debounce(() => onInput && onInput(input.value.trim()), delay) });
    const el = h('span', { class: 'search-wrap' }, TA.ui.icon('search', 'sm'), input);
    return { el, input, set: (v) => { input.value = v; } };
  };
  TA.ui.check = function check({ label, checked, onChange }) {
    const input = h('input', { type: 'checkbox', checked: !!checked, onChange: () => onChange && onChange(input.checked) });
    return h('label', { class: 'check' }, input, label);
  };

  /* abas: items=[{id,label,count?}] */
  TA.ui.tabs = function tabs({ items, active, onChange }) {
    const els = items.map((it) => h('div', { class: ['tab', it.id === active && 'active'], onClick: () => set(it.id, true) },
      it.label, it.count !== undefined && it.count !== null ? h('span', { class: 'n' }, it.count) : null));
    const el = h('div', { class: 'tabs' }, els);
    function set(id, fire) { els.forEach((e, i) => e.classList.toggle('active', items[i].id === id)); active = id; if (fire && onChange) onChange(id); }
    return { el, set: (id) => set(id, false), get: () => active };
  };

  /* tabela: columns=[{key,label,render?(row,i)->Node|string, sortable?, align?:'r', width?, title?}] */
  TA.ui.table = function table({ columns, rows = [], onRowClick, sort, onSort, empty = 'Nada por aqui', rowId, selectedId, rowClass }) {
    const wrap = h('div', { class: 'table-wrap' });
    function render() {
      const head = h('tr', null, columns.map((c) => {
        const on = sort && sort.key === (c.sortKey || c.key);
        return h('th', {
          class: [c.sortable && 'sortable', c.align === 'r' && 'r'], style: c.width ? { width: c.width } : null, title: c.title,
          onClick: c.sortable && onSort ? () => onSort(c.sortKey || c.key, on && sort.order === 'desc' ? 'asc' : 'desc') : null,
        }, c.label, on ? h('span', { class: 'sort' }, sort.order === 'asc' ? '↑' : '↓') : null);
      }));
      const body = rows.map((row, i) => h('tr', {
        class: [onRowClick && 'clickable', rowId && selectedId !== undefined && selectedId !== null && rowId(row) === selectedId && 'sel', rowClass && rowClass(row)],
        onClick: onRowClick ? (e) => { if (!e.target.closest('a,button')) onRowClick(row, e); } : null,
      }, columns.map((c) => h('td', { class: c.align === 'r' ? 'r num' : '' }, c.render ? c.render(row, i) : (row[c.key] ?? '—')))));
      TA.util.clear(wrap);
      if (!rows.length) wrap.appendChild(TA.ui.empty(empty));
      else wrap.appendChild(h('table', { class: 't' }, h('thead', null, head), h('tbody', null, body)));
    }
    render();
    return { el: wrap, setRows(r) { rows = r; render(); }, setSort(s) { sort = s; render(); }, setSelected(id) { selectedId = id; render(); } };
  };

  /* paginação por offset */
  TA.ui.pager = function pager({ total, limit, offset, onChange }) {
    const from = total ? offset + 1 : 0, to = Math.min(total, offset + limit);
    return h('div', { class: 'pager' },
      h('span', null, `${TA.fmt.num(from)}–${TA.fmt.num(to)} de ${TA.fmt.num(total)}`), h('span', { class: 'spacer' }),
      h('button', { class: 'btn sm', disabled: offset <= 0, onClick: () => onChange(Math.max(0, offset - limit)) }, '← Anterior'),
      h('button', { class: 'btn sm', disabled: offset + limit >= total, onClick: () => onChange(offset + limit) }, 'Próxima →'));
  };

  /* ------------------------------------------------------------------ árvore JSON */
  TA.ui.jsonTree = function jsonTree(value, { expand = 1, maxString = 600 } = {}) {
    const root = h('div', { class: 'jt' });
    const isObj = (v) => v !== null && typeof v === 'object';
    function preview(v) {
      if (Array.isArray(v)) return `[${v.length}]`;
      return `{${Object.keys(v).length}}`;
    }
    function leaf(v) {
      if (v === null) return h('span', { class: 'z' }, 'null');
      if (typeof v === 'string') {
        if (v.length <= maxString) return h('span', { class: 's' }, JSON.stringify(v));
        const span = h('span', { class: 's' }, JSON.stringify(v.slice(0, maxString)) + '… ');
        span.appendChild(h('span', { class: 'more', onClick: () => { span.textContent = JSON.stringify(v); } }, `mostrar tudo (+${v.length - maxString})`));
        return span;
      }
      if (typeof v === 'number') return h('span', { class: 'n' }, String(v));
      if (typeof v === 'boolean') return h('span', { class: 'b' }, String(v));
      return h('span', null, String(v));
    }
    function node(key, v, depth) {
      const keyEl = key === null ? null : h('span', { class: 'k' }, typeof key === 'number' ? key : JSON.stringify(key), h('span', { class: 'dim' }, ': '));
      if (!isObj(v)) return h('div', { class: 'row-j' }, keyEl, leaf(v));
      const entries = Array.isArray(v) ? v.map((x, i) => [i, x]) : Object.entries(v);
      const open = Array.isArray(v) ? '[' : '{', close = Array.isArray(v) ? ']' : '}';
      const row = h('div', { class: 'row-j' });
      const tog = h('span', { class: 'tog' }, '▸');
      const kids = h('div', { class: 'kids hidden' });
      const sum = h('span', { class: 'dim' }, ` ${preview(v)}`);
      let built = false;
      function setOpen(o) {
        if (o && !built) { built = true; entries.forEach(([k, x]) => kids.appendChild(node(k, x, depth + 1))); }
        kids.classList.toggle('hidden', !o);
        tog.textContent = o ? '▾' : '▸';
        sum.classList.toggle('hidden', o);
      }
      tog.addEventListener('click', () => setOpen(kids.classList.contains('hidden')));
      row.append(tog, keyEl || '', h('span', { class: 'dim' }, open), sum, kids, h('span', { class: 'dim' }, close));
      if (!entries.length) { tog.textContent = ''; sum.textContent = ''; row.lastChild.textContent = close; }
      else setOpen(depth < expand);
      return row;
    }
    root.appendChild(node(null, value, 0));
    return root;
  };

  /* ------------------------------------------------------------------ toast e tooltip */
  let toasts;
  TA.ui.toast = function toast(text, kind) {
    if (!toasts) { toasts = h('div', { class: 'toasts' }); document.body.appendChild(toasts); }
    const t = h('div', { class: ['toast', kind] }, text);
    toasts.appendChild(t);
    setTimeout(() => t.remove(), 2600);
  };

  let tipEl;
  function tipShow(e, content) {
    if (!tipEl) { tipEl = h('div', { class: 'tip hidden' }); document.body.appendChild(tipEl); }
    TA.util.clear(tipEl);
    tipEl.appendChild(typeof content === 'string' ? document.createTextNode(content) : content);
    tipEl.classList.remove('hidden');
    tipMove(e);
  }
  function tipMove(e) {
    if (!tipEl) return;
    const pad = 14, r = tipEl.getBoundingClientRect();
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + r.width > window.innerWidth - 8) x = e.clientX - r.width - pad;
    if (y + r.height > window.innerHeight - 8) y = e.clientY - r.height - pad;
    tipEl.style.left = Math.max(4, x) + 'px'; tipEl.style.top = Math.max(4, y) + 'px';
  }
  function tipHide() { if (tipEl) tipEl.classList.add('hidden'); }
  /** tooltip que segue o mouse; `content` = string, Node, ou função (evento) -> string|Node */
  TA.ui.tip = function tip(el, content) {
    el.addEventListener('mouseenter', (e) => tipShow(e, typeof content === 'function' ? content(e) : content));
    el.addEventListener('mousemove', (e) => { if (typeof content === 'function') { tipShow(e, content(e)); } else tipMove(e); });
    el.addEventListener('mouseleave', tipHide);
    return el;
  };
  TA.ui.tipHide = tipHide;

  /* ------------------------------------------------------------------ painel dividido redimensionável (esquerda fixa + direita flexível) */
  TA.ui.split = function split({ left, right, width = 380, min = 220, max = 760, key }) {
    let w = key ? TA.util.store.get('split.' + key, width) : width;
    const l = h('div', { class: 'pane', style: { width: w + 'px', flex: 'none' } }, left);
    const r = h('div', { class: 'pane grow' }, right);
    const bar = h('div', { class: 'splitter' });
    bar.addEventListener('mousedown', (e) => {
      e.preventDefault(); bar.classList.add('drag');
      const x0 = e.clientX, w0 = w;
      const move = (ev) => { w = TA.util.clamp(w0 + ev.clientX - x0, min, max); l.style.width = w + 'px'; };
      const up = () => { bar.classList.remove('drag'); document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); if (key) TA.util.store.set('split.' + key, w); };
      document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
    });
    return h('div', { class: 'split' }, l, bar, r);
  };
})();
