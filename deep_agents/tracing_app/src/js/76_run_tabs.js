/* Abas secundárias do detalhe de um run: conversa, eventos, fontes, erros, arquivos e configuração.
   API: TA.runTabs.<aba>(el, {runId, run, trace}) -> Promise (preenche `el`; nunca rejeita: erros viram TA.ui.error). */
(function () {
  const h = TA.h;
  const ui = TA.ui;

  /* ------------------------------------------------------------------ utilidades */
  const isObj = (v) => v !== null && typeof v === 'object';
  const keysOf = (o) => (isObj(o) ? Object.keys(o) : []);
  const has = (o) => keysOf(o).length > 0;

  /** carrega `loader()` (devolve Node ou Promise<Node>) para dentro de `el`, com carregamento e erro */
  function mountAsync(el, loader) {
    TA.util.clear(el);
    el.appendChild(ui.loading());
    return Promise.resolve()
      .then(loader)
      .then((node) => { TA.util.clear(el); if (node) el.appendChild(node); })
      .catch((e) => { console.error(e); TA.util.clear(el); el.appendChild(ui.error(e)); });
  }

  /** arquivo do run; arquivo inexistente (run em andamento) vira null em vez de erro */
  function fetchFile(runId, name) {
    return TA.api.file(runId, name).catch((e) => {
      if (/n[ãa]o encontrad|not found|404|inexist/i.test(String((e && e.message) || e))) return null;
      throw e;
    });
  }

  /** run.json: usa o que veio do chamador ou carrega */
  function getRun(ctx) {
    if (ctx.run) return Promise.resolve(ctx.run);
    if (ctx.trace && ctx.trace.run) return Promise.resolve(ctx.trace.run);
    return fetchFile(ctx.runId, 'run.json').catch(() => null);
  }

  const card = (title, body, opts, cls) => {
    const c = ui.card(title, body, opts);
    c.classList.add('rt-card');
    if (cls) c.classList.add(cls);
    return c;
  };

  function md(text) {
    const s = text === null || text === undefined ? '' : String(text);
    if (ui.markdown) {
      try { return h('div', { class: 'rt-md' }, ui.markdown(s)); } catch (e) { console.error(e); }
    }
    return h('div', { class: 'rt-plain' }, s);
  }

  /** texto legível de um `content` (string ou lista de blocos) */
  function textOf(content) {
    if (content === null || content === undefined) return '';
    if (typeof content === 'string') return content;
    if (Array.isArray(content)) {
      return content.map((b) => {
        if (typeof b === 'string') return b;
        if (isObj(b)) {
          if (typeof b.text === 'string') return b.text;
          if (b.type === 'function_call' || b.type === 'tool_use') return `[${b.name || 'tool'}] ${b.arguments || TA.util.pretty(b.input || {})}`;
          return TA.util.pretty(b);
        }
        return String(b);
      }).join('\n');
    }
    return TA.util.pretty(content);
  }

  /** lista de mensagens: usa TA.ui.messages se existir, senão um fallback simples */
  function messagesNode(list, opts) {
    if (ui.messages) {
      try { return ui.messages(list, opts || {}); } catch (e) { console.error(e); }
    }
    return h('div', { class: 'col' }, list.map((m) => {
      const role = (m && (m.type || m.role)) || '?';
      const calls = m && Array.isArray(m.tool_calls) ? m.tool_calls : [];
      return h('div', { class: 'rt-vfile', style: 'padding:8px 12px' },
        h('div', { class: 'rt-row' }, ui.badge(role, role === 'ai' || role === 'assistant' ? 'accent' : role === 'tool' ? 'info' : ''), m && m.name ? ui.chip(m.name, true) : null),
        h('div', { class: 'rt-plain', style: 'margin-top:6px' }, textOf(m && m.content)),
        calls.map((c) => h('div', { class: 'rt-mono muted', style: 'margin-top:4px' }, `→ ${c.name}(${TA.fmt.trunc(TA.util.pretty(c.args || {}), 200)})`)));
    }));
  }

  const ROLE_TO_TYPE = { user: 'human', assistant: 'ai', system: 'system', tool: 'tool' };
  /** entrada {role, content} -> formato serializado {type, content} aceito por TA.ui.messages */
  function toSerialized(m) {
    if (!isObj(m)) return { type: 'human', content: String(m) };
    if (m.type) return m;
    return { ...m, type: ROLE_TO_TYPE[m.role] || m.role || 'human' };
  }

  function emptyState(title, text) { return h('div', { class: 'card' }, ui.empty(title, text)); }

  /** tempo de um valor `at` (ISO, epoch em s ou ms) */
  function whenOf(v) {
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v === 'number') return TA.fmt.datetime(new Date(v < 1e12 ? v * 1000 : v).toISOString());
    return TA.fmt.datetime(v);
  }

  function safeJson(v, max) {
    try { const s = JSON.stringify(v); return s && s.length > max ? s.slice(0, max) : (s || ''); } catch (e) { return ''; }
  }

  /** só links http(s) viram <a> (evita javascript: vindo dos dados) */
  function extLink(url, text) {
    const u = String(url || '');
    if (!/^https?:\/\//i.test(u)) return h('span', { class: 'rt-url' }, text || u);
    return h('a', { href: u, target: '_blank', rel: 'noopener noreferrer', class: 'rt-url' }, text || u);
  }

  function spanLink(runId, spanId, label) {
    return TA.router.link('runs/' + runId, { span: spanId }, ui.icon('branch', 'sm'), ' ', label || 'ver span ' + TA.fmt.short(spanId));
  }

  /* ------------------------------------------------------------------ aba: conversa */
  function conversation(el, ctx) {
    return mountAsync(el, async () => {
      const [run, conv] = await Promise.all([getRun(ctx), fetchFile(ctx.runId, 'conversation.json')]);
      const root = h('div', { class: 'rt' });
      const answer = run && run.output && run.output.answer;

      if (answer) {
        root.appendChild(h('div', { class: 'rt-answer' },
          h('div', { class: 'rt-answer-head' }, ui.icon('check'), 'Resposta final', h('span', { class: 'spacer' }),
            run.output.n_sources ? ui.badge(run.output.n_sources + ' fontes', 'accent') : null,
            ui.copyBtn(String(answer))),
          h('div', { class: 'rt-answer-body' }, md(answer))));
      }
      if (!conv) {
        root.appendChild(emptyState('Conversa ainda não gravada', 'O arquivo conversation.json só é gravado ao fim do run.'));
        return root;
      }

      const input = Array.isArray(conv.input_messages) ? conv.input_messages : [];
      const finals = Array.isArray(conv.final_messages) ? conv.final_messages : [];
      root.appendChild(card('Entrada enviada ao agente', input.length ? messagesNode(input.map(toSerialized)) : ui.empty('Sem mensagens de entrada'),
        { hint: `${input.length} mensagem(ns): histórico + pergunta atual` }));
      root.appendChild(card('Estado final', finals.length ? messagesNode(finals) : ui.empty('Sem estado final', 'O run pode ter sido cancelado ou ter falhado antes do fim.'),
        { hint: `${finals.length} mensagem(ns), incluindo chamadas e resultados de tools` }));

      const todos = Array.isArray(conv.todos) ? conv.todos : [];
      if (todos.length) root.appendChild(todosCard(todos));

      const files = isObj(conv.files) ? conv.files : {};
      const fnames = Object.keys(files);
      if (fnames.length) root.appendChild(card('Arquivos virtuais', fnames.map((n, i) => vfile(n, files[n], i === 0)), { hint: `${fnames.length} arquivo(s) no estado final do agente` }));

      const keys = Array.isArray(conv.state_keys) ? conv.state_keys : [];
      if (keys.length) root.appendChild(card('Chaves de estado', h('div', { class: 'rt-chips' }, keys.map((k) => ui.chip(k, true))), { hint: 'o que o estado final do agente continha' }));
      return root;
    });
  }

  function todosCard(todos) {
    const norm = (s) => String(s || 'pending').toLowerCase().replace('-', '_');
    const done = todos.filter((t) => norm(t && t.status) === 'completed').length;
    const pct = todos.length ? (done / todos.length) * 100 : 0;
    const KIND = { completed: ['ok', 'Concluído'], in_progress: ['info', 'Em andamento'], pending: ['', 'Pendente'] };
    return card('Lista de tarefas (todos)', [
      h('div', { class: 'rt-row', style: 'margin-bottom:6px' }, h('b', null, `${done}/${todos.length} concluídas`), h('span', { class: 'rt-sub' }, TA.fmt.pct(done / todos.length, 0))),
      h('div', { class: 'rt-progress' }, h('div', { style: { width: pct + '%' } })),
      h('ul', { class: 'rt-todos' }, todos.map((t) => {
        const st = norm(t && t.status);
        const [kind, label] = KIND[st] || ['', st];
        const txt = isObj(t) ? (t.content || t.task || t.title || t.text || TA.util.pretty(t)) : String(t);
        return h('li', { class: ['rt-todo', st] }, ui.badge(label, kind), h('span', { class: 'txt' }, txt));
      })),
    ]);
  }

  function vfile(path, info, open) {
    const content = isObj(info) && 'content' in info ? info.content : info;
    const text = typeof content === 'string' ? content : TA.util.pretty(content);
    const chars = isObj(info) && info.chars !== undefined ? info.chars : text.length;
    const body = h('div', { class: 'body' });
    const det = h('details', { class: 'rt-vfile', open: open ? true : null },
      h('summary', null, ui.icon('file', 'sm'), h('span', { class: 'rt-mono' }, path), h('span', { class: 'spacer' }), h('span', { class: 'rt-sub' }, TA.fmt.num(chars) + ' caracteres')),
      body);
    let built = false;
    const build = () => { if (!built && det.open) { built = true; body.appendChild(ui.code(text, { maxHeight: 360 })); } };
    det.addEventListener('toggle', build);
    if (open) build();
    return det;
  }

  /* ------------------------------------------------------------------ aba: eventos */
  const EV_UI = {
    model_call: 'llm', tool: 'tool', subagent: 'subagent', subagent_dynamic: 'subagent', code_eval: 'code_eval',
    async_task: 'async_task', todos: 'todos', skill: 'skill', file: 'file', summarization: 'summarization',
  };
  const EV_ICON = { response: 'chat', reasoning: 'bot', tool_args: 'tool', sources: 'link', notice: 'alert', interrupt: 'alert', graph_step: 'branch', custom: 'code', run: 'layers' };
  const PHASE_KIND = { start: 'info', end: 'ok', error: 'err', cancelled: 'warn', delta: '', info: 'accent' };
  const VIS_OPTIONS = [{ value: '', label: 'Todas' }, { value: 'primary', label: 'Primárias' }, { value: 'secondary', label: 'Secundárias' }, { value: 'debug', label: 'Debug' }];

  function eventIcon(kind) {
    if (EV_UI[kind]) return ui.kindIcon(EV_UI[kind]);
    const ic = ui.icon(EV_ICON[kind] || 'branch');
    ic.classList.add('rt-ico-plain');
    return ic;
  }

  function events(el, ctx) {
    return mountAsync(el, async () => {
      const [run, data] = await Promise.all([getRun(ctx), fetchFile(ctx.runId, 'events.json')]);
      const list = data && Array.isArray(data.events) ? data.events : [];
      if (!list.length) return emptyState('Sem eventos', 'O arquivo events.json só é gravado ao fim do run.');
      return buildEvents(list, run);
    });
  }

  function buildEvents(list, run) {
    /* ---- tempo: offset em segundos desde o início do run ---- */
    let firstTs = Infinity, lastTs = -Infinity;
    list.forEach((e) => { if (typeof e.ts === 'number') { if (e.ts < firstTs) firstTs = e.ts; if (e.ts > lastTs) lastTs = e.ts; } });
    let t0 = run && run.started_at ? Date.parse(run.started_at) / 1000 : NaN;
    if (!Number.isFinite(t0) || !Number.isFinite(firstTs) || Math.abs(t0 - firstTs) > 3600) t0 = Number.isFinite(firstTs) ? firstTs : 0;
    const offOf = (e) => (typeof e.ts === 'number' ? e.ts - t0 : null);
    const tEnd = Math.max(0.001, (Number.isFinite(lastTs) ? lastTs : t0) - t0);

    /* ---- contagens para os filtros ---- */
    const kindCount = new Map(), agentSet = new Set(), phaseSet = new Set();
    list.forEach((e) => {
      kindCount.set(e.kind, (kindCount.get(e.kind) || 0) + 1);
      if (e.agent) agentSet.add(e.agent);
      if (e.phase) phaseSet.add(e.phase);
    });
    const kinds = [...kindCount.entries()].sort((a, b) => b[1] - a[1]);

    const st = { kinds: new Set(), phase: '', vis: '', agent: '', q: '', group: true, range: null, page: 0, size: 100 };
    const open = new Set();
    const hayCache = new WeakMap();
    function hay(e) {
      let s = hayCache.get(e);
      if (s === undefined) {
        s = [e.kind, e.phase, e.agent, e.name, e.label, e.summary, e.error ? safeJson(e.error, 500) : '',
          e.data && typeof e.data.text === 'string' ? e.data.text : '', e.args ? safeJson(e.args, 1500) : '', e.data ? safeJson(e.data, 1500) : '']
          .filter(Boolean).join(' ').toLowerCase();
        hayCache.set(e, s);
      }
      return s;
    }
    const passBase = (e) => (!st.kinds.size || st.kinds.has(e.kind)) && (!st.phase || e.phase === st.phase) && (!st.vis || e.visibility === st.vis)
      && (!st.agent || (e.agent || '') === st.agent) && (!st.q || hay(e).includes(st.q.toLowerCase()));
    const inRange = (e) => { const o = offOf(e); return o === null || !st.range || (o >= st.range.from && (o < st.range.to || st.range.last)); };

    const deltaText = (e) => (e.data && (typeof e.data.text === 'string' ? e.data.text : typeof e.data.delta === 'string' ? e.data.delta : '')) || '';
    const msgId = (e) => (e.data && e.data.message_id) || e.id;
    function groupRows(evs) {
      const rows = [];
      let cur = null;
      for (const e of evs) {
        const g = st.group && e.phase === 'delta' && (e.kind === 'response' || e.kind === 'reasoning');
        if (g && cur && cur.ev.kind === e.kind && cur.ev.agent === e.agent && cur.mid === msgId(e)) { cur.events.push(e); cur.text += deltaText(e); continue; }
        if (g) { cur = { grouped: true, ev: e, events: [e], mid: msgId(e), text: deltaText(e) }; rows.push(cur); } else { cur = null; rows.push({ grouped: false, ev: e, events: [e] }); }
      }
      return rows;
    }

    /* ---- elementos fixos ---- */
    const chartBox = h('div', { class: 'card rt-chart' });
    const info = h('div', { class: 'rt-info' });
    const tableBox = h('div');
    const pagerBox = h('div');
    let rows = [];

    const search = ui.searchInput({ placeholder: 'Buscar nos eventos…', onInput: (v) => { st.q = v; st.page = 0; update(); } });
    const agentSel = ui.select({ title: 'Agente', options: [{ value: '', label: 'Todos os agentes' }, ...[...agentSet].sort().map((a) => ({ value: a, label: a }))], value: '', onChange: (v) => { st.agent = v; st.page = 0; update(); } });
    const phaseSel = ui.select({ title: 'Fase', options: [{ value: '', label: 'Todas as fases' }, ...[...phaseSet].sort().map((p) => ({ value: p, label: p }))], value: '', onChange: (v) => { st.phase = v; st.page = 0; update(); } });
    const visSeg = ui.seg({ options: VIS_OPTIONS, value: '', onChange: (v) => { st.vis = v; st.page = 0; update(); } });
    const groupChk = ui.check({ label: 'Agrupar deltas', checked: true, onChange: (v) => { st.group = v; st.page = 0; update(); } });
    const sizeSel = ui.select({ title: 'Linhas por página', options: [50, 100, 250, 500].map((n) => ({ value: String(n), label: n + ' por página' })), value: '100', onChange: (v) => { st.size = Number(v) || 100; st.page = 0; update(); } });
    const clearBtn = h('button', { class: 'btn sm ghost hidden', onClick: resetFilters }, ui.icon('x', 'sm'), 'Limpar filtros');

    const chipEls = new Map();
    const chips = h('div', { class: 'rt-chips' }, kinds.map(([k, n]) => {
      const b = h('button', { type: 'button', class: 'rt-fchip', title: 'Filtrar por tipo: ' + k, onClick: () => {
        if (st.kinds.has(k)) st.kinds.delete(k); else st.kinds.add(k);
        st.page = 0; update();
      } }, eventIcon(k), k, h('span', { class: 'n' }, TA.fmt.num(n)));
      chipEls.set(k, b);
      return b;
    }));

    function resetFilters() {
      st.kinds.clear(); st.phase = ''; st.vis = ''; st.agent = ''; st.q = ''; st.range = null; st.page = 0;
      search.set(''); agentSel.set(''); phaseSel.set(''); visSeg.set('');
      update();
    }

    /* ---- gráfico de densidade (primárias x demais), clique numa barra filtra aquele intervalo ---- */
    const NB = 60, BW = 10, BH = 56;
    function drawChart(base) {
      const bins = Array.from({ length: NB }, () => ({ p: 0, s: 0 }));
      base.forEach((e) => {
        const o = offOf(e);
        if (o === null) return;
        const i = TA.util.clamp(Math.floor((o / tEnd) * NB), 0, NB - 1);
        if (e.visibility === 'primary') bins[i].p++; else bins[i].s++;
      });
      const max = Math.max(1, ...bins.map((b) => b.p + b.s));
      const svg = h.svg('svg', { class: 'rt-spark', viewBox: `0 0 ${NB * BW} ${BH}`, preserveAspectRatio: 'none', role: 'img', 'aria-label': 'Densidade de eventos ao longo do tempo' });
      bins.forEach((b, i) => {
        const from = (i / NB) * tEnd, to = ((i + 1) / NB) * tEnd;
        const sel = st.range && st.range.bin === i;
        const hs = (b.s / max) * (BH - 2), hp = (b.p / max) * (BH - 2);
        const bg = h.svg('rect', { class: ['rt-bar-bg', sel && 'sel'], x: i * BW, y: 0, width: BW, height: BH });
        const click = () => { st.range = sel ? null : { from, to, bin: i, last: i === NB - 1 }; st.page = 0; update(); };
        const tipText = `${TA.fmt.dur(from)} – ${TA.fmt.dur(to)}\n${b.p + b.s} evento(s): ${b.p} primários, ${b.s} secundários/debug\nClique para filtrar este intervalo`;
        ui.tip(bg, tipText);
        bg.addEventListener('click', click);
        svg.appendChild(bg);
        if (b.s) svg.appendChild(h.svg('rect', { class: 'rt-bar s', x: i * BW + 1, y: BH - hs, width: BW - 2, height: hs, 'pointer-events': 'none' }));
        if (b.p) svg.appendChild(h.svg('rect', { class: 'rt-bar p', x: i * BW + 1, y: BH - hs - hp, width: BW - 2, height: hp, 'pointer-events': 'none' }));
      });
      TA.util.clear(chartBox);
      chartBox.appendChild(h('div', { class: 'rt-row', style: 'margin-bottom:6px' },
        h('b', { class: 'small' }, 'Densidade de eventos'), h('span', { class: 'rt-sub' }, 'clique numa barra para filtrar o intervalo'), h('span', { class: 'spacer' }),
        h('span', { class: 'rt-legend' }, h('span', null, h('i', { class: 'p' }), 'primários'), h('span', null, h('i', { class: 's' }), 'secundários/debug'))));
      chartBox.appendChild(svg);
      chartBox.appendChild(h('div', { class: 'rt-axis' }, h('span', null, '0 s'), h('span', null, TA.fmt.dur(tEnd / 2)), h('span', null, TA.fmt.dur(tEnd))));
    }

    /* ---- tabela ---- */
    const COLS = ['', 'Seq', 'Offset', 'Tipo', 'Fase', 'Agente', 'Rótulo', 'Duração'];
    function renderTable() {
      TA.util.clear(tableBox); TA.util.clear(pagerBox);
      if (!rows.length) { tableBox.appendChild(h('div', { class: 'table-wrap' }, ui.empty('Nenhum evento com esses filtros'))); return; }
      const maxPage = Math.max(0, Math.ceil(rows.length / st.size) - 1);
      st.page = Math.min(st.page, maxPage);
      const slice = rows.slice(st.page * st.size, (st.page + 1) * st.size);
      const tbody = h('tbody');
      slice.forEach((r) => tbody.appendChild(eventRow(r, tbody)));
      tableBox.appendChild(h('div', { class: 'table-wrap rt-evwrap' },
        h('table', { class: 't rt-evt' }, h('thead', null, h('tr', null, COLS.map((c) => h('th', null, c)))), tbody)));
      if (rows.length > st.size) {
        pagerBox.appendChild(ui.pager({ total: rows.length, limit: st.size, offset: st.page * st.size, onChange: (off) => { st.page = Math.floor(off / st.size); renderTable(); } }));
      }
    }

    function eventRow(r, tbody) {
      const e = r.ev;
      const key = r.events[0].seq + (r.grouped ? 'g' : '');
      const last = r.events[r.events.length - 1];
      const isErr = !!e.error || e.phase === 'error';
      const o = offOf(e);
      const depth = Number(e.depth) || 0;
      const label = r.grouped ? r.text : (e.label || e.summary || e.name || '');
      let dur = e.duration_s;
      if (r.grouped && r.events.length > 1 && typeof last.ts === 'number' && typeof e.ts === 'number') dur = last.ts - e.ts;
      const tog = h('td', { class: 'rt-tog' }, '▸');
      const tr = h('tr', { class: ['rt-ev', isErr && 'rt-err'], tabindex: 0, role: 'button', 'aria-expanded': 'false' },
        tog,
        h('td', { class: 'rt-seq' }, r.events.length > 1 ? `${r.events[0].seq}–${last.seq}` : (e.seq ?? '—')),
        h('td', { class: 'rt-off', title: o === null ? null : `${o.toFixed(6)} s desde o início` }, o === null ? '—' : '+' + o.toFixed(3) + ' s'),
        h('td', null, h('span', { class: 'rt-kind' }, eventIcon(e.kind), e.kind)),
        h('td', null, e.phase ? ui.badge(e.phase, PHASE_KIND[e.phase] || '') : '—'),
        h('td', null, agentCell(e, depth)),
        h('td', null, h('div', { class: 'rt-label', title: label ? TA.fmt.trunc(label, 400) : null },
          TA.fmt.trunc(label || '—', 200),
          r.grouped && r.events.length > 1 ? h('span', { class: 'rt-x', title: 'deltas agrupados' }, '×' + r.events.length) : null,
          !r.grouped && e.name && e.name !== label ? h('span', { class: 'chip mono name' }, e.name) : null,
          isErr ? ui.badge('erro', 'err') : null)),
        h('td', { class: 'rt-dur' }, dur === null || dur === undefined ? '—' : TA.fmt.dur(dur)));
      let detail = null;
      const toggle = () => {
        if (detail) { detail.remove(); detail = null; open.delete(key); tr.classList.remove('rt-open'); tog.textContent = '▸'; tr.setAttribute('aria-expanded', 'false'); return; }
        detail = h('tr', { class: 'rt-detail' }, h('td', { colspan: COLS.length }, detailNode(r)));
        tr.parentNode.insertBefore(detail, tr.nextSibling);
        open.add(key); tr.classList.add('rt-open'); tog.textContent = '▾'; tr.setAttribute('aria-expanded', 'true');
      };
      tr.addEventListener('click', (ev) => { if (!ev.target.closest('a,button,.jt')) toggle(); });
      tr.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); } });
      if (open.has(key)) setTimeout(() => { if (tr.parentNode && !detail) toggle(); }, 0);
      return tr;
    }

    function agentCell(e, depth) {
      if (!e.agent) return h('span', { class: 'faint' }, '—');
      return h('span', { class: 'rt-agent', title: e.parent_id ? 'parent_id: ' + e.parent_id : null },
        depth ? h('span', { class: 'ind', style: { width: depth * 12 + 'px' } }) : null,
        h('span', { class: 'dot', style: { background: TA.util.colorFor(e.agent) } }), e.agent);
    }

    function detailNode(r) {
      if (r.grouped) {
        return h('div', null,
          h('div', { class: 'rt-row', style: 'margin-bottom:6px' }, h('b', { class: 'small' }, `${r.events.length} delta(s) concatenados`), h('span', { class: 'spacer' }), ui.copyBtn(r.text, 'Copiar texto')),
          h('div', { class: 'rt-delta-text' }, r.text || '(vazio)'),
          ui.jsonTree(r.events.length === 1 ? r.events[0] : r.events, { expand: r.events.length === 1 ? 1 : 0 }));
      }
      return h('div', null,
        h('div', { class: 'rt-row', style: 'margin-bottom:6px' }, h('span', { class: 'rt-sub' }, 'Evento completo'), h('span', { class: 'spacer' }), ui.copyBtn(() => TA.util.pretty(r.ev), 'Copiar JSON')),
        ui.jsonTree(r.ev, { expand: 1 }));
    }

    /* ---- atualização geral ---- */
    function update() {
      const base = list.filter(passBase);
      const evs = st.range ? base.filter(inRange) : base;
      rows = groupRows(evs);
      kinds.forEach(([k]) => chipEls.get(k).classList.toggle('on', st.kinds.has(k)));
      const filtered = st.kinds.size || st.phase || st.vis || st.agent || st.q || st.range;
      clearBtn.classList.toggle('hidden', !filtered);
      TA.util.clear(info);
      info.appendChild(h('span', null, `${TA.fmt.num(evs.length)} de ${TA.fmt.num(list.length)} eventos · ${TA.fmt.num(rows.length)} linha(s)`));
      if (st.range) info.appendChild(h('span', { class: 'badge accent' }, `intervalo ${TA.fmt.dur(st.range.from)} – ${TA.fmt.dur(st.range.to)}`));
      drawChart(base);
      renderTable();
    }

    const root = h('div', { class: 'rt rt-events' },
      chartBox,
      h('div', { class: 'rt-toolbar' }, search.el, agentSel.el, phaseSel.el, visSeg.el, groupChk, h('span', { class: 'spacer' }), sizeSel.el, clearBtn),
      chips, info, tableBox, pagerBox);
    update();
    return root;
  }

  /* ------------------------------------------------------------------ aba: fontes */
  function sources(el, ctx) {
    return mountAsync(el, async () => {
      const [run, data] = await Promise.all([getRun(ctx), fetchFile(ctx.runId, 'sources.json')]);
      const srcs = data && Array.isArray(data.sources) ? data.sources : [];
      const pubs = data && Array.isArray(data.publications) ? data.publications : [];
      if (!data || (!srcs.length && !pubs.length)) {
        return emptyState('Nenhuma fonte consultada', 'Este run não usou ferramentas que publicam fontes (como a busca na web).');
      }
      const answer = (run && run.output && run.output.answer) || '';

      // quantas vezes cada URL apareceu nas publicações do canal lateral
      const counts = new Map();
      pubs.forEach((p) => {
        const items = Array.isArray(p.payload) ? p.payload : (p.payload && Array.isArray(p.payload.sources) ? p.payload.sources : []);
        const seen = new Set();
        items.forEach((s) => { if (s && s.url && !seen.has(s.url)) { seen.add(s.url); counts.set(s.url, (counts.get(s.url) || 0) + 1); } });
      });
      const rows = srcs.map((s) => ({ ...s, count: counts.has(s.url) ? counts.get(s.url) : (pubs.length ? 0 : null), cited: !!(s.url && answer && answer.includes(String(s.url).replace(/\/$/, ''))) }));
      const domains = new Map();
      rows.forEach((r) => domains.set(r.domain || '—', (domains.get(r.domain || '—') || 0) + 1));

      let sort = { key: 'count', order: 'desc' };
      const tbl = ui.table({
        columns: [
          { key: 'domain', label: 'Domínio', sortable: true, render: (r) => h('span', { class: 'rt-domain' }, ui.icon('link', 'sm'), r.domain || '—') },
          { key: 'title', label: 'Título', sortable: true, render: (r) => r.title || '—' },
          { key: 'url', label: 'URL', render: (r) => extLink(r.url, TA.fmt.trunc(r.url, 80)) },
          { key: 'count', label: 'Vezes citada', align: 'r', sortable: true, title: 'Em quantas buscas (publicações do canal lateral) esta URL apareceu', render: (r) => (r.count === null ? '—' : TA.fmt.num(r.count)) },
          { key: 'cited', label: 'Na resposta', sortable: true, render: (r) => (r.cited ? ui.badge('citada', 'ok') : h('span', { class: 'faint' }, '—')) },
        ],
        rows: sortRows(rows, sort),
        sort,
        onSort: (key, order) => { sort = { key, order }; tbl.setSort(sort); tbl.setRows(sortRows(rows, sort)); },
        empty: 'Nenhuma fonte',
      });

      const root = h('div', { class: 'rt' });
      root.appendChild(h('div', { class: 'rt-kpis' },
        ui.kpi({ label: 'Fontes', value: TA.fmt.num(rows.length) }),
        ui.kpi({ label: 'Domínios', value: TA.fmt.num(domains.size) }),
        ui.kpi({ label: 'Citadas na resposta', value: TA.fmt.num(rows.filter((r) => r.cited).length) }),
        ui.kpi({ label: 'Publicações', value: TA.fmt.num(pubs.length), sub: 'canal lateral' })));
      if (domains.size) {
        root.appendChild(h('div', { class: 'rt-chips' }, [...domains.entries()].sort((a, b) => b[1] - a[1]).map(([d, n]) => h('span', { class: 'chip' }, d, h('b', null, n)))));
      }
      root.appendChild(card('Fontes consultadas', tbl.el, { hint: 'URLs deduplicadas, na ordem em que apareceram' }));

      root.appendChild(h('div', null,
        h('div', { class: 'rt-sec-title' }, 'Publicações do canal lateral', h('span', { class: 'n' }, pubs.length)),
        pubs.length ? pubs.map((p, i) => pubCard(p, i)) : emptyState('Sem publicações', 'Nenhuma tool publicou no canal lateral neste run.')));
      return root;
    });
  }

  function sortRows(rows, sort) {
    const dir = sort.order === 'asc' ? 1 : -1;
    const val = (r) => { const v = r[sort.key]; return typeof v === 'string' ? v.toLowerCase() : (v === null || v === undefined ? -1 : Number(v)); };
    return rows.slice().sort((a, b) => { const x = val(a), y = val(b); return x < y ? -dir : x > y ? dir : 0; });
  }

  function pubCard(p, i) {
    const n = Array.isArray(p.payload) ? p.payload.length : null;
    return h('div', { class: 'rt-pub' },
      h('div', { class: 'rt-pub-head' },
        ui.badge('#' + (i + 1), ''), ui.badge(p.toolkit || '—', 'purple'), ui.badge(p.tool || '—', 'info'), ui.badge(p.kind || '—', 'accent'),
        n !== null ? h('span', { class: 'rt-sub' }, n + ' item(ns)') : null, h('span', { class: 'spacer' }),
        h('span', { class: 'rt-sub' }, whenOf(p.created_at)),
        p.turn !== undefined && p.turn !== null ? ui.chip('turno ' + p.turn) : null),
      ui.jsonTree(p.payload === undefined ? p : p.payload, { expand: 0 }));
  }

  /* ------------------------------------------------------------------ aba: erros */
  function errors(el, ctx) {
    return mountAsync(el, async () => {
      const [run, data] = await Promise.all([getRun(ctx), fetchFile(ctx.runId, 'errors.json')]);
      const errs = data && Array.isArray(data.errors) ? data.errors : [];
      const retries = data && Array.isArray(data.retries) ? data.retries : [];
      const warns = data && Array.isArray(data.warnings) ? data.warnings : [];
      const runErr = run && run.error ? run.error : null;
      const root = h('div', { class: 'rt' });

      if (!data && !runErr) return emptyState('Erros ainda não gravados', 'O arquivo errors.json só é gravado ao fim do run.');

      if (!errs.length && !retries.length && !warns.length && !runErr) {
        root.appendChild(h('div', { class: 'rt-okbox' }, ui.icon('check'),
          h('div', null, h('b', null, 'Nenhum erro'), h('span', null, 'Este run terminou sem erros, retries nem avisos.')),
          h('span', { class: 'spacer' }), run ? ui.statusBadge(run.status) : null));
        return root;
      }

      root.appendChild(h('div', { class: 'rt-kpis' },
        ui.kpi({ label: 'Erros', value: TA.fmt.num(errs.length + (runErr ? 1 : 0)), kind: errs.length || runErr ? 'err' : '' }),
        ui.kpi({ label: 'Retries', value: TA.fmt.num(retries.length) }),
        ui.kpi({ label: 'Avisos', value: TA.fmt.num(warns.length) })));

      if (runErr || errs.length) {
        const items = [];
        if (runErr) items.push(errorItem(ctx.runId, { where: 'run', name: 'Falha do run', type: runErr.type, message: runErr.message, traceback: runErr.traceback }));
        errs.forEach((e) => items.push(errorItem(ctx.runId, e)));
        root.appendChild(h('div', null, h('div', { class: 'rt-sec-title' }, 'Erros', h('span', { class: 'n' }, items.length)), items));
      }
      if (retries.length) root.appendChild(h('div', null, h('div', { class: 'rt-sec-title' }, 'Retries', h('span', { class: 'n' }, retries.length)), retries.map((r) => genericItem(ctx.runId, r, 'info', 'retry'))));
      if (warns.length) root.appendChild(h('div', null, h('div', { class: 'rt-sec-title' }, 'Avisos', h('span', { class: 'n' }, warns.length)), warns.map((w) => genericItem(ctx.runId, w, 'warn', 'aviso'))));
      return root;
    });
  }

  const ERR_KNOWN = new Set(['where', 'name', 'type', 'message', 'span_id', 'at', 'traceback']);

  function errorItem(runId, e) {
    const extra = {};
    keysOf(e).forEach((k) => { if (!ERR_KNOWN.has(k)) extra[k] = e[k]; });
    return h('div', { class: 'rt-eitem' },
      h('div', { class: 'rt-ehead' }, ui.badge(e.type || 'erro', 'err'),
        e.where ? ui.chip(e.where, true) : null, e.name ? h('b', null, e.name) : null,
        h('span', { class: 'spacer' }), e.at !== undefined && e.at !== null ? h('span', { class: 'rt-sub' }, whenOf(e.at)) : null),
      h('p', { class: 'rt-emsg' }, e.message ? String(e.message) : '(sem mensagem)'),
      e.span_id ? h('div', { class: 'rt-ekv' }, h('span', null, 'span: ', spanLink(runId, e.span_id))) : null,
      e.traceback ? ui.code(String(e.traceback), { maxHeight: 320 }) : null,
      has(extra) ? h('div', { style: 'margin-top:8px' }, ui.jsonTree(extra, { expand: 1 })) : null);
  }

  /** retry/aviso com formato livre: título/mensagem conhecidos + o resto em árvore */
  function genericItem(runId, o, kind, label) {
    if (!isObj(o)) return h('div', { class: ['rt-eitem', kind] }, h('p', { class: 'rt-emsg' }, String(o)));
    const msg = o.message || o.error || o.reason;
    const rest = {};
    keysOf(o).forEach((k) => { if (!['type', 'message', 'span_id', 'at'].includes(k) && !(k === 'error' && typeof o.error === 'string')) rest[k] = o[k]; });
    return h('div', { class: ['rt-eitem', kind] },
      h('div', { class: 'rt-ehead' }, ui.badge(o.type || label, kind === 'warn' ? 'warn' : 'info'), h('span', { class: 'spacer' }), o.at !== undefined && o.at !== null ? h('span', { class: 'rt-sub' }, whenOf(o.at)) : null),
      msg ? h('p', { class: 'rt-emsg' }, typeof msg === 'string' ? msg : TA.util.pretty(msg)) : null,
      o.span_id ? h('div', { class: 'rt-ekv' }, h('span', null, 'span: ', spanLink(runId, o.span_id))) : null,
      has(rest) ? ui.jsonTree(rest, { expand: 1 }) : null);
  }

  /* ------------------------------------------------------------------ aba: arquivos */
  const FILE_INFO = {
    'run.json': 'Resumo do run: status, totais, tempos, modelo, ambiente',
    'conversation.json': 'Mensagens de entrada e estado final, todos e arquivos virtuais',
    'spans.json': 'Árvore de execução: chains, LLMs e tools',
    'llm_calls.json': 'Cada chamada ao LLM: prompt completo, resposta, tokens e latência',
    'tool_calls.json': 'Cada chamada de tool: argumentos, saída e duração',
    'subagents.json': 'Delegações a subagents (estáticos, dinâmicos e assíncronos)',
    'events.json': 'Todos os eventos do streaming, em ordem',
    'response.json': 'Resposta em streaming: segmentos, reasoning e tempos',
    'sources.json': 'Fontes consultadas e publicações do canal lateral',
    'errors.json': 'Erros, retries e avisos',
  };
  const BIG_FILE = 1048576;

  function downloadJson(filename, data) {
    const blob = new Blob([TA.util.pretty(data)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = h('a', { href: url, download: filename, style: 'display:none' });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  /** poda `value` mantendo só os caminhos cuja chave ou valor contém `q` (listas viram objetos com o índice original) */
  function pruneBy(value, q, budget) {
    const ql = q.toLowerCase();
    function walk(v) {
      if (!isObj(v)) return String(v).toLowerCase().includes(ql) ? (budget.n++, { keep: true, v }) : { keep: false };
      const entries = Array.isArray(v) ? v.map((x, i) => [String(i), x]) : Object.entries(v);
      const out = {};
      let any = false;
      for (const [k, x] of entries) {
        if (budget.n >= budget.max) break;
        if (!Array.isArray(v) && k.toLowerCase().includes(ql)) { out[k] = x; any = true; budget.n++; continue; }
        const r = walk(x);
        if (r.keep) { out[k] = r.v; any = true; }
      }
      return any ? { keep: true, v: out } : { keep: false };
    }
    const r = walk(value);
    return r.keep ? r.v : null;
  }

  function files(el, ctx) {
    return mountAsync(el, async () => {
      const run = await getRun(ctx);
      const sizes = (run && run.files) || {};
      const names = [...Object.keys(FILE_INFO)];
      Object.keys(sizes).forEach((n) => { if (!names.includes(n)) names.push(n); });
      const cache = new Map();
      let selected = null;

      const viewer = h('div', { class: 'rt-viewer' });
      const buttons = new Map();
      const grid = h('div', { class: 'rt-filegrid' }, names.map((n) => {
        const meta = sizes[n];
        const bytes = meta && typeof meta.bytes === 'number' ? meta.bytes : null;
        const missing = run && run.files && !(n in sizes) && n !== 'run.json';
        const b = h('button', { type: 'button', class: ['rt-fbtn', missing && 'missing'], onClick: () => select(n) },
          h('span', { class: 'nm' }, ui.icon('file', 'sm'), n, h('span', { class: 'sz' }, bytes === null ? '—' : TA.fmt.bytes(bytes))),
          h('span', { class: 'ds' }, FILE_INFO[n] || 'Arquivo do run'));
        buttons.set(n, b);
        return b;
      }));

      function select(name, force) {
        selected = name;
        buttons.forEach((b, n) => b.classList.toggle('on', n === name));
        const meta = sizes[name];
        const bytes = meta && typeof meta.bytes === 'number' ? meta.bytes : null;
        TA.util.clear(viewer);
        if (run && run.files && !(name in sizes) && name !== 'run.json') {   // run em andamento: só o run.json existe no disco
          viewer.appendChild(ui.empty('Arquivo ainda não gravado', `${name} só é gravado ao fim do run (hoje existe apenas o run.json).`));
          return;
        }
        if (!force && bytes !== null && bytes > BIG_FILE && !cache.has(name)) {
          viewer.appendChild(h('div', { class: 'rt-warnbox' }, ui.icon('alert'),
            h('div', { class: 'rt-grow' }, h('b', null, `${name} é grande (${TA.fmt.bytes(bytes)})`),
              h('div', { class: 'rt-sub' }, 'Carregar e montar a árvore pode deixar a página lenta. O arquivo só é buscado se você pedir.')),
            h('button', { class: 'btn primary', onClick: () => select(name, true) }, ui.icon('download', 'sm'), 'Carregar mesmo assim')));
          return;
        }
        viewer.appendChild(ui.loading('Carregando ' + name + '…'));
        const p = cache.has(name) ? Promise.resolve(cache.get(name)) : TA.api.file(ctx.runId, name).then((d) => { cache.set(name, d); return d; });
        p.then((data) => { if (selected === name) showFile(name, data, bytes); })
          .catch((e) => { if (selected === name) { TA.util.clear(viewer); viewer.appendChild(ui.error(e)); } });
      }

      function showFile(name, data, bytes) {
        TA.util.clear(viewer);
        const treeBox = h('div', { class: 'rt-tree' });
        const status = h('span', { class: 'rt-sub' });
        const renderTree = (q) => {
          TA.util.clear(treeBox);
          if (!q) { status.textContent = ''; treeBox.appendChild(ui.jsonTree(data, { expand: 1 })); return; }
          const budget = { n: 0, max: 300 };
          const pruned = pruneBy(data, q, budget);
          if (pruned === null) { status.textContent = 'nenhum resultado'; treeBox.appendChild(ui.empty('Nada encontrado', `Nenhuma chave ou valor contém “${q}”.`)); return; }
          status.textContent = budget.n >= budget.max ? `primeiros ${budget.max} resultados` : `${budget.n} resultado(s)`;
          treeBox.appendChild(ui.jsonTree(pruned, { expand: 12 }));
        };
        const search = ui.searchInput({ placeholder: 'Buscar chave ou valor…', onInput: renderTree, delay: 350 });
        const filename = `${TA.fmt.short(ctx.runId)}_${name}`;
        viewer.appendChild(h('div', { class: 'rt-vhead' },
          h('h3', { class: 'rt-mono' }, name), bytes !== null ? ui.chip(TA.fmt.bytes(bytes)) : null,
          search.el, status, h('span', { class: 'spacer' }),
          ui.copyBtn(() => TA.util.pretty(data), 'Copiar JSON'),
          h('button', { class: 'btn sm', title: 'Baixa o que está na tela, sem servidor', onClick: () => downloadJson(filename, data) }, ui.icon('download', 'sm'), 'Baixar')));
        viewer.appendChild(treeBox);
        renderTree('');
      }

      viewer.appendChild(h('div', { class: 'rt-sub' }, 'Escolha um arquivo acima para ver o JSON bruto.'));
      return h('div', { class: 'rt' }, grid, viewer);
    });
  }

  /* ------------------------------------------------------------------ aba: configuração */
  function table(columns, rows, empty) { return ui.table({ columns, rows, empty }).el; }

  function config(el, ctx) {
    return mountAsync(el, async () => {
      const run = await getRun(ctx);
      if (!run) return emptyState('Sem dados do run', 'Não consegui carregar o run.json.');
      const m = run.model || {};
      const t = run.totals || {};
      const tm = run.timing || {};
      const env = run.environment || {};
      const hash = run.config_hash;
      const root = h('div', { class: 'rt' });

      if (hash) {
        const big = TA.router.link('prompts/' + hash, null, ui.icon('book'),
          h('span', null, 'Ver system prompt e regras desta versão', h('small', null, 'config ' + hash + ': prompts, regras, skills e subagents completos')),
          h('span', { class: 'arrow' }, ui.icon('chevR')));
        big.classList.add('rt-biglink');
        root.appendChild(big);
      }

      // totais
      root.appendChild(h('div', { class: 'rt-kpis' },
        ui.kpi({ label: 'Chamadas ao LLM', value: TA.fmt.num(t.llm_calls), sub: `${TA.fmt.num(t.main_llm_calls)} principal · ${TA.fmt.num(t.subagent_llm_calls)} subagents` }),
        ui.kpi({ label: 'Chamadas de tools', value: TA.fmt.num(t.tool_calls), sub: `${TA.fmt.num(t.subagent_calls)} delegações` }),
        ui.kpi({ label: 'Tokens', value: TA.fmt.compact(t.total_tokens), sub: `${TA.fmt.compact(t.input_tokens)} entrada · ${TA.fmt.compact(t.output_tokens)} saída` }),
        ui.kpi({ label: 'Cache', value: TA.fmt.compact(t.cache_read_tokens), sub: `${TA.fmt.compact(t.cache_creation_tokens)} criados` }),
        ui.kpi({ label: 'Custo', value: TA.fmt.cost(t.cost_usd), sub: t.cost_usd === null || t.cost_usd === undefined ? 'modelo sem preço' : null }),
        ui.kpi({ label: 'Erros', value: TA.fmt.num(t.errors), kind: t.errors ? 'err' : '' })));

      const modelPairs = [
        ['Modelo', m.spec], ['Provedor', m.provider], ['Id do modelo', m.model_id],
        ['Temperatura', m.temperature], ['Thinking', m.thinking === null || m.thinking === undefined ? null : (isObj(m.thinking) ? TA.util.pretty(m.thinking) : String(m.thinking))],
        ['Máx. tokens', m.max_tokens], ['Timeout', m.timeout === undefined || m.timeout === null ? null : m.timeout + ' s'], ['Retries máx.', m.max_retries],
        ['Modelos usados', Array.isArray(m.models_used) && m.models_used.length ? h('span', { class: 'rt-chips' }, m.models_used.map((x) => ui.chip(x, true))) : null],
      ];
      const modelBody = [ui.kv(modelPairs)];
      if (has(m.extra)) modelBody.push(h('div', { class: 'divider' }), h('div', { class: 'rt-sub' }, 'extra'), ui.jsonTree(m.extra, { expand: 1 }));
      if (has(m.resolved_kwargs)) modelBody.push(h('div', { class: 'divider' }), h('div', { class: 'rt-sub' }, 'resolved_kwargs (o que o ProviderRules realmente enviou)'), ui.jsonTree(m.resolved_kwargs, { expand: 1 }));
      if (hash) modelBody.push(h('div', { class: 'divider' }), ui.kv([['config_hash', h('span', { class: 'rt-mono' }, hash, ' ', ui.copyBtn(hash))]]));

      const timingBody = ui.kv([
        ['Tempo total', TA.fmt.dur(tm.wall_time_s)], ['Tempo em LLM', TA.fmt.dur(tm.llm_time_s)], ['Tempo em tools', TA.fmt.dur(tm.tool_time_s)],
        ['1º token do LLM', TA.fmt.dur(tm.time_to_first_llm_token_s)], ['1º delta da resposta', TA.fmt.dur(tm.time_to_first_response_delta_s)],
        ['Streaming da resposta', TA.fmt.dur(tm.response_stream_s)], ['Deltas da resposta', tm.n_response_deltas === undefined || tm.n_response_deltas === null ? null : TA.fmt.num(tm.n_response_deltas)],
        ['Início', TA.fmt.datetime(run.started_at)], ['Fim', TA.fmt.datetime(run.ended_at)],
      ]);

      const git = env.git || {};
      const envBody = [ui.kv([
        ['Python', env.python], ['Sistema', env.platform],
        ['Git', git.commit ? h('span', { class: 'rt-row' }, h('span', { class: 'rt-mono' }, git.commit), git.branch ? ui.chip(git.branch, true) : null, git.dirty ? ui.badge('alterações locais', 'warn') : ui.badge('limpo', 'ok')) : null],
      ])];
      const pk = env.packages;
      if (has(pk)) envBody.push(h('div', { class: 'divider' }), h('div', { class: 'rt-pkgs' }, Object.keys(pk).sort().map((k) => h('div', { class: 'rt-pkg' }, h('span', null, k), h('span', null, String(pk[k]))))));

      root.appendChild(h('div', { class: 'rt-grid wide' }, card('Modelo', modelBody), card('Tempos', timingBody), card('Ambiente', envBody)));

      // por agente / por tool
      const agentRows = Object.entries(run.by_agent || {}).map(([name, v]) => ({ name, ...(v || {}) }));
      const toolRows = Object.entries(run.by_tool || {}).map(([name, v]) => ({ name, ...(v || {}) }));
      root.appendChild(h('div', { class: 'rt-grid wide' },
        card('Por agente', table([
          { key: 'name', label: 'Agente', render: (r) => h('span', { class: 'rt-agent' }, h('span', { class: 'dot', style: { background: TA.util.colorFor(r.name) } }), r.name) },
          { key: 'llm_calls', label: 'LLM', align: 'r', render: (r) => TA.fmt.num(r.llm_calls) },
          { key: 'input_tokens', label: 'Entrada', align: 'r', render: (r) => TA.fmt.compact(r.input_tokens) },
          { key: 'output_tokens', label: 'Saída', align: 'r', render: (r) => TA.fmt.compact(r.output_tokens) },
          { key: 'tool_calls', label: 'Tools', align: 'r', render: (r) => TA.fmt.num(r.tool_calls) },
          { key: 'llm_time_s', label: 'Tempo LLM', align: 'r', render: (r) => TA.fmt.dur(r.llm_time_s) },
          { key: 'cost_usd', label: 'Custo', align: 'r', render: (r) => TA.fmt.cost(r.cost_usd) },
        ], agentRows, 'Sem dados por agente')),
        card('Por tool', table([
          { key: 'name', label: 'Tool', render: (r) => h('span', { class: 'rt-mono' }, r.name) },
          { key: 'calls', label: 'Chamadas', align: 'r', render: (r) => TA.fmt.num(r.calls) },
          { key: 'errors', label: 'Erros', align: 'r', render: (r) => (r.errors ? h('span', { style: 'color:var(--err)' }, TA.fmt.num(r.errors)) : '0') },
          { key: 'total_s', label: 'Total', align: 'r', render: (r) => TA.fmt.dur(r.total_s) },
          { key: 'avg_s', label: 'Média', align: 'r', render: (r) => TA.fmt.dur(r.avg_s) },
          { key: 'max_s', label: 'Máx.', align: 'r', render: (r) => TA.fmt.dur(r.max_s) },
        ], toolRows, 'Nenhuma tool usada'))));

      // configuração declarada (carregada sob demanda)
      if (hash) {
        const box = h('div', null, ui.loading('Carregando a configuração…'));
        root.appendChild(card('Configuração declarada do agente', box, { hint: 'snapshot de configs/' + hash + '.json' }));
        TA.api.config(hash).then((cfg) => {
          TA.util.clear(box);
          box.appendChild(configSummary(cfg, hash));
        }).catch((e) => { TA.util.clear(box); box.appendChild(ui.error(e)); });
      }
      return root;
    });
  }

  function configSummary(cfg, hash) {
    cfg = cfg || {};
    const p = cfg.prompts || {};
    const sys = typeof p.system_prompt === 'string' ? p.system_prompt : '';
    const rules = Array.isArray(p.rules) ? p.rules : (Array.isArray(cfg.rules) ? cfg.rules : []);
    const skills = Array.isArray(p.skills) ? p.skills : (Array.isArray(cfg.skills) ? cfg.skills : []);
    const subs = isObj(cfg.subagents) ? Object.entries(cfg.subagents) : [];
    const subsOn = subs.filter(([, v]) => v && v.enabled).length;
    const lim = cfg.limits || {};
    const mini = (v, l) => h('div', { class: 'rt-mini' }, h('div', { class: 'v' }, v), h('div', { class: 'l' }, l));
    const head = sys.length > 1500 ? sys.slice(0, 1500) + '\n…' : sys;
    return h('div', null,
      h('div', { class: 'rt-cfg-counts' },
        mini(TA.fmt.num(sys.length), 'caracteres no system prompt'), mini(TA.fmt.num(rules.length), 'regras'), mini(TA.fmt.num(skills.length), 'skills'),
        mini(subsOn === subs.length ? TA.fmt.num(subs.length) : `${subsOn}/${subs.length}`, 'subagents'),
        lim.model_call_limit !== undefined ? mini(TA.fmt.num(lim.model_call_limit), 'limite de chamadas ao modelo') : null,
        lim.subagent_call_limit !== undefined ? mini(TA.fmt.num(lim.subagent_call_limit), 'limite por subagent') : null),
      h('div', { class: 'rt-sec-title' }, 'Início do system prompt', sys.length > 1500 ? h('span', { class: 'n' }, 'primeiros 1.500 de ' + TA.fmt.num(sys.length) + ' caracteres') : null),
      sys ? ui.code(head, { maxHeight: 320 }) : ui.empty('System prompt vazio'),
      subs.length ? h('div', { class: 'rt-chips', style: 'margin-top:10px' }, subs.map(([n, v]) => ui.chip(n + (v && v.enabled ? '' : ' (desligado)'), true))) : null,
      h('div', { style: 'margin-top:12px' }, TA.router.link('prompts/' + hash, null, 'Abrir a versão completa →')));
  }

  /* ------------------------------------------------------------------ API pública */
  TA.runTabs = { conversation, events, sources, errors, files, config };
})();
