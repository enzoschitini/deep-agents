/* Trace view (#/runs/:id): cabeçalho do run, abas e a árvore/waterfall de spans com o detalhe do span ao lado.
   Classes CSS com prefixo `.tv-` (src/css/50_trace.css). Depende de TA.spanDetail (72_span_detail.js) e TA.runTabs (76_run_tabs.js),
   ambos opcionais: se faltarem, mostra um fallback mínimo. */
(function () {
  const h = TA.h;
  const ROW_H = 28;      // altura de cada linha da árvore (igual ao CSS)
  const HEAD_H = 26;     // altura da régua de tempo (igual ao CSS)
  const OVERSCAN = 10;

  const TABS = [
    { id: 'trace', label: 'Trace' },
    { id: 'conversation', label: 'Conversa' },
    { id: 'events', label: 'Eventos' },
    { id: 'sources', label: 'Fontes' },
    { id: 'errors', label: 'Erros' },
    { id: 'files', label: 'Arquivos JSON' },
    { id: 'config', label: 'Config & prompt' },
  ];
  const KIND_COLOR = {
    llm: '--k-llm', tool: '--k-tool', chain: '--k-chain', subagent: '--k-subagent', skill: '--k-skill', file: '--k-file',
    todos: '--k-todos', code_eval: '--k-code', async_task: '--k-subagent', summarization: '--k-chain',
  };
  const kcolor = (k) => `var(${KIND_COLOR[k] || '--k-chain'})`;
  const num = (x) => (typeof x === 'number' && isFinite(x) ? x : null);
  const raf = (fn) => (window.requestAnimationFrame ? window.requestAnimationFrame(fn) : setTimeout(fn, 16));

  /* cache curto do último trace carregado (navegar entre spans do mesmo run remonta a view) */
  const CACHE = { id: null, at: 0, data: null };

  /* ------------------------------------------------------------------ dados do run */
  function modelOf(run) {
    const m = run && run.model;
    if (!m) return null;
    if (typeof m === 'string') return m;
    return m.spec || m.model_id || (Array.isArray(m.models_used) && m.models_used[0]) || null;
  }
  function modelsUsed(run) {
    const m = run && run.model;
    const used = m && typeof m === 'object' && Array.isArray(m.models_used) ? m.models_used : [];
    const main = modelOf(run);
    return Array.from(new Set([main, ...used].filter(Boolean)));
  }
  function tot(run, key) {
    const t = run && run.totals;
    const v = t && t[key] !== undefined && t[key] !== null ? t[key] : run && run[key];
    return v === undefined || v === null ? null : v;
  }
  function userMessage(run) {
    return (run && ((run.input && run.input.user_message) || run.user_message)) || '';
  }
  function ttftOf(run) {
    const tm = (run && run.timing) || {};
    return num(run && run.ttft_s) ?? num(tm.time_to_first_llm_token_s) ?? num(tm.time_to_first_response_delta_s);
  }
  const isPartial = (run) => !!run && (run.status === 'running' || run.status === 'unfinished');

  /* ------------------------------------------------------------------ preparo dos spans */
  function kindOf(s, b) {
    if (s.type === 'llm') return 'llm';
    if (s.type === 'tool') {
      if (b.kind && b.kind !== 'tool' && KIND_COLOR[b.kind]) return b.kind;
      if (s.name === 'task' || b.subagent_type) return 'subagent';
      return 'tool';
    }
    return 'chain';
  }
  function labelOf(s, b, kind, sub) {
    if (kind === 'llm') return b.model || s.name || 'LLM';
    if (kind === 'subagent' || kind === 'async_task') return sub || b.name || s.name || 'subagent';
    if (s.type === 'tool') return b.name || s.name || 'tool';
    return s.name || 'chain';
  }

  function prepare(data) {
    const run = data.run || {};
    const spans = Array.isArray(data.spans) ? data.spans : [];
    const recs = new Map();
    for (const s of spans) {
      if (!s || !s.span_id) continue;
      const b = s.brief || {};
      const kind = kindOf(s, b);
      const sub = b.subagent_type || null;
      const off = num(s.offset_s) ?? num(s.start_offset_s) ?? 0;
      let dur = num(s.duration_s);
      const open = dur === null && (s.status === 'running' || s.status === 'unfinished' || !s.ended_at);
      if (dur === null && !open) dur = 0;
      const label = labelOf(s, b, kind, sub);
      recs.set(s.span_id, {
        id: s.span_id, s, b, type: s.type, kind, sub, label, off, dur, open, seq: num(s.seq) ?? 0,
        err: s.status === 'error' || !!s.error, kids: [], parent: null, isRoot: false,
        search: [label, s.name, b.name, sub, b.model, b.purpose, kind, (b.requested_tools || []).join(' ')].filter(Boolean).join(' ').toLowerCase(),
      });
    }
    const byTime = (a, b2) => (a.off - b2.off) || (a.seq - b2.seq);
    const rootRecs = [];
    recs.forEach((r) => {
      const p = r.s.parent_id ? recs.get(r.s.parent_id) : null;
      if (p && p !== r) { r.parent = p; p.kids.push(r); } else { r.isRoot = true; rootRecs.push(r); }
    });
    rootRecs.sort(byTime);
    recs.forEach((r) => r.kids.sort(byTime));

    // agregados por subárvore (LLM, tools, subagents, erros), para o resumo de grupos recolhidos
    const seen = new Set();
    function agg(r) {
      const self = {
        llm: r.kind === 'llm' ? 1 : 0,
        tool: r.type === 'tool' && r.kind !== 'subagent' && r.kind !== 'async_task' ? 1 : 0,
        sub: r.kind === 'subagent' || r.kind === 'async_task' ? 1 : 0,
        err: r.err ? 1 : 0,
      };
      const total = { ...self };
      if (!seen.has(r.id)) {
        seen.add(r.id);
        r.kids.forEach((k) => { const a = agg(k); total.llm += a.llm; total.tool += a.tool; total.sub += a.sub; total.err += a.err; });
      }
      r.dsc = { llm: total.llm - self.llm, tool: total.tool - self.tool, sub: total.sub - self.sub, err: total.err - self.err };
      return total;
    }
    rootRecs.forEach(agg);

    let maxEnd = 0;
    recs.forEach((r) => { maxEnd = Math.max(maxEnd, r.off + (r.dur || 0)); });
    const rd = num(run.duration_s) ?? num(run.timing && run.timing.wall_time_s);
    const total = Math.max(rd || 0, maxEnd, 0.001);
    let spanErrors = 0;
    recs.forEach((r) => { if (r.err) spanErrors += 1; });
    return { run, data, recs, rootRecs, total, spanErrors };
  }

  /* chains internos (middlewares e nós do LangGraph) que só atrapalham a leitura */
  const NOISE_SUFFIX = /\.(a?before_agent|a?before_model|a?after_model|a?after_agent|a?wrap_model_call|a?wrap_tool_call)$/i;
  const NOISE_NAME = /^(Runnable\w*|ChannelWrite.*|ChannelRead.*|branch:.*|_write|_route|__start__|__end__|should_continue|tools_condition)$/;
  function isNoise(r) {
    if (r.type !== 'chain' || r.isRoot || r.err) return false;
    const n = r.s.name || '';
    if (NOISE_SUFFIX.test(n) || NOISE_NAME.test(n)) return true;
    if ((n === 'model' || n === 'tools' || n === 'agent') && r.kids.length <= 1) return true;
    const p = r.parent;
    if (p && (p.kind === 'subagent' || p.kind === 'async_task') && (n === p.label || n === p.sub)) return true;
    return false;
  }

  /** árvore visível: chains escondidos têm os filhos promovidos ao pai */
  function buildVisible(P, showAll) {
    const nodes = new Map();
    const roots = [];
    let hidden = 0;
    function visit(rec, parentNode) {
      if (!showAll && isNoise(rec)) { hidden += 1; rec.kids.forEach((k) => visit(k, parentNode)); return; }
      const node = { rec, id: rec.id, parent: parentNode, children: [], depth: parentNode ? parentNode.depth + 1 : 0 };
      nodes.set(rec.id, node);
      (parentNode ? parentNode.children : roots).push(node);
      rec.kids.forEach((k) => visit(k, node));
    }
    P.rootRecs.forEach((r) => visit(r, null));
    const byTime = (a, b) => (a.rec.off - b.rec.off) || (a.rec.seq - b.rec.seq);
    roots.sort(byTime);
    nodes.forEach((n) => n.children.sort(byTime));
    return { nodes, roots, hidden };
  }

  /* ------------------------------------------------------------------ pequenos blocos */
  function hl(text, q) {
    if (!q) return text;
    const i = text.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return text;
    return [text.slice(0, i), h('mark', { class: 'tv-mark' }, text.slice(i, i + q.length)), text.slice(i + q.length)];
  }

  const iconCache = {};
  function kindIconCached(kind) {
    if (!iconCache[kind]) {
      const i = TA.ui.kindIcon(kind);
      i.style.color = kcolor(kind);
      i.classList.add('tv-ico');
      iconCache[kind] = i;
    }
    return iconCache[kind].cloneNode(true);
  }

  function groupSummary(rec) {
    const d = rec.dsc || {};
    const parts = [];
    if (d.llm) parts.push(`${d.llm} LLM`);
    if (d.tool) parts.push(`${d.tool} ${d.tool === 1 ? 'tool' : 'tools'}`);
    if (d.sub) parts.push(`${d.sub} ${d.sub === 1 ? 'subagent' : 'subagents'}`);
    return parts.join(' · ');
  }

  function tipContent(r, P) {
    const b = r.b || {};
    const lines = [`${TA.ui.kindMeta(r.kind)[1]} · ${TA.util.statusLabel(r.s.status)}`];
    lines.push(`início +${TA.fmt.dur(r.off)}  ·  duração ${r.open ? 'em andamento' : TA.fmt.dur(r.dur)}`);
    if (r.kind === 'llm') {
      if (b.input_tokens !== undefined || b.output_tokens !== undefined) lines.push(`tokens ${TA.fmt.num(b.input_tokens)} → ${TA.fmt.num(b.output_tokens)}`);
      if (b.cost_usd !== undefined && b.cost_usd !== null) lines.push(`custo ${TA.fmt.cost(b.cost_usd)}`);
      if (num(b.ttft_s) !== null) lines.push(`TTFT ${TA.fmt.dur(b.ttft_s)}`);
    }
    if (r.s.agent) lines.push(`agente ${r.s.agent}`);
    if (r.s.error) lines.push(`erro: ${TA.fmt.trunc(typeof r.s.error === 'string' ? r.s.error : (r.s.error.message || TA.util.pretty(r.s.error)), 200)}`);
    lines.push(`${TA.fmt.pct(r.dur !== null ? r.dur / P.total : (P.total - r.off) / P.total, 0)} do run`);
    return h('div', null, h('b', null, r.label), '\n' + lines.join('\n'));
  }

  /* ------------------------------------------------------------------ árvore (waterfall) */
  function makeTree(P, st, hooks) {
    let vis = buildVisible(P, st.showAll);
    let rows = [];
    let rowIndex = new Map();
    let matchSet = null;
    let hitSet = new Set();
    let pathSet = new Set();
    const rendered = new Map();
    let scheduled = false;

    const countEl = h('span', { class: 'tv-count muted xs' });
    const hiddenLbl = h('span', null);
    const empty = h('div', { class: 'tv-tree-empty hidden' }, 'Nenhum span corresponde à busca');
    const inner = h('div', { class: 'tv-inner' });

    const search = TA.ui.searchInput({
      placeholder: 'Buscar span…', delay: 150,
      onInput: (v) => { st.q = v; applyFilter(); },
    });
    const btnExpand = h('button', { class: 'btn sm icon', title: 'Expandir tudo', 'aria-label': 'Expandir tudo', onClick: () => { st.collapsed.clear(); reflow(true); } }, TA.ui.icon('layers'));
    const btnCollapse = h('button', { class: 'btn sm icon', title: 'Recolher tudo (mantém a raiz aberta)', 'aria-label': 'Recolher tudo', onClick: () => collapseAll() }, TA.ui.icon('chevR'));
    const allChk = TA.ui.check({
      label: hiddenLbl, checked: st.showAll,
      onChange: (v) => { st.showAll = v; hooks.onShowAll(v); rebuild(); },
    });
    allChk.title = 'Mostra também os chains de middleware e os nós internos do LangGraph';

    const legend = h('div', { class: 'tv-legend' },
      [['llm', 'LLM'], ['tool', 'Tool'], ['subagent', 'Subagent'], ['chain', 'Chain']].map(([k, l]) =>
        h('span', { class: 'tv-leg' }, h('i', { class: 'tv-leg-dot', style: { background: kcolor(k) } }), l)),
      h('span', { class: 'tv-leg' }, h('i', { class: 'tv-leg-dot', style: { background: 'var(--err)' } }), 'Erro'),
      h('span', { class: 'tv-leg' }, h('i', { class: 'tv-leg-dot tv-leg-open' }), 'Sem fim'));

    /* régua de tempo */
    const ticks = [0, 1, 2, 3, 4].map((i) => h('span', { class: ['tv-tick', 'tv-t' + i], style: { left: (i * 25) + '%' } },
      h('span', null, i === 0 ? '0' : TA.fmt.dur(P.total * i / 4))));
    const ruler = h('div', { class: 'tv-ruler' },
      h('div', { class: 'tv-name tv-ruler-name' }, 'Span'),
      h('div', { class: 'tv-dur' }, 'Duração'),
      h('div', { class: 'tv-barcol tv-ruler-bar' }, ticks));

    const scroller = h('div', { class: 'tv-scroll', tabindex: '0', role: 'tree', 'aria-label': 'Árvore de spans' }, ruler, inner, empty);

    const el = h('div', { class: 'tv-tree' },
      h('div', { class: 'tv-tools' },
        h('div', { class: 'tv-tools-row' }, search.el, btnExpand, btnCollapse),
        h('div', { class: 'tv-tools-row tv-tools-sub' }, allChk, h('span', { class: 'spacer' }), countEl)),
      legend, scroller);

    /* ---- cálculo das linhas ---- */
    function computeMatch() {
      const q = (st.q || '').toLowerCase();
      hitSet = new Set();
      if (!q) { matchSet = null; return; }
      matchSet = new Set();
      vis.nodes.forEach((n) => {
        if (n.rec.search.includes(q)) {
          hitSet.add(n.id);
          for (let x = n; x && !matchSet.has(x); x = x.parent) matchSet.add(x);
        }
      });
    }
    function computePath() {
      pathSet = new Set();
      const n = vis.nodes.get(st.sel);
      for (let x = n && n.parent; x; x = x.parent) pathSet.add(x.id);
    }
    function flatten() {
      rows = [];
      const walk = (n) => {
        if (matchSet && !matchSet.has(n)) return;
        rows.push(n);
        if (n.children.length && (matchSet || !st.collapsed.has(n.id))) n.children.forEach(walk);
      };
      vis.roots.forEach(walk);
      rowIndex = new Map();
      rows.forEach((n, i) => rowIndex.set(n.id, i));
    }
    function updateLabels() {
      TA.util.clear(hiddenLbl);
      hiddenLbl.appendChild(document.createTextNode(vis.hidden || st.showAll ? `Mostrar chains internos${st.showAll ? '' : ` (${vis.hidden} ocultos)`}` : 'Mostrar chains internos'));
      const n = vis.nodes.size;
      countEl.textContent = matchSet ? `${rows.length} de ${n} spans` : `${n} spans`;
      empty.classList.toggle('hidden', rows.length > 0);
    }
    function reflow(full) {
      computeMatch(); computePath(); flatten(); updateLabels();
      paint(full !== false);
    }

    /* ---- desenho virtualizado ---- */
    function makeRow(n, i) {
      const r = n.rec;
      const hasKids = n.children.length > 0;
      const open = hasKids && (matchSet ? true : !st.collapsed.has(n.id));
      const selected = n.id === st.sel;
      const tog = hasKids
        ? h('button', { class: 'tv-tog', tabindex: '-1', 'aria-label': open ? 'Recolher' : 'Expandir', dataset: { act: 'toggle' } }, TA.ui.icon(open ? 'chevD' : 'chevR', 'sm'))
        : h('span', { class: 'tv-tog tv-tog-empty' });
      const b = r.b || {};
      const pills = [];
      if (r.kind === 'llm' && b.purpose === 'summary') pills.push(h('span', { class: 'tv-pill tv-pill-sum' }, 'resumo'));
      if (r.kind === 'llm' && (num(b.input_tokens) !== null || num(b.output_tokens) !== null)) {
        pills.push(h('span', { class: 'tv-tok num', title: `Tokens: ${TA.fmt.num(b.input_tokens)} entrada → ${TA.fmt.num(b.output_tokens)} saída` },
          `${TA.fmt.compact(b.input_tokens)}→${TA.fmt.compact(b.output_tokens)}`));
      }
      if (r.err) pills.push(h('span', { class: 'tv-pill tv-pill-err' }, 'erro'));
      else if (r.open) pills.push(h('span', { class: 'tv-pill tv-pill-run' }, r.s.status === 'running' ? 'rodando' : 'sem fim'));
      if (hasKids && !open) {
        const sum = groupSummary(r);
        if (sum) pills.push(h('span', { class: 'tv-grp' }, sum));
        if (r.dsc && r.dsc.err) pills.push(h('span', { class: 'tv-pill tv-pill-err' }, `${r.dsc.err} ${r.dsc.err === 1 ? 'erro' : 'erros'}`));
      }

      let left = Math.min(100, Math.max(0, r.off / P.total * 100));
      const span = r.open ? Math.max(0, P.total - r.off) : (r.dur || 0);
      const w = Math.max(0, Math.min(100 - left, span / P.total * 100));
      const bar = h('div', { class: ['tv-bar', r.open && 'tv-bar-open', r.err && 'tv-bar-err'], style: { left: left + '%', width: w + '%' } });
      const barcol = h('div', { class: 'tv-barcol' }, bar);
      TA.ui.tip(barcol, () => tipContent(r, P));

      return h('div', {
        class: ['tv-row', 'tv-k-' + r.kind, selected && 'tv-sel', !selected && pathSet.has(n.id) && 'tv-path', r.err && 'tv-err'],
        role: 'treeitem', id: 'tv-r-' + n.id, 'aria-level': String(n.depth + 1), 'aria-selected': selected ? 'true' : 'false',
        'aria-expanded': hasKids ? (open ? 'true' : 'false') : null,
        dataset: { id: n.id },
        style: { top: (i * ROW_H) + 'px', '--kc': kcolor(r.kind) },
      },
      h('div', { class: 'tv-name' },
        h('span', { class: 'tv-indent', style: { width: (n.depth * 14) + 'px' } }),
        tog, kindIconCached(r.kind),
        h('span', { class: ['tv-label', r.kind === 'chain' && 'tv-label-chain'], title: r.s.name && r.s.name !== r.label ? r.s.name : null }, hl(r.label, hitSet.has(n.id) ? st.q : '')),
        pills),
      h('div', { class: ['tv-dur', 'num', r.type === 'chain' && 'tv-dur-chain'] }, r.open ? '…' : TA.fmt.dur(r.dur)),
      barcol);
    }

    function paint(full) {
      const vh = scroller.clientHeight || 600;
      inner.style.height = (rows.length * ROW_H) + 'px';
      const top = Math.max(0, scroller.scrollTop - HEAD_H);
      const a = Math.max(0, Math.floor(top / ROW_H) - OVERSCAN);
      const b = Math.min(rows.length, Math.ceil((top + vh) / ROW_H) + OVERSCAN);
      if (full) { TA.util.clear(inner); rendered.clear(); }
      else {
        rendered.forEach((node, i) => { if (i < a || i >= b) { node.remove(); rendered.delete(i); } });
      }
      const frag = document.createDocumentFragment();
      for (let i = a; i < b; i++) {
        if (!rendered.has(i)) { const row = makeRow(rows[i], i); rendered.set(i, row); frag.appendChild(row); }
      }
      inner.appendChild(frag);
      if (st.sel && rowIndex.has(st.sel)) scroller.setAttribute('aria-activedescendant', 'tv-r-' + st.sel);
    }

    function onScroll() {
      if (scheduled) return;
      scheduled = true;
      raf(() => { scheduled = false; paint(false); });
    }
    scroller.addEventListener('scroll', onScroll);
    if (typeof ResizeObserver !== 'undefined') {
      try { new ResizeObserver(() => onScroll()).observe(scroller); } catch (e) { /* sem observer */ }
    }

    function scrollToId(id, center) {
      const i = rowIndex.get(id);
      if (i === undefined) return;
      const y = HEAD_H + i * ROW_H;
      const vh = scroller.clientHeight || 600;
      if (center) scroller.scrollTop = Math.max(0, y - vh / 2 + ROW_H / 2);
      else if (y < scroller.scrollTop + HEAD_H) scroller.scrollTop = Math.max(0, y - HEAD_H);
      else if (y + ROW_H > scroller.scrollTop + vh) scroller.scrollTop = y + ROW_H - vh;
      paint(false);
    }

    /* ---- ações ---- */
    function applyFilter() {
      reflow(true);
      scroller.scrollTop = 0;
      paint(false);
      if (!st.q) scrollToId(st.sel, true);
    }
    function collapseAll() {
      st.collapsed.clear();
      vis.nodes.forEach((n) => { if (n.children.length && n.parent) st.collapsed.add(n.id); });
      // se a seleção ficou escondida, sobe para o ancestral visível
      const sel = vis.nodes.get(st.sel);
      reflow(true);
      if (sel && !rowIndex.has(sel.id)) {
        let x = sel;
        while (x && !rowIndex.has(x.id)) x = x.parent;
        if (x) select(x.id, { scroll: true, user: true });
      }
    }
    function toggle(node) {
      if (!node.children.length || matchSet) return;
      const collapsing = !st.collapsed.has(node.id);
      if (collapsing) st.collapsed.add(node.id); else st.collapsed.delete(node.id);
      reflow(true);
      if (collapsing) {
        const sel = vis.nodes.get(st.sel);
        for (let x = sel && sel.parent; x; x = x.parent) {
          if (x === node) { select(node.id, { scroll: false, user: true }); break; }
        }
      }
    }
    function select(id, opts) {
      opts = opts || {};
      const node = vis.nodes.get(id);
      if (!node) return false;
      const changed = st.sel !== id;
      st.sel = id;
      for (let p = node.parent; p; p = p.parent) st.collapsed.delete(p.id);
      reflow(true);
      if (opts.scroll !== false) scrollToId(id, opts.center);
      if (changed || opts.force) hooks.onSelect(id, opts);
      return true;
    }
    function rebuild() {
      vis = buildVisible(P, st.showAll);
      let sel = vis.nodes.has(st.sel) ? st.sel : null;
      if (!sel && st.sel) {
        for (let r = P.recs.get(st.sel); r && !sel; r = r.parent) if (vis.nodes.has(r.id)) sel = r.id;
      }
      if (!sel && vis.roots[0]) sel = vis.roots[0].id;
      const changed = sel !== st.sel;
      st.sel = sel;
      reflow(true);
      if (sel) scrollToId(sel, true);
      if (changed && sel) hooks.onSelect(sel, { user: true });
    }

    /* ---- mouse e teclado ---- */
    scroller.addEventListener('click', (e) => {
      const rowEl = e.target && e.target.closest ? e.target.closest('.tv-row') : null;
      if (!rowEl) return;
      const node = vis.nodes.get(rowEl.dataset.id);
      if (!node) return;
      if (e.target.closest('[data-act="toggle"]')) { toggle(node); return; }
      select(node.id, { scroll: false, user: true });
    });
    scroller.addEventListener('dblclick', (e) => {
      const rowEl = e.target && e.target.closest ? e.target.closest('.tv-row') : null;
      const node = rowEl && vis.nodes.get(rowEl.dataset.id);
      if (node) toggle(node);
    });
    scroller.addEventListener('keydown', (e) => {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const i = rowIndex.has(st.sel) ? rowIndex.get(st.sel) : -1;
      const cur = i >= 0 ? rows[i] : null;
      const go = (idx) => {
        if (!rows.length) return;
        const n = rows[TA.util.clamp(idx, 0, rows.length - 1)];
        if (n) select(n.id, { user: true, key: true });
      };
      let handled = true;
      switch (e.key) {
        case 'ArrowDown': go(i + 1); break;
        case 'ArrowUp': go(i < 0 ? 0 : i - 1); break;
        case 'PageDown': go(i + 10); break;
        case 'PageUp': go(i - 10); break;
        case 'Home': go(0); break;
        case 'End': go(rows.length - 1); break;
        case 'ArrowLeft':
          if (cur && cur.children.length && !matchSet && !st.collapsed.has(cur.id)) toggle(cur);
          else if (cur && cur.parent && rowIndex.has(cur.parent.id)) go(rowIndex.get(cur.parent.id));
          break;
        case 'ArrowRight':
          if (cur && cur.children.length) {
            if (!matchSet && st.collapsed.has(cur.id)) toggle(cur);
            else go(i + 1);
          }
          break;
        case 'Enter': hooks.focusDetail(); break;
        default: handled = false;
      }
      if (handled) e.preventDefault();
    });

    /* ---- inicialização ---- */
    reflow(true);

    return {
      el, select, rebuild,
      layout() { paint(false); scrollToId(st.sel, false); },
      initial(id) { // seleciona sem rolar para trás e centraliza
        if (id && vis.nodes.has(id)) select(id, { center: true, scroll: true, force: true });
        else if (vis.roots[0]) select(vis.roots[0].id, { center: false, scroll: true, force: true });
      },
      isVisible: (id) => vis.nodes.has(id),
      focus() { scroller.focus(); },
    };
  }

  /* ------------------------------------------------------------------ cabeçalho do run */
  function metric(label, value, { kind, title, sub, onClick } = {}) {
    const tag = onClick ? 'button' : 'div';
    return h(tag, { class: ['tv-m', kind && 'tv-m-' + kind, onClick && 'tv-m-click'], title, onClick, type: onClick ? 'button' : null },
      h('span', { class: 'tv-m-l' }, label),
      h('span', { class: 'tv-m-v num' }, value),
      sub ? h('span', { class: 'tv-m-s' }, sub) : null);
  }
  function metaItem(label, value) {
    if (value === null || value === undefined || value === '' || value === false) return null;
    return h('span', { class: 'tv-mi' }, h('span', { class: 'tv-mi-l' }, label), h('span', { class: 'tv-mi-v' }, value));
  }

  function buildHead(P, hooks) {
    const run = P.run;
    const msg = String(userMessage(run) || '').trim();
    const firstLine = (msg.split('\n').find((l) => l.trim()) || '').trim();
    const expandable = msg.length > firstLine.length || msg.length > 140;
    let expanded = false;
    const msgEl = h('div', { class: 'tv-msg' }, msg ? firstLine : h('span', { class: 'muted' }, '(sem mensagem do usuário)'));
    const expBtn = expandable ? h('button', { class: 'btn sm ghost', type: 'button', onClick: () => {
      expanded = !expanded;
      TA.util.clear(msgEl); msgEl.appendChild(document.createTextNode(expanded ? msg : firstLine));
      msgEl.classList.toggle('tv-msg-open', expanded);
      expBtn.textContent = expanded ? 'Recolher' : 'Expandir';
    } }, 'Expandir') : null;

    const foldKey = 'tv.headFold';
    let folded = !!TA.util.store.get(foldKey, false);
    const foldBtn = h('button', { class: 'btn sm icon ghost', type: 'button', title: 'Mostrar/ocultar detalhes do cabeçalho', 'aria-label': 'Alternar detalhes' });
    const paintFold = () => { TA.util.clear(foldBtn); foldBtn.appendChild(TA.ui.icon(folded ? 'chevD' : 'sortUp', 'sm')); };

    const sid = run.session_id;
    const models = modelsUsed(run);
    const cfg = run.config_hash;
    const meta = h('div', { class: 'tv-meta' },
      metaItem('Quando', run.started_at ? h('span', { title: TA.fmt.datetime(run.started_at) }, `${TA.fmt.datetime(run.started_at)} (${TA.fmt.rel(run.started_at)})`) : null),
      metaItem('Duração', num(run.duration_s) !== null ? TA.fmt.dur(run.duration_s) : null),
      metaItem(models.length > 1 ? 'Modelos' : 'Modelo', models.length ? models.map((m) => h('span', { class: 'chip mono' }, m)) : null),
      metaItem('Sessão', sid ? [TA.router.link('sessions/' + sid, null, TA.fmt.short(sid, 12)), run.turn !== undefined && run.turn !== null ? ` · turno ${run.turn}` : ''] : null),
      metaItem('Origem', run.origin ? TA.ui.badge(run.origin, 'info') : null),
      metaItem('Config', cfg ? TA.router.link('prompts/' + cfg, null, TA.fmt.short(cfg, 8)) : null),
      metaItem('Run', h('span', { class: 'mono' }, TA.fmt.short(run.run_id || '', 12), TA.ui.copyBtn(run.run_id || ''))));

    const inTok = tot(run, 'input_tokens'), outTok = tot(run, 'output_tokens'), cache = tot(run, 'cache_read_tokens');
    const reasoning = tot(run, 'reasoning_tokens');
    const errs = Math.max(Number(tot(run, 'errors')) || 0, P.spanErrors);
    const nSub = tot(run, 'subagent_calls');
    const dyn = tot(run, 'dynamic_subagents');
    const tm = run.timing || {};
    const chips = h('div', { class: 'tv-chips' },
      metric('Latência', TA.fmt.dur(num(run.duration_s) ?? num(tm.wall_time_s)), {
        title: `LLM ${TA.fmt.dur(num(tm.llm_time_s))} · tools ${TA.fmt.dur(num(tm.tool_time_s))}`,
        sub: num(tm.llm_time_s) !== null ? `LLM ${TA.fmt.dur(tm.llm_time_s)}` : null }),
      metric('TTFT', TA.fmt.dur(ttftOf(run)), { title: 'Tempo até o primeiro token' }),
      metric('Tokens', `${TA.fmt.compact(inTok)} → ${TA.fmt.compact(outTok)}`, {
        title: `Entrada ${TA.fmt.num(inTok)} · saída ${TA.fmt.num(outTok)} · cache lido ${TA.fmt.num(cache)}${reasoning ? ' · raciocínio ' + TA.fmt.num(reasoning) : ''}`,
        sub: cache ? `cache ${TA.fmt.compact(cache)}` : 'entrada → saída' }),
      metric('Custo', TA.fmt.cost(tot(run, 'cost_usd'))),
      metric('Chamadas LLM', TA.fmt.num(tot(run, 'llm_calls')), {
        title: `Principal ${TA.fmt.num(tot(run, 'main_llm_calls'))} · subagents ${TA.fmt.num(tot(run, 'subagent_llm_calls'))} · resumo ${TA.fmt.num(tot(run, 'summary_llm_calls'))}` }),
      metric('Tools', TA.fmt.num(tot(run, 'tool_calls'))),
      metric('Subagents', TA.fmt.num(nSub), { title: dyn ? `${dyn} dinâmicos` : null }),
      metric('Erros', TA.fmt.num(errs), { kind: errs > 0 ? 'err' : null, onClick: errs > 0 ? () => hooks.showTab('errors') : null,
        title: errs > 0 ? 'Ver a aba de erros' : null }));

    const runErr = run.error && (run.error.message || run.error.type)
      ? h('div', { class: 'tv-runerr' }, TA.ui.icon('alert', 'sm'), h('b', null, `${run.error.type || 'Erro'}: `), TA.fmt.trunc(run.error.message || '', 400))
      : null;

    const details = h('div', { class: 'tv-details' }, meta, chips, runErr);
    const el = h('div', { class: 'tv-head' },
      h('div', { class: 'tv-title' }, TA.ui.statusBadge(run.status), msgEl, expBtn, foldBtn),
      details);
    const applyFold = () => { details.classList.toggle('hidden', folded); paintFold(); };
    foldBtn.addEventListener('click', () => { folded = !folded; TA.util.store.set(foldKey, folded); applyFold(); });
    applyFold();
    return el;
  }

  /* ------------------------------------------------------------------ fallback do detalhe do span */
  function fallbackDetail(rec, withNotice) {
    const s = rec.s;
    const err = s.error ? (typeof s.error === 'string' ? s.error : (s.error.message || TA.util.pretty(s.error))) : null;
    return h('div', { class: 'tv-fb' },
      withNotice ? h('div', { class: 'tv-note' }, 'Módulo de detalhe do span ainda não carregado: mostrando um resumo mínimo.') : null,
      h('div', { class: 'tv-fb-head' }, kindIconCached(rec.kind), h('h3', null, rec.label), TA.ui.statusBadge(s.status)),
      TA.ui.kv([
        ['Nome', s.name], ['Tipo', `${TA.ui.kindMeta(rec.kind)[1]} (${s.type || '—'})`], ['Agente', s.agent],
        ['Início', `+${TA.fmt.dur(rec.off)}`], ['Duração', rec.open ? 'em andamento' : TA.fmt.dur(rec.dur)], ['ID', h('span', { class: 'mono' }, s.span_id)],
      ]),
      err ? h('div', { class: 'tv-runerr' }, TA.ui.icon('alert', 'sm'), err) : null,
      TA.ui.card('Resumo (brief)', TA.ui.jsonTree(rec.b || {}, { expand: 2 })),
      TA.ui.card('Span (JSON)', TA.ui.jsonTree(s, { expand: 1 })));
  }

  /* ------------------------------------------------------------------ a view */
  TA.views.trace = {
    _t: { prepare, buildVisible, isNoise },   // exposto para testes
    mount(ctx) {
      const runId = ctx.params.id;
      const root = h('div', { class: 'tv-page' });
      ctx.el.appendChild(root);
      const validTab = (t) => (TABS.some((x) => x.id === t) ? t : 'trace');
      const st = { sel: ctx.query.span || null, showAll: ctx.query.all === '1', q: '', collapsed: new Set(), tab: validTab(ctx.query.tab) };
      let alive = true;
      let loadToken = 0;
      let pollTimer = null;
      let detailTimer = null;
      let detailToken = 0;
      let P = null;
      let tree = null;
      let detailHost = null;
      let panes = {};
      let mounted = new Set();
      let tabsCtl = null;

      ctx.crumbs([{ label: 'Traces', href: TA.router.hashFor('runs') }, { label: TA.fmt.short(runId) }]);
      const baseActions = () => [
        h('button', { class: 'btn sm', type: 'button', title: 'Copiar o link desta página', onClick: () => TA.util.copy(location.href) }, TA.ui.icon('link', 'sm'), 'Copiar link'),
        h('button', { class: 'btn sm', type: 'button', title: 'Copiar o ID do run', onClick: () => TA.util.copy(runId) }, TA.ui.icon('copy', 'sm'), 'Copiar ID'),
      ];
      ctx.actions(baseActions());

      /* ---- detalhe do span ---- */
      function loadDetail(id) {
        if (!detailHost || !P) return;
        const my = ++detailToken;
        TA.util.clear(detailHost);
        const rec = P.recs.get(id);
        if (!rec) { detailHost.appendChild(TA.ui.empty('Nenhum span selecionado', 'Escolha um span na árvore ao lado.')); return; }
        const host = h('div', { class: 'tv-detail-host' });
        detailHost.appendChild(host);
        const fail = (e) => { if (my === detailToken) { TA.util.clear(host); host.appendChild(TA.ui.error(e)); } };
        if (TA.spanDetail && typeof TA.spanDetail.render === 'function') {
          try {
            // links do detalhe (breadcrumbs, spans filhos, tool pedida) selecionam na árvore sem remontar a página;
            // se o span não está visível na árvore (chain interno escondido), cai para a troca de URL (remonta com all=1)
            const onSelect = (sid) => {
              if (tree && tree.select(sid, { user: true, center: true }) === true) return;
              const rec2 = P.recs.get(sid);
              location.hash = TA.router.hashFor('runs/' + runId, { span: sid, tab: st.tab && st.tab !== 'trace' ? st.tab : null, all: rec2 && isNoise(rec2) ? '1' : null });
            };
            const r = TA.spanDetail.render(host, { runId, spanId: id, trace: P.data, onSelect });
            if (r && typeof r.catch === 'function') r.catch(fail);
          } catch (e) { fail(e); }
        } else host.appendChild(fallbackDetail(rec, true));
      }

      /* ---- abas ---- */
      function mountTab(id) {
        if (id === 'trace' || mounted.has(id)) return;
        mounted.add(id);
        const el = panes[id];
        const fn = TA.runTabs && TA.runTabs[id];
        if (typeof fn !== 'function') { el.appendChild(TA.ui.empty('Módulo ainda não carregado', `A aba "${id}" depende de TA.runTabs.${id}.`)); return; }
        const fail = (e) => { TA.util.clear(el); el.appendChild(TA.ui.error(e)); };
        try {
          const r = fn(el, { runId, run: P.run, trace: P.data });
          if (r && typeof r.catch === 'function') r.catch(fail);
        } catch (e) { fail(e); }
      }
      function showTab(id, fromUser) {
        id = validTab(id);
        st.tab = id;
        if (tabsCtl) tabsCtl.set(id);
        TABS.forEach((t) => panes[t.id] && panes[t.id].classList.toggle('hidden', t.id !== id));
        if (id === 'trace') { if (tree) tree.layout(); } else mountTab(id);
        if (fromUser !== false) ctx.setQuery({ tab: id === 'trace' ? null : id });
      }

      /* ---- montagem da página para os dados carregados ---- */
      function render(data) {
        P = prepare(data);
        const run = P.run;
        mounted = new Set(); panes = {};
        TA.util.clear(root);

        // seleção inicial: o span pedido na URL (se for chain interno, liga "chains internos") ou a raiz
        const want = st.sel && P.recs.has(st.sel) ? st.sel : null;
        if (want && !st.showAll && isNoise(P.recs.get(want))) { st.showAll = true; ctx.setQuery({ all: '1' }); }
        st.sel = want;

        const hooks = {
          showTab: (id) => showTab(id, true),
          onShowAll: (v) => ctx.setQuery({ all: v ? '1' : null }),
          focusDetail: () => { if (detailHost) detailHost.focus(); },
          onSelect: (id, opts) => {
            if (opts && opts.user) ctx.setQuery({ span: id });
            clearTimeout(detailTimer);
            if (opts && opts.key) detailTimer = setTimeout(() => loadDetail(id), 140); else loadDetail(id);
          },
        };

        root.appendChild(buildHead(P, hooks));
        if (isPartial(run)) {
          root.appendChild(h('div', { class: 'tv-warn' }, TA.ui.icon('alert', 'sm'),
            h('span', null, run.status === 'running'
              ? 'Este run ainda está em andamento: os detalhes (spans, chamadas, eventos) só são gravados ao fim. Os dados abaixo podem estar incompletos.'
              : 'Este run foi gravado de forma parcial (incompleto): alguns spans podem não ter fim.'),
            h('span', { class: 'spacer' }),
            h('button', { class: 'btn sm', type: 'button', onClick: () => load(true) }, TA.ui.icon('refresh', 'sm'), 'Recarregar')));
        }

        const nErr = Math.max(Number(tot(run, 'errors')) || 0, P.spanErrors);
        const nSrc = run.output && num(run.output.n_sources);
        tabsCtl = TA.ui.tabs({
          items: TABS.map((t) => ({ id: t.id, label: t.label, count: t.id === 'errors' ? nErr : (t.id === 'sources' && nSrc ? nSrc : undefined) })),
          active: st.tab, onChange: (id) => showTab(id, true),
        });
        const errIdx = TABS.findIndex((t) => t.id === 'errors');
        const errTab = tabsCtl.el.children && tabsCtl.el.children[errIdx];
        if (errTab && nErr > 0) errTab.classList.add('tv-tab-err');
        root.appendChild(h('div', { class: 'tv-tabbar' }, tabsCtl.el));

        const body = h('div', { class: 'tv-body' });
        root.appendChild(body);

        // aba trace: árvore + detalhe
        detailHost = h('div', { class: 'tv-detail', tabindex: '-1' });
        if (!P.recs.size) {
          panes.trace = h('div', { class: 'tv-pane' }, TA.ui.empty('Este run não tem spans gravados',
            isPartial(run) ? 'Os spans só são gravados quando o run termina. Recarregue mais tarde.' : 'Nenhum span foi encontrado em spans.json.'));
          tree = null;
        } else {
          tree = makeTree(P, st, hooks);
          panes.trace = h('div', { class: 'tv-pane tv-pane-trace' },
            h('div', { class: 'tv-split' }, TA.ui.split({ left: tree.el, right: detailHost, width: 640, min: 380, max: 1200, key: 'trace' })));
        }
        body.appendChild(panes.trace);
        TABS.slice(1).forEach((t) => { panes[t.id] = h('div', { class: 'tv-pane tv-pane-doc hidden' }); body.appendChild(panes[t.id]); });

        showTab(st.tab, false);
        if (tree) tree.initial(want);

        // ações do topo
        const acts = baseActions();
        if (run.session_id) acts.push(h('a', { class: 'btn sm tv-act', href: TA.router.hashFor('sessions/' + run.session_id) }, TA.ui.icon('chat', 'sm'), 'Ver sessão'));
        ctx.actions(acts);

        clearInterval(pollTimer);
        if (run.status === 'running') pollTimer = setInterval(() => { if (alive) load(true, true); }, 5000);
      }

      /* ---- carga ---- */
      async function load(force, silent) {
        const my = ++loadToken;
        if (!silent) { TA.util.clear(root); root.appendChild(TA.ui.loading('Carregando o trace…')); }
        try {
          let data;
          if (!force && CACHE.id === runId && Date.now() - CACHE.at < 30000 && CACHE.data) data = CACHE.data;
          else {
            data = await TA.api.trace(runId);
            if (data && data.run && !isPartial(data.run)) { CACHE.id = runId; CACHE.at = Date.now(); CACHE.data = data; } else CACHE.id = null;
          }
          if (!alive || my !== loadToken) return;
          if (!data) throw new Error('Resposta vazia do servidor');
          if (silent && P && data.run && P.run.status === data.run.status && P.recs.size === (data.spans || []).length) return; // nada mudou
          render(data);
        } catch (e) {
          if (!alive || my !== loadToken) return;
          clearInterval(pollTimer);
          TA.util.clear(root);
          root.appendChild(TA.ui.error(e));
          root.appendChild(h('div', { class: 'tv-retry' }, h('button', { class: 'btn', type: 'button', onClick: () => load(true) }, TA.ui.icon('refresh', 'sm'), 'Tentar de novo')));
        }
      }

      const onResize = TA.util.debounce(() => { if (tree && st.tab === 'trace') tree.layout(); }, 120);
      window.addEventListener('resize', onResize);
      ctx.onRefresh(() => load(true));
      load(false);

      return function cleanup() {
        alive = false;
        clearInterval(pollTimer); clearTimeout(detailTimer);
        window.removeEventListener('resize', onResize);
      };
    },
  };
})();
