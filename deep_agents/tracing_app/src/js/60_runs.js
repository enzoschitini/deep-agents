/* View "runs" (#/runs): a tabela de traces estilo LangSmith.
   Filtros, ordenação, colunas e paginação ficam na URL (links compartilháveis); o intervalo de tempo global entra por TA.api.runs. */
(function () {
  const h = TA.h, fmt = TA.fmt, U = TA.util;

  const PAGE_SIZES = [25, 50, 100];
  const DEFAULT_LIMIT = 50;
  const STATUSES = [['completed', 'Concluído'], ['error', 'Erro'], ['cancelled', 'Cancelado'], ['running', 'Em andamento']];
  const DEFAULT_COLS = ['status', 'input', 'when', 'latency', 'tokens', 'cost', 'llm', 'tools'];
  const SORTABLE = ['started_at', 'duration_s', 'total_tokens', 'input_tokens', 'output_tokens', 'cost_usd', 'llm_calls', 'tool_calls', 'ttft_s'];

  /* ---- helpers locais ---- */
  const arr = (v) => (Array.isArray(v) ? v : []);
  const numOr0 = (v) => (typeof v === 'number' && !Number.isNaN(v) ? v : 0);
  function total(items, f) { let s = 0; items.forEach((x) => { s += numOr0(f(x)); }); return s; }
  function median(list) {
    const v = list.filter((x) => typeof x === 'number').sort((a, b) => a - b);
    if (!v.length) return null;
    const m = Math.floor(v.length / 2);
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  }
  const dash = () => h('span', { class: 'faint' }, '—');

  /* ---- definição das colunas ----
     render(r, env) -> Node | string; sort = chave aceita pela API (ou null); align 'r' = numérica */
  const COLS = [
    {
      id: 'status', label: 'Status', width: '124px',
      render(r) {
        const b = TA.ui.statusBadge(r.status);
        if (r.status === 'running') b.classList.add('rv-running');
        const extra = r.status !== 'error' && numOr0(r.errors) > 0
          ? TA.ui.badge(`${r.errors} ${r.errors > 1 ? 'erros' : 'erro'}`, 'warn', 'Houve erros durante o run') : null;
        return h('div', { class: 'rv-status' }, b, extra);
      },
    },
    {
      id: 'input', label: 'Entrada',
      render(r) {
        const href = TA.router.hashFor('runs/' + r.run_id);
        return h('div', { class: 'rv-in' },
          h('a', { class: 'rv-in-q truncate', href, title: r.user_message || '' }, fmt.trunc(r.user_message, 160) || '(sem mensagem)'),
          r.answer_preview ? h('div', { class: 'rv-in-a truncate' }, fmt.trunc(r.answer_preview, 180)) : null);
      },
    },
    {
      id: 'when', label: 'Quando', sort: 'started_at', width: '110px',
      render(r) { return h('span', { class: 'nowrap', title: fmt.datetime(r.started_at) }, fmt.rel(r.started_at)); },
    },
    {
      id: 'latency', label: 'Latência', sort: 'duration_s', width: '150px',
      render(r, env) {
        if (typeof r.duration_s !== 'number') return r.status === 'running' ? h('span', { class: 'muted' }, 'em curso…') : dash();
        const pct = env.maxDur > 0 ? U.clamp((r.duration_s / env.maxDur) * 100, 2, 100) : 0;
        return h('div', { class: 'rv-lat' },
          h('span', { class: 'rv-lat-v num' }, fmt.dur(r.duration_s)),
          h('span', { class: 'rv-lat-bar' }, h('i', { class: r.status === 'error' ? 'err' : '', style: { width: pct + '%' } })));
      },
    },
    {
      id: 'ttft', label: 'TTFT', sort: 'ttft_s', align: 'r', title: 'Tempo até o primeiro token',
      render(r) { return typeof r.ttft_s === 'number' ? fmt.dur(r.ttft_s) : dash(); },
    },
    {
      id: 'tokens', label: 'Tokens', sort: 'total_tokens', align: 'r', title: 'Entrada → saída (total no tooltip)',
      render(r) {
        if (r.input_tokens == null && r.output_tokens == null) return dash();
        const el = h('span', { class: 'nowrap' }, `${fmt.compact(r.input_tokens)} → ${fmt.compact(r.output_tokens)}`);
        const total_ = r.total_tokens != null ? r.total_tokens : numOr0(r.input_tokens) + numOr0(r.output_tokens);
        let tip = `Total: ${fmt.num(total_)}\nEntrada: ${fmt.num(r.input_tokens)}\nSaída: ${fmt.num(r.output_tokens)}`;
        if (numOr0(r.cache_read_tokens) > 0) tip += `\nCache lido: ${fmt.num(r.cache_read_tokens)}`;
        return TA.ui.tip(el, tip);
      },
    },
    {
      id: 'cost', label: 'Custo', sort: 'cost_usd', align: 'r',
      render(r) { return r.cost_usd == null ? dash() : fmt.cost(r.cost_usd); },
    },
    {
      id: 'llm', label: 'LLM', sort: 'llm_calls', align: 'r', title: 'Chamadas ao modelo',
      render(r) { return r.llm_calls == null ? dash() : fmt.num(r.llm_calls); },
    },
    {
      id: 'tools', label: 'Tools', sort: 'tool_calls', align: 'r', title: 'Chamadas a tools',
      render(r) {
        if (r.tool_calls == null) return dash();
        const el = h('span', { class: ['nowrap', numOr0(r.tool_calls) ? '' : 'faint'] }, fmt.num(r.tool_calls));
        const names = arr(r.tools);
        if (!names.length) return el;
        return TA.ui.tip(el, h('div', { class: 'rv-tipchips' }, names.map((n) => h('span', { class: 'rv-tipchip' }, n))));
      },
    },
    {
      id: 'subagents', label: 'Subagents', align: 'r',
      render(r) { return r.subagent_calls ? fmt.num(r.subagent_calls) : h('span', { class: 'faint' }, r.subagent_calls == null ? '—' : '0'); },
    },
    {
      id: 'model', label: 'Modelo',
      render(r) { return r.model ? h('span', { class: 'chip mono', title: r.model }, fmt.trunc(r.model, 28)) : dash(); },
    },
    {
      id: 'session', label: 'Sessão',
      render(r) {
        if (!r.session_id) return dash();
        return h('span', { class: 'nowrap' },
          TA.router.link('sessions/' + r.session_id, null, h('span', { class: 'mono' }, fmt.short(r.session_id))),
          r.turn != null ? h('span', { class: 'muted xs' }, ` · turno ${r.turn}`) : null);
      },
    },
    {
      id: 'origin', label: 'Origem',
      render(r) { return r.origin ? h('span', { class: 'chip' }, r.origin) : dash(); },
    },
    {
      id: 'runid', label: 'Run ID',
      render(r) {
        return h('span', { class: 'rv-idcell nowrap' }, h('span', { class: 'mono muted', title: r.run_id }, fmt.short(r.run_id)), TA.ui.copyBtn(r.run_id));
      },
    },
  ];
  const COL_BY_ID = Object.fromEntries(COLS.map((c) => [c.id, c]));

  /* ================================================================== view */
  TA.views.runs = {
    mount(ctx) {
      const q0 = ctx.query || {};
      const savedCols = U.store.get('runs.cols', null);
      const visible = new Set((Array.isArray(savedCols) ? savedCols : DEFAULT_COLS).filter((id) => COL_BY_ID[id]));
      if (!visible.size) DEFAULT_COLS.forEach((id) => visible.add(id));

      const lim0 = parseInt(q0.limit, 10);
      const st = {
        q: q0.q || '', status: q0.status || '', model: q0.model || '', session: q0.session || '', origin: q0.origin || '', tool: q0.tool || '',
        since: q0.since || '', until: q0.until || '',   // recorte de tempo vindo de links (ex.: barras do dashboard); vence o intervalo global
        errors: q0.errors === '1' || q0.errors === 'true',
        sort: SORTABLE.includes(q0.sort) ? q0.sort : 'started_at',
        order: q0.order === 'asc' ? 'asc' : 'desc',
        offset: Math.max(0, parseInt(q0.offset, 10) || 0),
        limit: PAGE_SIZES.includes(lim0) ? lim0 : (PAGE_SIZES.includes(U.store.get('runs.limit', DEFAULT_LIMIT)) ? U.store.get('runs.limit', DEFAULT_LIMIT) : DEFAULT_LIMIT),
      };

      let data = null;          // última resposta de /api/runs
      let items = [];
      let loadError = null;
      let seq = 0;
      let selId = null;         // run selecionado pelo teclado
      let rowEls = [];          // [{id, el}]
      let timer = null;
      const seen = { model: new Set(), origin: new Set(), session: new Set(), tool: new Set() };   // opções já vistas (os facets podem sumir com o filtro)
      let statusSeen = {};

      /* ---------------------------------------------------------- estrutura fixa */
      const countEl = h('span', { class: 'rv-count' });
      const search = TA.ui.searchInput({ placeholder: 'Buscar em mensagem, resposta ou run id…   ( / )', value: st.q, onInput: (v) => { st.q = v; st.offset = 0; changed(); } });
      search.input.setAttribute('aria-label', 'Buscar traces');
      const chipsEl = h('div', { class: 'rv-chips', role: 'group', 'aria-label': 'Filtrar por status' });

      const mkSelect = (key, label) => {
        const s = TA.ui.select({
          options: [{ value: '', label }], value: st[key], title: label,
          onChange: (v) => { st[key] = v; st.offset = 0; changed(); },
        });
        s.el.classList.add('rv-select');
        return s;
      };
      const selects = {
        model: mkSelect('model', 'Todos os modelos'),
        session: mkSelect('session', 'Todas as sessões'),
        origin: mkSelect('origin', 'Todas as origens'),
        tool: mkSelect('tool', 'Todas as tools'),
      };
      const errCheck = TA.ui.check({ label: 'Só com erros', checked: st.errors, onChange: (v) => { st.errors = v; st.offset = 0; changed(); } });
      const rangeChip = h('span', { class: 'chip hidden', title: 'Recorte de tempo vindo de um link' });
      const clearBtn = h('button', { class: 'btn sm ghost hidden', type: 'button', onClick: clearFilters }, TA.ui.icon('x', 'sm'), 'Limpar filtros');

      const menuEl = h('div', { class: 'rv-menu hidden', role: 'menu' });
      const menuBtn = h('button', { class: 'btn sm', type: 'button', 'aria-haspopup': 'true', onClick: (e) => { e.stopPropagation(); toggleMenu(); } },
        TA.ui.icon('list', 'sm'), 'Colunas');
      const menuWrap = h('div', { class: 'rv-menuwrap' }, menuBtn, menuEl);

      const summaryEl = h('div', { class: 'rv-summary' });
      const wrap = h('div', { class: 'table-wrap rv-tablewrap' });
      const footEl = h('div', { class: 'rv-foot' });

      const page = h('div', { class: 'page rv' },
        h('div', { class: 'page-head' },
          h('div', null, h('h1', null, 'Traces ', countEl), h('div', { class: 'sub' }, 'Cada trace é uma resposta do agente, do pedido do usuário até o texto final.')),
          h('span', { class: 'spacer' }), menuWrap),
        h('div', { class: 'rv-bar' }, search.el, chipsEl),
        h('div', { class: 'rv-bar' }, selects.model.el, selects.session.el, selects.origin.el, selects.tool.el, errCheck, rangeChip, h('span', { class: 'spacer' }), clearBtn),
        summaryEl, wrap, footEl);

      ctx.el.appendChild(page);
      ctx.crumbs([{ label: 'Traces' }]);
      ctx.actions([]);

      /* ---------------------------------------------------------- URL */
      function sync() {
        ctx.setQuery({
          q: st.q, status: st.status, model: st.model, session: st.session, origin: st.origin, tool: st.tool,
          errors: st.errors ? '1' : null, since: st.since || null, until: st.until || null,
          sort: st.sort === 'started_at' ? null : st.sort,
          order: st.order === 'desc' ? null : st.order,
          offset: st.offset || null,
          limit: st.limit === DEFAULT_LIMIT ? null : st.limit,
        });
      }
      function changed() { sync(); load(); }
      function hasFilters() { return !!(st.q || st.status || st.model || st.session || st.origin || st.tool || st.errors || st.since || st.until); }
      function paintRange() {
        const on = !!(st.since || st.until);
        rangeChip.classList.toggle('hidden', !on);
        U.clear(rangeChip);
        if (on) rangeChip.append(TA.ui.icon('clock', 'sm'), `${st.since ? TA.fmt.datetime(st.since) : '…'} → ${st.until ? TA.fmt.datetime(st.until) : '…'}`);
      }
      function clearFilters() {
        st.q = st.status = st.model = st.session = st.origin = st.tool = st.since = st.until = ''; st.errors = false; st.offset = 0; paintRange();
        search.set(''); errCheck.querySelector('input').checked = false;
        changed();
      }

      /* ---------------------------------------------------------- carregamento */
      async function load(silent) {
        const my = ++seq;
        clearTimeout(timer);
        if (!silent) wrap.classList.add('rv-busy');
        if (!data && !silent) { U.clear(wrap); wrap.appendChild(TA.ui.loading()); }
        try {
          const params = {
            q: st.q, status: st.status, model: st.model, session: st.session, origin: st.origin, tool: st.tool,
            has_errors: st.errors ? 1 : null, sort: st.sort, order: st.order, limit: st.limit, offset: st.offset,
          };
          if (st.since) params.since = st.since;   // só sobrescreve o intervalo global quando o link trouxe um recorte
          if (st.until) params.until = st.until;
          const res = await TA.api.runs(params);
          if (my !== seq) return;
          data = res || {};
          items = arr(data.items);
          loadError = null;
          if (st.offset > 0 && !items.length && numOr0(data.total) > 0) {   // página além do fim (filtro mudou)
            st.offset = 0; sync(); return load();
          }
          absorbFacets();
        } catch (e) {
          if (my !== seq) return;
          loadError = e;
        }
        wrap.classList.remove('rv-busy');
        paint();
        if (items.some((r) => r.status === 'running')) timer = setTimeout(() => load(true), 5000);   // acompanha runs em andamento
      }

      function absorbFacets() {
        const f = (data && data.facets) || {};
        ['model', 'origin', 'session'].forEach((k) => Object.keys(f[k] || {}).forEach((v) => seen[k].add(v)));
        arr(data && data.items).forEach((r) => arr(r.tools).forEach((t) => seen.tool.add(t)));
        const ss = f.status || {};
        if (!st.status) statusSeen = { ...ss };
        else statusSeen = { ...statusSeen, ...ss };
        const m = TA.state.meta;
        if (m) { arr(m.models).forEach((x) => seen.model.add(x)); arr(m.origins).forEach((x) => seen.origin.add(x)); }
      }

      let toolsLoaded = false;
      function loadToolOptions() {   // nomes de tools de todos os runs (a lista da página só mostra as da página)
        if (toolsLoaded) return;
        toolsLoaded = true;
        TA.api.stats().then((s) => {
          arr(s && s.by_tool).forEach((t) => { const n = t && (t.name || t.tool || t.key); if (n) seen.tool.add(n); });
          paintSelects();
        }).catch(() => { /* só enriquece as opções */ });
      }

      /* ---------------------------------------------------------- pintura */
      function paint() {
        countEl.textContent = data ? fmt.num(data.total) : '';
        paintChips();
        paintSelects();
        clearBtn.classList.toggle('hidden', !hasFilters());
        paintSummary();
        paintTable();
        paintFoot();
      }

      function paintChips() {
        U.clear(chipsEl);
        const cur = (data && data.facets && data.facets.status) || {};
        const sumAll = Object.values(statusSeen).reduce((s, n) => s + numOr0(n), 0);
        const mk = (key, label, count) => {
          const on = st.status === key;
          return h('button', {
            type: 'button', class: ['rv-chip', key && 'k-' + key, on && 'on'], 'aria-pressed': on ? 'true' : 'false',
            onClick: () => { st.status = on ? '' : key; st.offset = 0; changed(); },
          }, key ? h('span', { class: 'dot' }) : null, label, count === null || count === undefined ? null : h('span', { class: 'n' }, fmt.compact(count)));
        };
        chipsEl.appendChild(mk('', 'Todos', st.status ? null : (data ? sumAll || data.total : null)));
        STATUSES.forEach(([k, label]) => {
          let c = cur[k];
          if (!data) c = null;
          else if (c === undefined) c = st.status && st.status !== k ? statusSeen[k] : (st.status === k ? null : 0);
          chipsEl.appendChild(mk(k, label, c));
        });
      }

      function paintSelects() {
        const f = (data && data.facets) || {};
        const build = (key, allLabel, plural) => {
          const counts = key === 'tool' ? {} : (f[key] || {});
          const names = Array.from(seen[key]);
          if (st[key] && !names.includes(st[key])) names.push(st[key]);
          names.sort((a, b) => (numOr0(counts[b]) - numOr0(counts[a])) || String(a).localeCompare(String(b)));
          const shown = key === 'session' ? names.slice(0, 80) : names;
          if (st[key] && !shown.includes(st[key])) shown.push(st[key]);
          const opts = [{ value: '', label: allLabel }].concat(shown.map((n) => ({
            value: n,
            label: (key === 'session' ? fmt.short(n) : n) + (counts[n] !== undefined ? ` (${fmt.compact(counts[n])})` : ''),
          })));
          selects[key].setOptions(opts, st[key]);
          selects[key].el.classList.toggle('on', !!st[key]);
          selects[key].el.title = plural;
        };
        build('model', 'Todos os modelos', 'Modelo');
        build('session', 'Todas as sessões', 'Sessão');
        build('origin', 'Todas as origens', 'Origem');
        build('tool', 'Todas as tools', 'Ferramenta usada');
      }

      function paintSummary() {
        U.clear(summaryEl);
        if (!data || loadError || !items.length) return;
        const tin = total(items, (r) => r.input_tokens), tout = total(items, (r) => r.output_tokens);
        const cost = total(items, (r) => r.cost_usd);
        const nErr = items.filter((r) => r.status === 'error' || numOr0(r.errors) > 0).length;
        const med = median(items.map((r) => r.duration_s));
        const it = (...c) => h('span', { class: 'rv-sum-item' }, ...c);
        summaryEl.append(
          it(h('b', null, fmt.num(data.total)), ` ${data.total === 1 ? 'run' : 'runs'}`, hasFilters() ? ' (filtrados)' : ''),
          it('nesta página: ', h('b', null, fmt.compact(tin + tout)), ' tokens ', h('span', { class: 'muted' }, `(${fmt.compact(tin)} in / ${fmt.compact(tout)} out)`)),
          it(h('b', null, fmt.cost(cost))),
          it(h('b', { class: nErr ? 'rv-err-n' : '' }, String(nErr)), nErr === 1 ? ' com erro' : ' com erros'),
          med !== null ? it('latência mediana ', h('b', null, fmt.dur(med))) : null);
      }

      function paintTable() {
        U.clear(wrap);
        rowEls = [];
        if (loadError) {
          wrap.appendChild(TA.ui.error(loadError));
          wrap.appendChild(h('div', { class: 'rv-retry' }, h('button', { class: 'btn sm', type: 'button', onClick: () => load() }, 'Tentar de novo')));
          return;
        }
        if (!items.length) {
          const e = TA.ui.empty(hasFilters() ? 'Nenhum trace com esses filtros' : 'Nenhum trace ainda',
            hasFilters() ? 'Tente afastar o intervalo de tempo ou remover algum filtro.' : 'Converse com o agente (CLI ou web) e os runs aparecem aqui.');
          if (hasFilters()) e.appendChild(h('div', { style: 'margin-top:12px' }, h('button', { class: 'btn', type: 'button', onClick: clearFilters }, 'Limpar filtros')));
          wrap.appendChild(e);
          return;
        }
        const cols = COLS.filter((c) => visible.has(c.id));
        const env = { maxDur: Math.max(0, ...items.map((r) => numOr0(r.duration_s))) };
        const head = h('tr', null, cols.map(thFor));
        const body = items.map((r, i) => rowFor(r, i, cols, env));
        wrap.appendChild(h('table', { class: 't rv-table' }, h('thead', null, head), h('tbody', null, body)));
        if (selId) { const idx = items.findIndex((r) => r.run_id === selId); if (idx >= 0) markSel(idx, false); else selId = null; }
      }

      function thFor(c) {
        const sortable = !!c.sort;
        const on = sortable && st.sort === c.sort;
        const content = sortable
          ? h('button', { type: 'button', class: 'rv-th', onClick: () => sortBy(c.sort) },
            c.label, h('span', { class: ['rv-arrow', on && 'on'] }, on ? (st.order === 'asc' ? '↑' : '↓') : '↕'))
          : c.label;
        return h('th', {
          class: [c.align === 'r' && 'r', sortable && 'sortable', on && 'rv-sorted'], title: c.title,
          style: c.width ? { width: c.width } : null, 'aria-sort': on ? (st.order === 'asc' ? 'ascending' : 'descending') : null,
        }, content);
      }

      function rowFor(r, i, cols, env) {
        const tr = h('tr', {
          class: ['clickable', 'rv-row', r.status === 'error' && 'rv-err', r.status !== 'error' && numOr0(r.errors) > 0 && 'rv-warn', r.status === 'running' && 'rv-run'],
          'data-id': r.run_id,
          onClick: (e) => {
            if (e.target && e.target.closest && e.target.closest('a,button')) return;
            markSel(i, false); openRun(r);
          },
        }, cols.map((c) => {
          let content;
          try { content = c.render(r, env); } catch (e) { content = dash(); console.error('[runs] coluna', c.id, e); }
          return h('td', { class: [c.align === 'r' && 'r num', 'rv-c-' + c.id] }, content);
        }));
        rowEls.push({ id: r.run_id, el: tr });
        return tr;
      }

      function paintFoot() {
        U.clear(footEl);
        if (!data || loadError || !items.length) return;
        const pager = TA.ui.pager({
          total: numOr0(data.total), limit: st.limit, offset: st.offset,
          onChange: (o) => { st.offset = o; sync(); load(); wrap.scrollTop = 0; },
        });
        pager.classList.add('rv-pager');
        const size = TA.ui.select({
          options: PAGE_SIZES.map((n) => ({ value: String(n), label: `${n} por página` })), value: String(st.limit), title: 'Itens por página',
          onChange: (v) => { st.limit = parseInt(v, 10) || DEFAULT_LIMIT; U.store.set('runs.limit', st.limit); st.offset = 0; changed(); },
        });
        size.el.classList.add('rv-select');
        footEl.append(pager, size.el);
      }

      /* ---------------------------------------------------------- ações */
      function sortBy(key) {
        if (st.sort === key) st.order = st.order === 'desc' ? 'asc' : 'desc';
        else { st.sort = key; st.order = 'desc'; }
        st.offset = 0;
        changed();
      }
      function openRun(r) { if (r && r.run_id) ctx.nav('runs/' + r.run_id); }

      /* seleção por teclado */
      function markSel(idx, scroll) {
        rowEls.forEach((x) => x.el.classList.remove('sel'));
        const x = rowEls[idx];
        if (!x) return;
        x.el.classList.add('sel');
        selId = x.id;
        if (scroll && x.el.scrollIntoView) x.el.scrollIntoView({ block: 'nearest' });
      }
      function moveSel(delta) {
        if (!rowEls.length) return;
        let idx = rowEls.findIndex((x) => x.id === selId);
        idx = idx < 0 ? (delta > 0 ? 0 : rowEls.length - 1) : U.clamp(idx + delta, 0, rowEls.length - 1);
        markSel(idx, true);
      }

      function onKey(e) {
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        const t = e.target;
        const typing = !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
        if (e.key === '/' && !typing) { e.preventDefault(); search.input.focus(); return; }
        if (e.key === 'Escape') {
          if (!menuEl.classList.contains('hidden')) { closeMenu(); return; }
          if (typing && t.blur) t.blur();
          return;
        }
        if (typing) return;
        if (e.key === 'ArrowDown') { e.preventDefault(); moveSel(1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); moveSel(-1); }
        else if (e.key === 'Enter') {
          if (t && t.closest && t.closest('a,button')) return;
          const r = items.find((x) => x.run_id === selId);
          if (r) { e.preventDefault(); openRun(r); }
        }
      }

      /* menu de colunas */
      function paintMenu() {
        U.clear(menuEl);
        menuEl.appendChild(h('div', { class: 'rv-menu-title' }, 'Colunas visíveis'));
        COLS.forEach((c) => {
          menuEl.appendChild(TA.ui.check({
            label: c.label, checked: visible.has(c.id),
            onChange: (on) => {
              if (on) visible.add(c.id); else visible.delete(c.id);
              if (!visible.size) { visible.add(c.id); paintMenu(); }
              U.store.set('runs.cols', COLS.filter((x) => visible.has(x.id)).map((x) => x.id));
              paintTable();
            },
          }));
        });
        menuEl.appendChild(h('button', {
          class: 'btn sm ghost', type: 'button',
          onClick: () => { visible.clear(); DEFAULT_COLS.forEach((id) => visible.add(id)); U.store.set('runs.cols', DEFAULT_COLS.slice()); paintMenu(); paintTable(); },
        }, 'Restaurar padrão'));
      }
      function toggleMenu() {
        if (menuEl.classList.contains('hidden')) { paintMenu(); menuEl.classList.remove('hidden'); } else closeMenu();
      }
      function closeMenu() { menuEl.classList.add('hidden'); }
      const onDocDown = (e) => { if (!menuEl.classList.contains('hidden') && !menuWrap.contains(e.target)) closeMenu(); };

      document.addEventListener('keydown', onKey);
      document.addEventListener('mousedown', onDocDown);
      ctx.onCleanup(() => {
        document.removeEventListener('keydown', onKey);
        document.removeEventListener('mousedown', onDocDown);
        clearTimeout(timer);
        seq++;   // descarta respostas em voo
      });
      ctx.onRefresh(() => load());

      paintChips(); paintSelects();
      loadToolOptions();
      paintRange();
      load();
    },
  };
})();
