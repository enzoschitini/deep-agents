/* Views "sessions" (#/sessions) e "session" (#/sessions/:id): lista de conversas (threads) e a conversa em linha do tempo. */
(function () {
  const h = TA.h, fmt = TA.fmt, U = TA.util;

  /* ---- helpers locais ---- */
  const arr = (v) => (Array.isArray(v) ? v : []);
  const numOr0 = (v) => (typeof v === 'number' && !Number.isNaN(v) ? v : 0);
  const dash = () => h('span', { class: 'faint' }, '—');
  const plural = (n, one, many) => `${fmt.num(n)} ${n === 1 ? one : many}`;
  /** "25/11 14:30" */
  function shortDT(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  }
  /** texto de um `content` que pode ser string ou lista de blocos */
  function textOf(content) {
    if (content === null || content === undefined) return '';
    if (typeof content === 'string') return content;
    if (Array.isArray(content)) {
      return content.map((b) => (typeof b === 'string' ? b : (b && typeof b.text === 'string' ? b.text : ''))).filter(Boolean).join('\n\n');
    }
    if (typeof content.text === 'string') return content.text;
    return U.pretty(content);
  }
  const tot = (s) => (s && s.totals) || {};
  const sTokens = (s) => numOr0(tot(s).input_tokens) + numOr0(tot(s).output_tokens);

  /* ================================================================== lista de sessões */
  const SORTS = {
    last_run_at: (s) => s.last_run_at || '',
    started_at: (s) => s.started_at || '',
    n_runs: (s) => numOr0(s.n_runs),
    calls: (s) => numOr0(tot(s).llm_calls) + numOr0(tot(s).tool_calls),
    tokens: (s) => sTokens(s),
    cost: (s) => numOr0(tot(s).cost_usd),
    n_errors: (s) => numOr0(s.n_errors),
    duration_s: (s) => numOr0(s.duration_s),
  };

  TA.views.sessions = {
    mount(ctx) {
      const q0 = ctx.query || {};
      const st = {
        q: q0.q || '',
        sort: SORTS[q0.sort] ? q0.sort : 'last_run_at',
        order: q0.order === 'asc' ? 'asc' : 'desc',
      };
      let all = [];
      let seq = 0;

      const countEl = h('span', { class: 'sv-count' });
      const summaryEl = h('div', { class: 'sv-summary' });
      const body = h('div', { class: 'sv-listbody' });
      const search = TA.ui.searchInput({
        placeholder: 'Buscar por mensagem, modelo ou id…', value: st.q,
        onInput: (v) => { st.q = v; sync(); paint(); },
      });
      search.input.setAttribute('aria-label', 'Buscar sessões');

      ctx.el.appendChild(h('div', { class: 'page sv' },
        h('div', { class: 'page-head' },
          h('div', null, h('h1', null, 'Sessões ', countEl), h('div', { class: 'sub' }, 'Uma sessão é uma conversa: cada turno dela é um trace.')),
          h('span', { class: 'spacer' }), search.el),
        summaryEl, body));
      ctx.crumbs([{ label: 'Sessões' }]);
      ctx.actions([]);

      function sync() {
        ctx.setQuery({ q: st.q, sort: st.sort === 'last_run_at' ? null : st.sort, order: st.order === 'desc' ? null : st.order });
      }

      const columns = [
        {
          key: 'first_message', label: 'Conversa',
          render(s) {
            return h('div', { class: 'sv-first' },
              h('div', { class: 'sv-first-t truncate', title: s.first_message || '' }, fmt.trunc(s.first_message, 150) || '(sem mensagem)'),
              h('div', { class: 'sv-first-id mono' }, fmt.short(s.session_id, 12)));
          },
        },
        { key: 'n_runs', label: 'Turnos', sortable: true, align: 'r', render: (s) => (s.n_runs == null ? dash() : fmt.num(s.n_runs)) },
        {
          key: 'models', label: 'Modelos',
          render(s) {
            const m = arr(s.models);
            if (!m.length) return dash();
            return h('span', { class: 'sv-models' }, m.slice(0, 2).map((x) => h('span', { class: 'chip mono', title: x }, fmt.trunc(x, 24))),
              m.length > 2 ? h('span', { class: 'chip', title: m.slice(2).join('\n') }, `+${m.length - 2}`) : null);
          },
        },
        {
          key: 'last_run_at', label: 'Período', sortable: true,
          render(s) {
            return h('div', { class: 'sv-period', title: `${fmt.datetime(s.started_at)} → ${fmt.datetime(s.last_run_at)}` },
              h('span', { class: 'nowrap' }, `${shortDT(s.started_at)} → ${shortDT(s.last_run_at)}`),
              h('span', { class: 'muted xs' }, fmt.rel(s.last_run_at)));
          },
        },
        {
          key: 'calls', label: 'Chamadas', sortable: true, align: 'r', title: 'LLM / tools',
          render(s) { const t = tot(s); return h('span', { class: 'nowrap' }, `${fmt.num(numOr0(t.llm_calls))} / ${fmt.num(numOr0(t.tool_calls))}`); },
        },
        {
          key: 'tokens', label: 'Tokens', sortable: true, align: 'r', title: 'Entrada → saída',
          render(s) {
            const t = tot(s);
            const el = h('span', { class: 'nowrap' }, `${fmt.compact(t.input_tokens)} → ${fmt.compact(t.output_tokens)}`);
            return TA.ui.tip(el, `Total: ${fmt.num(sTokens(s))}`);
          },
        },
        { key: 'cost', label: 'Custo', sortable: true, align: 'r', render: (s) => (tot(s).cost_usd == null ? dash() : fmt.cost(tot(s).cost_usd)) },
        {
          key: 'n_errors', label: 'Erros', sortable: true, align: 'r',
          render: (s) => (numOr0(s.n_errors) > 0 ? TA.ui.badge(String(s.n_errors), 'err') : h('span', { class: 'faint' }, '0')),
        },
        { key: 'duration_s', label: 'Duração', sortable: true, align: 'r', render: (s) => (typeof s.duration_s === 'number' ? fmt.dur(s.duration_s) : dash()) },
      ];

      let table = null;
      function filtered() {
        const q = st.q.toLowerCase();
        let rows = all;
        if (q) {
          rows = all.filter((s) => `${s.first_message || ''} ${s.session_id || ''} ${arr(s.models).join(' ')}`.toLowerCase().includes(q));
        }
        const key = SORTS[st.sort];
        const dir = st.order === 'asc' ? 1 : -1;
        return rows.slice().sort((a, b) => {
          const x = key(a), y = key(b);
          return x < y ? -dir : x > y ? dir : 0;
        });
      }

      function paint() {
        const rows = filtered();
        countEl.textContent = all.length ? fmt.num(rows.length === all.length ? all.length : rows.length) : '';
        U.clear(summaryEl);
        if (rows.length) {
          const turns = rows.reduce((s, x) => s + numOr0(x.n_runs), 0);
          const tokens = rows.reduce((s, x) => s + sTokens(x), 0);
          const cost = rows.reduce((s, x) => s + numOr0(tot(x).cost_usd), 0);
          const errs = rows.reduce((s, x) => s + numOr0(x.n_errors), 0);
          const it = (...c) => h('span', { class: 'sv-sum-item' }, ...c);
          summaryEl.append(
            it(h('b', null, fmt.num(rows.length)), rows.length === 1 ? ' sessão' : ' sessões'),
            it(h('b', null, fmt.num(turns)), turns === 1 ? ' turno' : ' turnos'),
            it(h('b', null, fmt.compact(tokens)), ' tokens'),
            it(h('b', null, fmt.cost(cost))),
            it(h('b', { class: errs ? 'sv-err-n' : '' }, fmt.num(errs)), errs === 1 ? ' erro' : ' erros'));
        }
        const sort = { key: st.sort, order: st.order };
        if (table) { table.setRows(rows); table.setSort(sort); return; }
        U.clear(body);
        table = TA.ui.table({
          columns, rows, sort, empty: st.q ? 'Nenhuma sessão com essa busca' : 'Nenhuma sessão no intervalo',
          onRowClick: (s) => ctx.nav('sessions/' + s.session_id),
          rowClass: (s) => (numOr0(s.n_errors) > 0 ? 'sv-row-err' : ''),
          onSort: (key, order) => { st.sort = SORTS[key] ? key : st.sort; st.order = order; sync(); paint(); },
        });
        body.appendChild(table.el);
      }

      async function load() {
        const my = ++seq;
        if (!all.length) { U.clear(body); table = null; body.appendChild(TA.ui.loading()); }
        try {
          const res = await TA.api.sessions();
          if (my !== seq) return;
          all = arr(res && res.items);
          if (table === null) U.clear(body);
          paint();
        } catch (e) {
          if (my !== seq) return;
          table = null;
          U.clear(body); body.appendChild(TA.ui.error(e));
        }
      }
      ctx.onCleanup(() => { seq++; });
      ctx.onRefresh(load);
      load();
    },
  };

  /* ================================================================== detalhe da sessão */
  const METRICS = [
    { value: 'latency', label: 'Latência', get: (r) => r.duration_s, fmt: (v) => fmt.dur(v) },
    { value: 'tokens', label: 'Tokens', get: (r) => (r.total_tokens != null ? r.total_tokens : numOr0(r.input_tokens) + numOr0(r.output_tokens)), fmt: (v) => fmt.num(v) },
    { value: 'cost', label: 'Custo', get: (r) => r.cost_usd, fmt: (v) => fmt.cost(v) },
  ];

  function bubbleBody(text, md) {
    if (md && TA.ui.markdown) {
      try { return h('div', { class: 'sv-md' }, TA.ui.markdown(text)); } catch (e) { console.error('[session] markdown', e); }
    }
    return h('div', { class: 'sv-plain' }, text);
  }

  /** bolha de mensagem; textos longos começam recolhidos */
  function bubble(kind, text, { md, title } = {}) {
    const av = h('div', { class: 'sv-av', title }, TA.ui.icon(kind === 'user' ? 'user' : 'bot'));
    const inner = bubbleBody(text, md);
    const box = h('div', { class: ['sv-bubble', kind === 'ai' && 'sv-bubble-ai'] }, inner);
    const long = text.length > 1400 || text.split('\n').length > 22;
    if (long) {
      box.classList.add('sv-clamped');
      const btn = h('button', { type: 'button', class: 'btn sm sv-more' }, 'Mostrar tudo');
      btn.addEventListener('click', () => {
        const open = box.classList.toggle('sv-clamped');
        btn.textContent = open ? 'Mostrar tudo' : 'Recolher';
      });
      box.appendChild(btn);
    }
    return h('div', { class: ['sv-msg', 'sv-msg-' + kind] }, av, box);
  }

  function stat(icon, text, title, cls) {
    return h('span', { class: ['sv-stat', cls], title }, icon ? TA.ui.icon(icon, 'sm') : null, text);
  }

  TA.views.session = {
    mount(ctx) {
      const id = ctx.params.id;
      const root = h('div', { class: 'page sv sv-detail' });
      ctx.el.appendChild(root);
      ctx.crumbs([{ label: 'Sessões', href: TA.router.hashFor('sessions') }, { label: fmt.short(id, 12) }]);
      ctx.actions([]);
      let seq = 0;
      let metric = U.store.get('session.metric', 'latency');
      if (!METRICS.some((m) => m.value === metric)) metric = 'latency';

      function render(data) {
        U.clear(root);
        const s = (data && data.session) || {};
        const runs = arr(data && data.runs).slice().sort((a, b) => (numOr0(a.turn) - numOr0(b.turn)) || String(a.started_at || '').localeCompare(String(b.started_at || '')));
        const messages = arr(data && data.messages);

        // totais: usa os da sessão e completa com os runs se faltar
        const t = { ...tot(s) };
        if (t.input_tokens == null) t.input_tokens = runs.reduce((x, r) => x + numOr0(r.input_tokens), 0);
        if (t.output_tokens == null) t.output_tokens = runs.reduce((x, r) => x + numOr0(r.output_tokens), 0);
        if (t.cost_usd == null && runs.some((r) => r.cost_usd != null)) t.cost_usd = runs.reduce((x, r) => x + numOr0(r.cost_usd), 0);
        if (t.llm_calls == null) t.llm_calls = runs.reduce((x, r) => x + numOr0(r.llm_calls), 0);
        if (t.tool_calls == null) t.tool_calls = runs.reduce((x, r) => x + numOr0(r.tool_calls), 0);
        const nErr = s.n_errors != null ? s.n_errors : runs.filter((r) => r.status === 'error').length;
        const dur = typeof s.duration_s === 'number' ? s.duration_s : runs.reduce((x, r) => x + numOr0(r.duration_s), 0);
        const first = s.first_message || (runs[0] && runs[0].user_message) || '';
        const models = arr(s.models).length ? arr(s.models) : Array.from(new Set(runs.map((r) => r.model).filter(Boolean)));
        const startedAt = s.started_at || (runs[0] && runs[0].started_at);
        const lastAt = s.last_run_at || (runs.length && runs[runs.length - 1].started_at);

        /* cabeçalho */
        root.appendChild(h('div', { class: 'sv-head' },
          h('div', { class: 'sv-head-main' },
            h('h1', { class: 'sv-title' }, fmt.trunc(first, 220) || '(sem mensagem)'),
            h('div', { class: 'sv-sub' },
              h('span', { class: 'mono' }, id), TA.ui.copyBtn(id),
              h('span', { class: 'faint' }, '·'),
              h('span', { title: `${fmt.datetime(startedAt)} → ${fmt.datetime(lastAt)}` }, `${shortDT(startedAt)} → ${shortDT(lastAt)}`),
              models.map((m) => h('span', { class: 'chip mono', title: m }, fmt.trunc(m, 30)))))));

        root.appendChild(h('div', { class: 'sv-kpis' },
          TA.ui.kpi({ label: 'Turnos', value: fmt.num(s.n_runs != null ? s.n_runs : runs.length) }),
          TA.ui.kpi({ label: 'Tokens', value: fmt.compact(numOr0(t.input_tokens) + numOr0(t.output_tokens)), sub: `${fmt.compact(t.input_tokens)} in / ${fmt.compact(t.output_tokens)} out`, title: fmt.num(numOr0(t.input_tokens) + numOr0(t.output_tokens)) + ' tokens' }),
          TA.ui.kpi({ label: 'Custo', value: t.cost_usd == null ? '—' : fmt.cost(t.cost_usd) }),
          TA.ui.kpi({ label: 'Chamadas LLM', value: fmt.num(numOr0(t.llm_calls)), sub: plural(numOr0(t.tool_calls), 'chamada de tool', 'chamadas de tools') }),
          TA.ui.kpi({ label: 'Erros', value: fmt.num(numOr0(nErr)), kind: numOr0(nErr) ? 'err' : '' }),
          TA.ui.kpi({ label: 'Duração', value: fmt.dur(dur), sub: 'soma dos turnos' })));

        if (!runs.length && !messages.length) { root.appendChild(TA.ui.empty('Sessão sem traces', 'Nenhum run desta sessão está no intervalo de tempo escolhido.')); return; }

        /* mini-gráfico por turno */
        const turnEls = new Map();
        if (runs.length > 1) root.appendChild(chartCard(runs, turnEls));

        /* conversa */
        const byRun = new Map();
        messages.forEach((m) => {
          if (!m || !m.run_id) return;
          const slot = byRun.get(m.run_id) || {};
          if (m.role === 'human' || m.role === 'user') { if (slot.human === undefined) slot.human = textOf(m.content); }
          else if (m.role === 'ai' || m.role === 'assistant') slot.ai = textOf(m.content);
          byRun.set(m.run_id, slot);
        });
        const known = new Set(runs.map((r) => r.run_id));

        const timeline = h('div', { class: 'sv-timeline' });
        runs.forEach((r, i) => {
          const el = turnFor(r, i, byRun.get(r.run_id) || {});
          turnEls.set(r.run_id, el);
          timeline.appendChild(el);
        });
        const orphans = messages.filter((m) => m && (!m.run_id || !known.has(m.run_id)) && textOf(m.content));
        if (orphans.length) {
          timeline.appendChild(h('div', { class: 'sv-orphans' },
            h('div', { class: 'sv-orph-title' }, 'Mensagens sem trace nesta lista'),
            orphans.map((m) => bubble(m.role === 'human' || m.role === 'user' ? 'user' : 'ai', textOf(m.content), { md: m.role === 'ai', title: fmt.datetime(m.at) }))));
        }
        root.appendChild(timeline);
      }

      function turnFor(r, i, msgs) {
        const n = r.turn != null ? r.turn : i + 1;
        const user = msgs.human !== undefined ? msgs.human : (r.user_message || '');
        let answer = msgs.ai !== undefined ? msgs.ai : (r.answer_preview || '');
        const isErr = r.status === 'error';
        const href = TA.router.hashFor('runs/' + r.run_id);

        const nodes = [];
        nodes.push(h('div', { class: 'sv-turn-head' },
          h('span', { class: 'sv-turn-n' }, `Turno ${n}`),
          h('span', { class: 'muted xs', title: fmt.datetime(r.started_at) }, fmt.rel(r.started_at))));
        nodes.push(bubble('user', user || '(sem mensagem)', { title: 'Usuário' }));
        if (answer) nodes.push(bubble('ai', answer, { md: true, title: r.model || 'Agente' }));
        else nodes.push(h('div', { class: 'sv-msg sv-msg-ai' }, h('div', { class: 'sv-av' }, TA.ui.icon('bot')),
          h('div', { class: ['sv-bubble', 'sv-bubble-empty', isErr && 'sv-bubble-err'] },
            r.status === 'running' ? 'Resposta em andamento…' : isErr ? 'O turno terminou com erro e não gerou resposta.' : 'Sem resposta registrada.')));

        const nTools = numOr0(r.tool_calls), nSub = numOr0(r.subagent_calls);
        const sb = TA.ui.statusBadge(r.status);
        if (r.status === 'running') sb.classList.add('sv-running');
        nodes.push(h('div', { class: 'sv-strip' },
          sb,
          stat('clock', fmt.dur(r.duration_s), 'Latência'),
          stat('zap', `${fmt.compact(r.input_tokens)} → ${fmt.compact(r.output_tokens)}`, `Tokens: entrada → saída (${fmt.num(r.total_tokens)} no total)`),
          r.cost_usd != null ? stat(null, fmt.cost(r.cost_usd), 'Custo') : null,
          stat('tool', plural(nTools, 'tool', 'tools'), arr(r.tools).join(', ') || 'Chamadas a tools'),
          nSub ? stat('bot', plural(nSub, 'subagent', 'subagents'), 'Subagents acionados') : null,
          numOr0(r.errors) > 0 ? stat('alert', plural(r.errors, 'erro', 'erros'), 'Erros durante o run', 'sv-stat-err') : null,
          h('span', { class: 'spacer' }),
          h('a', { class: 'sv-trace', href }, 'Ver trace', TA.ui.icon('chevR', 'sm'))));

        return h('section', { class: ['sv-turn', isErr && 'sv-turn-err'], id: 'sv-turn-' + r.run_id, 'aria-label': `Turno ${n}` }, nodes);
      }

      function chartCard(runs, turnEls) {
        const holder = h('div', { class: 'sv-chart', role: 'list' });
        const legend = h('span', { class: 'hint' });
        const seg = TA.ui.seg({
          options: METRICS.map((m) => ({ value: m.value, label: m.label })), value: metric,
          onChange: (v) => { metric = v; U.store.set('session.metric', v); paint(); },
        });
        function paint() {
          const m = METRICS.find((x) => x.value === metric) || METRICS[0];
          U.clear(holder);
          const vals = runs.map((r) => m.get(r));
          const max = Math.max(0, ...vals.map(numOr0));
          legend.textContent = `pico: ${max > 0 ? m.fmt(max) : '—'}`;
          runs.forEach((r, i) => {
            const v = vals[i];
            const pct = max > 0 && typeof v === 'number' ? U.clamp((v / max) * 100, 3, 100) : 3;
            const n = r.turn != null ? r.turn : i + 1;
            const b = h('button', {
              type: 'button', class: ['sv-bar', r.status === 'error' && 'err', r.status === 'running' && 'run'], role: 'listitem', 'aria-label': `Turno ${n}: ${v == null ? 'sem dado' : m.fmt(v)}`,
              onClick: () => { const el = turnEls.get(r.run_id); if (el && el.scrollIntoView) el.scrollIntoView({ block: 'start', behavior: 'smooth' }); },
            }, h('i', { style: { height: pct + '%' } }));
            TA.ui.tip(b, `Turno ${n} · ${m.label}: ${v == null ? '—' : m.fmt(v)}\n${U.statusLabel(r.status)}`);
            holder.appendChild(b);
          });
        }
        paint();
        return h('div', { class: 'card sv-chartcard' },
          h('div', { class: 'card-head' }, h('h3', null, 'Por turno'), legend, h('span', { class: 'spacer' }), seg.el),
          h('div', { class: 'card-body' }, holder));
      }

      async function load() {
        const my = ++seq;
        if (!root.firstChild) root.appendChild(TA.ui.loading());
        try {
          const data = await TA.api.session(id);
          if (my !== seq) return;
          render(data);
        } catch (e) {
          if (my !== seq) return;
          U.clear(root);
          root.appendChild(TA.ui.error(e));
          root.appendChild(h('div', { style: 'padding:0 16px' }, TA.router.link('sessions', null, '← Voltar para as sessões')));
        }
      }
      ctx.onCleanup(() => { seq++; });
      ctx.onRefresh(load);
      load();
    },
  };
})();
