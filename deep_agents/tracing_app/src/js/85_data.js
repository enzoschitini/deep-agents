/* Dados: os datasets completos dos JSONs em três explorers (`#/data/llm`, `#/data/tools`, `#/data/files`).
   llm   = todas as chamadas ao LLM de todos os runs;  tools = todas as chamadas de tool;  files = os 10 JSONs de cada run.
   Classes CSS: prefixo `.dx-` (src/css/75_data.css). Estado (filtros, ordem, página) na URL via ctx.setQuery. */
(function () {
  const h = TA.h;
  const PAGE_SIZE = 50;
  const KINDS = [{ id: 'llm', label: 'Chamadas ao LLM' }, { id: 'tools', label: 'Chamadas de tools' }, { id: 'files', label: 'Arquivos dos runs' }];
  const RUN_FILES = ['run.json', 'conversation.json', 'spans.json', 'llm_calls.json', 'tool_calls.json', 'subagents.json', 'events.json', 'response.json', 'sources.json', 'errors.json'];
  const FILE_HINT = {
    'run.json': 'resumo, totais, tempos, ambiente', 'conversation.json': 'mensagens do turno', 'spans.json': 'árvore de spans',
    'llm_calls.json': 'chamadas ao LLM (completas)', 'tool_calls.json': 'chamadas de tool (completas)', 'subagents.json': 'subagents',
    'events.json': 'eventos do streaming', 'response.json': 'resposta e deltas', 'sources.json': 'fontes citadas', 'errors.json': 'erros',
  };

  /* ------------------------------------------------------------------ células reutilizáveis */
  const runLink = (id) => (id ? TA.router.link('runs/' + id, null, h('span', { class: 'dx-id', title: id }, TA.fmt.short(id))) : '—');
  const agentTag = (agent) => (agent
    ? h('span', { class: 'dx-agent', title: agent }, h('span', { class: 'dx-dot', style: { background: TA.util.colorFor(agent) } }), agent)
    : h('span', { class: 'faint' }, '—'));
  const prev = (text, n) => (text ? h('div', { class: 'dx-prev', title: String(text).slice(0, 1500) }, TA.fmt.trunc(text, n || 160)) : h('span', { class: 'faint' }, '—'));
  const num = (v) => (v === null || v === undefined ? h('span', { class: 'faint' }, '—') : TA.fmt.num(v));
  const chips = (arr, max) => {
    const a = Array.isArray(arr) ? arr : [];
    if (!a.length) return h('span', { class: 'faint' }, '—');
    return h('span', { class: 'dx-chips' }, a.slice(0, max || 3).map((t) => TA.ui.chip(t, true)), a.length > (max || 3) ? h('span', { class: 'muted xs' }, '+' + (a.length - (max || 3))) : null);
  };
  const finishBadge = (f) => (f ? TA.ui.badge(f, f === 'stop' || f === 'end_turn' ? 'ok' : f === 'tool_calls' || f === 'tool_use' ? 'info' : 'warn') : h('span', { class: 'faint' }, '—'));

  /* ------------------------------------------------------------------ definição dos explorers tabulares */
  const DEFS = {
    llm: {
      title: 'Chamadas ao LLM', unit: 'chamadas', fetch: (p) => TA.api.llmCalls(p),
      filters: [
        { key: 'q', type: 'search', placeholder: 'Buscar em entrada/saída, run, modelo…' },
        { key: 'model', type: 'select', label: 'Modelo', facet: 'model' },
        { key: 'agent', type: 'select', label: 'Agente', facet: 'agent' },
        { key: 'purpose', type: 'select', label: 'Propósito', facet: 'purpose' },
        { key: 'status', type: 'select', label: 'Status', facet: 'status', fmt: (v) => TA.util.statusLabel(v) },
        { key: 'min_latency', type: 'number', label: 'Latência ≥ (s)' },
        { key: 'errors', type: 'check', label: 'Só erros' },
      ],
      columns: [
        { key: 'started_at', label: 'Quando', sortable: true, render: (r) => h('span', { class: 'nowrap', title: r.started_at || '' }, TA.fmt.datetime(r.started_at)) },
        { key: 'run_id', label: 'Run', render: (r) => runLink(r.run_id) },
        { key: 'agent', label: 'Agente', sortable: true, render: (r) => agentTag(r.agent) },
        { key: 'purpose', label: 'Propósito', sortable: true, render: (r) => (r.purpose ? TA.ui.badge(r.purpose, r.purpose === 'summarization' || r.purpose === 'summary' ? 'warn' : '') : '—') },
        { key: 'model', label: 'Modelo', sortable: true, render: (r) => h('span', { class: 'mono xs' }, r.model || '—') },
        { key: 'status', label: 'Status', sortable: true, render: (r) => TA.ui.statusBadge(r.status) },
        { key: 'input_tokens', label: 'Tokens in', sortable: true, align: 'r', render: (r) => num(r.input_tokens) },
        { key: 'output_tokens', label: 'Tokens out', sortable: true, align: 'r', render: (r) => num(r.output_tokens) },
        { key: 'cache_read_tokens', label: 'Cache', sortable: true, align: 'r', title: 'Tokens lidos do cache', render: (r) => num(r.cache_read_tokens) },
        { key: 'cost_usd', label: 'Custo', sortable: true, align: 'r', render: (r) => TA.fmt.cost(r.cost_usd) },
        { key: 'latency_s', label: 'Latência', sortable: true, align: 'r', render: (r) => TA.fmt.dur(r.latency_s) },
        { key: 'ttft_s', label: 'TTFT', sortable: true, align: 'r', title: 'Tempo até o primeiro token', render: (r) => TA.fmt.dur(r.ttft_s) },
        { key: 'finish_reason', label: 'Fim', render: (r) => finishBadge(r.finish_reason) },
        { key: 'requested_tools', label: 'Tools pedidas', render: (r) => chips(r.requested_tools) },
        { key: 'preview_in', label: 'Entrada', render: (r) => prev(r.preview_in) },
        { key: 'preview_out', label: 'Saída', render: (r) => prev(r.preview_out) },
      ],
      totals(items) {
        const s = (f) => TA.util.sum(items, (r) => r[f] || 0);
        const lats = items.map((r) => r.latency_s).filter((v) => typeof v === 'number');
        return [
          ['Tokens in', TA.fmt.num(s('input_tokens'))], ['Tokens out', TA.fmt.num(s('output_tokens'))], ['Cache', TA.fmt.num(s('cache_read_tokens'))],
          ['Custo', TA.fmt.cost(s('cost_usd'))], ['Latência média', lats.length ? TA.fmt.dur(TA.util.sum(lats) / lats.length) : '—'],
          ['Erros', TA.fmt.num(items.filter((r) => r.status === 'error').length)],
        ];
      },
    },
    tools: {
      title: 'Chamadas de tools', unit: 'chamadas', fetch: (p) => TA.api.toolCalls(p),
      filters: [
        { key: 'q', type: 'search', placeholder: 'Buscar em argumentos, saída, run…' },
        { key: 'name', type: 'select', label: 'Tool', facet: 'name' },
        { key: 'kind', type: 'select', label: 'Tipo', facet: 'kind' },
        { key: 'agent', type: 'select', label: 'Agente', facet: 'agent' },
        { key: 'status', type: 'select', label: 'Status', facet: 'status', fmt: (v) => TA.util.statusLabel(v) },
        { key: 'min_duration', type: 'number', label: 'Duração ≥ (s)' },
        { key: 'errors', type: 'check', label: 'Só erros' },
      ],
      columns: [
        { key: 'started_at', label: 'Quando', sortable: true, render: (r) => h('span', { class: 'nowrap', title: r.started_at || '' }, TA.fmt.datetime(r.started_at)) },
        { key: 'run_id', label: 'Run', render: (r) => runLink(r.run_id) },
        { key: 'name', label: 'Tool', sortable: true, render: (r) => h('span', { class: 'dx-toolname' }, TA.ui.kindIcon(r.kind || 'tool'), h('span', { class: 'mono' }, r.name || '—')) },
        { key: 'kind', label: 'Tipo', sortable: true, render: (r) => (r.kind ? TA.ui.badge(TA.ui.kindMeta(r.kind)[1]) : '—') },
        { key: 'agent', label: 'Agente', sortable: true, render: (r) => agentTag(r.agent) },
        { key: 'status', label: 'Status', sortable: true, render: (r) => TA.ui.statusBadge(r.status) },
        { key: 'duration_s', label: 'Duração', sortable: true, align: 'r', render: (r) => TA.fmt.dur(r.duration_s) },
        { key: 'input_preview', label: 'Argumentos', render: (r) => prev(r.input_preview) },
        { key: 'output_preview', label: 'Saída', render: (r) => prev(r.output_preview) },
        { key: 'output_chars', label: 'Tam. saída', sortable: true, align: 'r', title: 'Caracteres da saída', render: (r) => (r.output_chars === null || r.output_chars === undefined ? '—' : TA.fmt.num(r.output_chars) + ' car.') },
      ],
      totals(items) {
        const durs = items.map((r) => r.duration_s).filter((v) => typeof v === 'number');
        return [
          ['Duração total', TA.fmt.dur(TA.util.sum(durs))], ['Duração média', durs.length ? TA.fmt.dur(TA.util.sum(durs) / durs.length) : '—'],
          ['Saída', TA.fmt.num(TA.util.sum(items, (r) => r.output_chars || 0)) + ' car.'], ['Erros', TA.fmt.num(items.filter((r) => r.status === 'error').length)],
        ];
      },
    },
  };

  /* ================================================================== VIEW */
  TA.views.data = {
    mount(ctx) {
      const kind = (DEFS[ctx.params.kind] || ctx.params.kind === 'files') ? ctx.params.kind : 'llm';
      ctx.crumbs([{ label: 'Dados', href: TA.router.hashFor('data') }, { label: (KINDS.find((k) => k.id === kind) || KINDS[0]).label }]);
      const page = h('div', { class: ['page', 'dx', kind === 'files' && 'dx-wide'] });
      ctx.el.appendChild(page);
      page.appendChild(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Dados'),
        h('div', { class: 'sub' }, 'Os datasets completos gravados pelo rastreamento: todas as chamadas ao LLM, todas as tools e os arquivos JSON de cada run.'))));
      const tabs = TA.ui.tabs({ items: KINDS, active: kind, onChange: (id) => ctx.nav('data/' + id) });
      const host = h('div', { class: 'dx-host' });
      page.append(tabs.el, host);
      try {
        const cleanup = kind === 'files' ? filesExplorer(ctx, host) : tableExplorer(ctx, host, kind);
        if (typeof cleanup === 'function') ctx.onCleanup(cleanup);
      } catch (e) { host.appendChild(TA.ui.error(e)); }
    },
  };

  /* ================================================================== EXPLORER TABULAR (llm / tools) */
  function tableExplorer(ctx, host, kind) {
    const def = DEFS[kind];
    const q = ctx.query;
    const state = {
      f: {}, sort: q.sort || 'started_at', order: q.order === 'asc' ? 'asc' : 'desc', page: Math.max(1, parseInt(q.p, 10) || 1),
    };
    def.filters.forEach((fl) => { if (fl.type !== 'check') state.f[fl.key] = q[fl.key] || ''; });
    let gone = false, token = 0, last = null;
    const facets = {};                                   // facet -> Set de valores já vistos
    const selects = {};                                  // key -> controle de select
    const addFacet = (name, v) => { if (v === null || v === undefined || v === '') return; (facets[name] || (facets[name] = new Set())).add(String(v)); };

    const bar = h('div', { class: 'dx-filters' });
    const info = h('div', { class: 'dx-info' });
    const tableBox = h('div', { class: 'dx-tablebox' });
    const totalsBox = h('div', { class: 'dx-totals' });
    const pagerBox = h('div');
    host.append(bar, info, tableBox, totalsBox, pagerBox);

    /* ---- filtros ---- */
    const controls = {};
    def.filters.forEach((fl) => {
      if (fl.type === 'search') {
        const s = TA.ui.searchInput({ placeholder: fl.placeholder, value: state.f[fl.key], onInput: (v) => change({ [fl.key]: v }) });
        controls[fl.key] = s; bar.appendChild(s.el);
      } else if (fl.type === 'select') {
        const s = TA.ui.select({ options: selectOptions(fl), value: state.f[fl.key], title: fl.label, onChange: (v) => change({ [fl.key]: v }) });
        selects[fl.key] = s; controls[fl.key] = s; bar.appendChild(s.el);
      } else if (fl.type === 'number') {
        const input = h('input', { class: 'input dx-num', type: 'number', min: '0', step: '0.1', placeholder: fl.label, title: fl.label, value: state.f[fl.key],
          onInput: TA.util.debounce(() => change({ [fl.key]: input.value }), 350) });
        controls[fl.key] = { set: (v) => { input.value = v; } }; bar.appendChild(input);
      } else if (fl.type === 'check') {
        const c = TA.ui.check({ label: fl.label, checked: state.f.status === 'error', onChange: (on) => change({ status: on ? 'error' : '' }) });
        controls[fl.key] = c; bar.appendChild(c);
      }
    });
    const clearBtn = h('button', { class: 'btn sm ghost', onClick: () => {
      Object.keys(state.f).forEach((k) => { state.f[k] = ''; });
      Object.values(controls).forEach((c) => { if (c && c.set) c.set(''); });
      syncChecks(); persist(); state.page = 1; load();
    } }, TA.ui.icon('x', 'sm'), 'Limpar');
    bar.appendChild(clearBtn);

    function selectOptions(fl) {
      const vals = new Set(facets[fl.facet] || []);
      if (state.f[fl.key]) vals.add(state.f[fl.key]);
      if (fl.facet === 'status') ['completed', 'error'].forEach((v) => vals.add(v));
      if (fl.facet === 'model' && TA.state.meta && Array.isArray(TA.state.meta.models)) TA.state.meta.models.forEach((m) => vals.add(m));
      return [{ value: '', label: fl.label + ': todos' }].concat(Array.from(vals).sort().map((v) => ({ value: v, label: fl.fmt ? fl.fmt(v) : v })));
    }
    function refreshSelects() { def.filters.forEach((fl) => { if (fl.type === 'select' && selects[fl.key]) selects[fl.key].setOptions(selectOptions(fl), state.f[fl.key]); }); }
    function syncChecks() {
      def.filters.forEach((fl) => { if (fl.type === 'check') { const input = controls[fl.key].querySelector('input'); if (input) input.checked = state.f.status === 'error'; } });
    }
    function change(patch) {
      Object.assign(state.f, patch);
      if ('status' in patch && selects.status) selects.status.set(state.f.status || '');
      syncChecks();
      state.page = 1; persist(); load();
    }
    function persist() {
      const query = { sort: state.sort === 'started_at' ? '' : state.sort, order: state.order === 'desc' ? '' : state.order, p: state.page > 1 ? state.page : '' };
      Object.entries(state.f).forEach(([k, v]) => { query[k] = v; });
      ctx.setQuery(query);
    }
    function params() {
      const p = { sort: state.sort, order: state.order, limit: PAGE_SIZE, offset: (state.page - 1) * PAGE_SIZE };
      Object.entries(state.f).forEach(([k, v]) => { if (v !== '' && v !== null && v !== undefined) p[k] = v; });
      return p;
    }

    /* ---- tabela ---- */
    const table = TA.ui.table({
      columns: def.columns, rows: [], sort: { key: state.sort, order: state.order }, empty: 'Nenhum registro com esses filtros',
      rowId: (r) => r.span_id || r.llm_call_id || r.tool_call_id,
      onRowClick: (r) => { if (r.run_id) ctx.nav('runs/' + r.run_id, r.span_id ? { span: r.span_id } : null); },
      rowClass: (r) => (r.status === 'error' ? 'dx-err' : ''),
      onSort: (key, order) => { state.sort = key; state.order = order; state.page = 1; table.setSort({ key, order }); persist(); load(); },
    });
    tableBox.appendChild(table.el);

    async function load() {
      const my = ++token;
      info.textContent = 'Carregando…';
      try {
        const res = await def.fetch(params());
        if (gone || my !== token) return;
        last = res || { total: 0, items: [] };
        const items = last.items || [];
        items.forEach((r) => {
          addFacet('agent', r.agent); addFacet('purpose', r.purpose); addFacet('model', r.model); addFacet('status', r.status); addFacet('name', r.name); addFacet('kind', r.kind);
        });
        refreshSelects();
        table.setRows(items);
        paintInfo(items);
        TA.util.clear(pagerBox);
        pagerBox.appendChild(TA.ui.pager({ total: last.total || 0, limit: PAGE_SIZE, offset: (state.page - 1) * PAGE_SIZE, onChange: (off) => { state.page = Math.floor(off / PAGE_SIZE) + 1; persist(); load(); tableBox.scrollIntoView && tableBox.scrollIntoView({ block: 'nearest' }); } }));
      } catch (e) {
        if (gone || my !== token) return;
        info.textContent = '';
        TA.util.clear(tableBox); tableBox.appendChild(TA.ui.error(e));
      }
    }

    function paintInfo(items) {
      info.textContent = '';
      const filtered = Object.values(state.f).some((v) => v);
      info.append(h('b', null, TA.fmt.num(last.total || 0)), ` ${def.unit}${filtered ? ' com os filtros atuais' : ' no total'}`,
        h('span', { class: 'faint' }, ` · página ${state.page} de ${Math.max(1, Math.ceil((last.total || 0) / PAGE_SIZE))}`));
      TA.util.clear(totalsBox);
      if (!items.length) return;
      const totals = last.totals && typeof last.totals === 'object' ? null : def.totals(items);
      if (totals) {
        totalsBox.appendChild(h('span', { class: 'dx-totals-h' }, `Totais da página (${items.length})`));
        totals.forEach(([k, v]) => totalsBox.appendChild(h('span', { class: 'dx-total' }, h('span', { class: 'muted' }, k), h('b', { class: 'num' }, v))));
      } else {
        totalsBox.appendChild(h('span', { class: 'dx-totals-h' }, 'Totais do filtro'));
        Object.entries(last.totals).forEach(([k, v]) => totalsBox.appendChild(h('span', { class: 'dx-total' }, h('span', { class: 'muted' }, k.replace(/_/g, ' ')), h('b', { class: 'num' }, typeof v === 'number' ? (/cost/.test(k) ? TA.fmt.cost(v) : /_s$/.test(k) ? TA.fmt.dur(v) : TA.fmt.num(v)) : String(v)))));
      }
    }

    /** um conjunto sem filtros só para alimentar as listas dos selects (agentes, propósitos, tools...) */
    async function loadFacets() {
      try {
        const res = await def.fetch({ limit: 500 });
        if (gone) return;
        ((res && res.items) || []).forEach((r) => { addFacet('agent', r.agent); addFacet('purpose', r.purpose); addFacet('model', r.model); addFacet('status', r.status); addFacet('name', r.name); addFacet('kind', r.kind); });
        refreshSelects();
      } catch (e) { /* os selects continuam só com o que já foi visto */ }
    }

    ctx.onRefresh(() => { load(); loadFacets(); });
    load();
    loadFacets();
    return () => { gone = true; };
  }

  /* ================================================================== EXPLORER DE ARQUIVOS */
  function filesExplorer(ctx, host) {
    const q = ctx.query;
    const state = { run: q.run || '', file: q.file || '', rq: '', fq: q.fq || '' };
    let gone = false, runToken = 0, fileToken = 0;
    let runFiles = null;      // { runId, files: { nome: { size, text, absent, data? } } }
    const enc = encodeURIComponent;

    /* ---- coluna 1: runs ---- */
    const runsList = h('div', { class: 'dx-scroll' }, TA.ui.loading());
    const runSearch = TA.ui.searchInput({ placeholder: 'Buscar run…', onInput: (v) => { state.rq = v; loadRuns(); } });
    const runsCol = h('div', { class: 'dx-col' }, h('div', { class: 'dx-col-head' }, h('div', { class: 'dx-col-title' }, 'Runs'), runSearch.el), runsList);

    /* ---- coluna 2: arquivos ---- */
    const filesList = h('div', { class: 'dx-scroll' }, h('div', { class: 'dx-hint' }, 'Escolha um run.'));
    const filesTitle = h('div', { class: 'dx-col-title' }, 'Arquivos');
    const filesCol = h('div', { class: 'dx-col' }, h('div', { class: 'dx-col-head' }, filesTitle), filesList);

    /* ---- coluna 3: conteúdo ---- */
    const viewerBar = h('div', { class: 'dx-viewbar' });
    const viewerBody = h('div', { class: 'dx-scroll dx-viewbody' }, h('div', { class: 'dx-hint' }, 'Escolha um arquivo para ver o JSON.'));
    const viewer = h('div', { class: 'dx-col' }, viewerBar, viewerBody);

    const inner = TA.ui.split({ left: filesCol, right: viewer, width: 250, min: 180, max: 420, key: 'dx.files2' });
    const root = TA.ui.split({ left: runsCol, right: inner, width: 320, min: 220, max: 520, key: 'dx.files1' });
    host.appendChild(h('div', { class: 'dx-files' }, root));

    /* ---- runs ---- */
    async function loadRuns() {
      try {
        const res = await TA.api.runs({ q: state.rq || undefined, limit: 100, sort: 'started_at', order: 'desc' });
        if (gone) return;
        const items = (res && res.items) || [];
        TA.util.clear(runsList);
        if (state.run && !items.some((r) => r.run_id === state.run)) {
          runsList.appendChild(runItem({ run_id: state.run, user_message: '(run selecionado, fora do filtro atual)' }));
        }
        if (!items.length) runsList.appendChild(TA.ui.empty('Nenhum run', state.rq ? 'Nada com essa busca.' : 'Ainda não há runs rastreados.'));
        items.forEach((r) => runsList.appendChild(runItem(r)));
        if (res && res.total > items.length) runsList.appendChild(h('div', { class: 'dx-hint' }, `Mostrando ${items.length} de ${TA.fmt.num(res.total)} runs. Use a busca para achar outros.`));
      } catch (e) { if (!gone) { TA.util.clear(runsList); runsList.appendChild(TA.ui.error(e)); } }
    }
    function runItem(r) {
      return h('button', { type: 'button', class: ['dx-run', r.run_id === state.run && 'sel'], dataset: { id: r.run_id }, onClick: () => selectRun(r.run_id) },
        h('div', { class: 'dx-run-top' },
          h('span', { class: 'dx-dot lg', style: { background: statusColor(r.status) }, title: TA.util.statusLabel(r.status) }),
          h('span', { class: 'mono xs muted' }, TA.fmt.short(r.run_id)), h('span', { class: 'spacer' }),
          h('span', { class: 'xs muted nowrap' }, r.started_at ? TA.fmt.rel(r.started_at) : '')),
        h('div', { class: 'dx-run-msg' }, TA.fmt.trunc(r.user_message || '(sem mensagem)', 120)),
        h('div', { class: 'dx-run-sub xs muted' }, [r.model, r.total_tokens ? TA.fmt.compact(r.total_tokens) + ' tok.' : null, r.duration_s ? TA.fmt.dur(r.duration_s) : null].filter(Boolean).join(' · ')));
    }
    function statusColor(s) { return { completed: 'var(--ok)', error: 'var(--err)', cancelled: 'var(--warn)', running: 'var(--info)', unfinished: 'var(--warn)' }[s] || 'var(--faint)'; }

    function selectRun(id) {
      if (id === state.run && runFiles) return;
      state.run = id; state.file = state.file && RUN_FILES.includes(state.file) ? state.file : '';
      ctx.setQuery({ run: id, file: state.file, fq: '' });
      state.fq = '';
      Array.from(runsList.querySelectorAll('.dx-run')).forEach((b) => b.classList.toggle('sel', b.dataset.id === id));
      loadRunFiles(id);
    }

    /* ---- arquivos do run: busca os 10 JSONs (texto) para mostrar tamanhos e abrir instantaneamente ---- */
    function loadRunFiles(id) {
      const my = ++runToken;
      runFiles = { runId: id, files: {} };
      TA.util.clear(viewerBar); TA.util.clear(viewerBody);
      viewerBody.appendChild(h('div', { class: 'dx-hint' }, 'Escolha um arquivo para ver o JSON.'));
      filesTitle.textContent = 'Arquivos · ' + TA.fmt.short(id);
      paintFiles();
      RUN_FILES.forEach((name) => {
        fetch(`/api/runs/${enc(id)}/files/${enc(name)}`, { headers: { Accept: 'application/json' } }).then(async (res) => {
          if (gone || my !== runToken) return;
          if (!res.ok) { runFiles.files[name] = { absent: true }; }
          else {
            const text = await res.text();
            if (gone || my !== runToken) return;
            runFiles.files[name] = { text, size: new Blob([text]).size };
          }
          paintFiles();
          if (state.file === name) openFile(name);
        }).catch(() => { if (!gone && my === runToken) { runFiles.files[name] = { absent: true }; paintFiles(); } });
      });
    }
    function paintFiles() {
      TA.util.clear(filesList);
      if (!runFiles) { filesList.appendChild(h('div', { class: 'dx-hint' }, 'Escolha um run.')); return; }
      let total = 0;
      RUN_FILES.forEach((name) => {
        const f = runFiles.files[name];
        if (f && f.size) total += f.size;
        filesList.appendChild(h('button', { type: 'button', class: ['dx-file', name === state.file && 'sel', f && f.absent && 'absent'], disabled: !!(f && f.absent), onClick: () => selectFile(name) },
          TA.ui.icon('file', 'sm'),
          h('span', { class: 'dx-file-main' }, h('span', { class: 'mono' }, name), h('span', { class: 'xs muted' }, FILE_HINT[name] || '')),
          h('span', { class: 'dx-file-size xs num' }, !f ? '…' : f.absent ? 'ausente' : TA.fmt.bytes(f.size))));
      });
      filesList.appendChild(h('div', { class: 'dx-hint' }, 'Total: ' + TA.fmt.bytes(total)));
    }
    function selectFile(name) {
      state.file = name; state.fq = '';
      ctx.setQuery({ file: name, fq: '' });
      paintFiles();
      openFile(name);
    }

    /* ---- visualizador ---- */
    function openFile(name) {
      const f = runFiles && runFiles.files[name];
      const my = ++fileToken;
      TA.util.clear(viewerBar); TA.util.clear(viewerBody);
      if (!f) { viewerBody.appendChild(TA.ui.loading()); return; }
      if (f.absent) { viewerBody.appendChild(TA.ui.empty('Arquivo ausente', 'Este arquivo só é gravado ao fim do run.')); return; }
      if (f.data === undefined) { try { f.data = JSON.parse(f.text); } catch (e) { viewerBody.appendChild(TA.ui.error('JSON inválido: ' + e.message)); return; } }
      const filename = `${TA.fmt.short(runFiles.runId)}_${name}`;
      const content = h('div', { class: 'dx-viewcontent' });
      const hits = h('div', { class: 'dx-hits' });
      const search = TA.ui.searchInput({ placeholder: 'Filtrar caminhos e valores…', value: state.fq, onInput: (v) => { state.fq = v; ctx.setQuery({ fq: v }); paint(); }, delay: 250 });
      search.el.classList.add('dx-fsearch');
      viewerBar.append(
        h('div', { class: 'dx-viewtitle' }, TA.ui.icon('file', 'sm'), h('span', { class: 'mono bold' }, name), h('span', { class: 'muted xs' }, TA.fmt.bytes(f.size) + ' · ' + describe(f.data))),
        h('span', { class: 'spacer' }), search.el,
        TA.ui.copyBtn(() => TA.util.pretty(f.data), 'Copiar'),
        h('button', { class: 'btn sm', title: 'Baixar o arquivo', onClick: () => download(filename, f.text) }, TA.ui.icon('download', 'sm'), 'Baixar'));
      viewerBody.append(hits, content);
      let treeEl = null;
      function paint() {
        if (my !== fileToken) return;
        const term = (state.fq || '').trim();
        TA.util.clear(hits);
        if (!term) {
          hits.classList.add('hidden'); content.classList.remove('hidden');
          if (!treeEl) treeEl = h('div', { class: 'dx-tree' }, TA.ui.jsonTree(f.data, { expand: 1, maxString: 800 }));
          if (!treeEl.parentNode) content.appendChild(treeEl);
          return;
        }
        content.classList.add('hidden'); hits.classList.remove('hidden');
        const res = searchJson(f.data, term);
        hits.appendChild(h('div', { class: 'dx-hits-head' }, h('b', null, TA.fmt.num(res.list.length)), res.capped ? '+ ' : ' ', res.list.length === 1 ? 'resultado' : 'resultados', h('span', { class: 'muted' }, ` para "${term}"`),
          res.capped ? h('span', { class: 'faint' }, ' (limitado)') : null));
        if (!res.list.length) hits.appendChild(TA.ui.empty('Nada encontrado', 'A busca olha nomes de campos e valores.'));
        res.list.forEach((hit) => hits.appendChild(hitRow(hit, term)));
      }
      paint();
    }
    function describe(d) { return Array.isArray(d) ? `${d.length} itens` : d && typeof d === 'object' ? `${Object.keys(d).length} campos` : typeof d; }

    function hitRow(hit, term) {
      const isObj = hit.value !== null && typeof hit.value === 'object';
      const body = h('div', { class: 'dx-hit-body hidden' });
      const row = h('div', { class: 'dx-hit' },
        h('button', { type: 'button', class: 'dx-hit-head', onClick: () => {
          if (!body.firstChild) body.appendChild(TA.ui.jsonTree(hit.value, { expand: 1, maxString: 2000 }));
          body.classList.toggle('hidden');
        } },
          h('span', { class: 'dx-hit-path mono' }, highlight(hit.path, term)),
          h('span', { class: 'dx-hit-val' }, isObj ? h('span', { class: 'faint mono' }, Array.isArray(hit.value) ? `[${hit.value.length}]` : `{${Object.keys(hit.value).length}}`) : highlight(snippet(hit.value, term), term))),
        h('div', { class: 'dx-hit-tools' }, TA.ui.copyBtn(hit.path)), body);
      return row;
    }
    function snippet(v, term) {
      const s = v === null ? 'null' : typeof v === 'string' ? v : String(v);
      const i = s.toLowerCase().indexOf(term.toLowerCase());
      if (s.length <= 200 || i < 0) return TA.fmt.trunc(s, 200);
      const from = Math.max(0, i - 70);
      return (from > 0 ? '…' : '') + s.slice(from, from + 200).replace(/\s+/g, ' ') + '…';
    }
    function highlight(text, term) {
      const s = String(text), low = s.toLowerCase(), t = term.toLowerCase();
      const out = []; let pos = 0, n = 0;
      while (n < 20) {
        const i = low.indexOf(t, pos);
        if (i < 0 || !t) break;
        if (i > pos) out.push(s.slice(pos, i));
        out.push(h('mark', { class: 'dx-mark' }, s.slice(i, i + t.length)));
        pos = i + t.length; n++;
      }
      out.push(s.slice(pos));
      return out;
    }
    /** percorre o JSON atrás de nomes de campos e valores que contenham o termo (limites de resultado e de nós visitados) */
    function searchJson(data, term) {
      const needle = term.toLowerCase(), list = [], seen = new Set();
      const MAX = 300, MAX_VISIT = 300000;
      let visited = 0, capped = false;
      const push = (path, value) => { if (!seen.has(path)) { seen.add(path); list.push({ path, value }); } };
      (function walk(v, path) {
        if (list.length >= MAX) { capped = true; return; }
        if (++visited > MAX_VISIT) { capped = true; return; }
        if (v !== null && typeof v === 'object') {
          const arr = Array.isArray(v);
          for (const k of Object.keys(v)) {
            const p = arr ? `${path}[${k}]` : (path ? path + '.' + k : k);
            if (!arr && k.toLowerCase().includes(needle)) push(p, v[k]);
            walk(v[k], p);
            if (list.length >= MAX) { capped = true; return; }
          }
        } else if (String(v).toLowerCase().includes(needle)) push(path || '(raiz)', v);
      })(data, '');
      return { list, capped };
    }
    function download(name, text) {
      const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
      const a = h('a', { href: url, download: name });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    ctx.onRefresh(() => { loadRuns(); });
    loadRuns();
    if (!RUN_FILES.includes(state.file)) state.file = '';
    if (state.run) loadRunFiles(state.run);   // o arquivo da URL abre assim que chegar
    return () => { gone = true; };
  }
})();
