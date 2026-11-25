/* View `dashboard` (#/): visão geral estilo "Monitor". Lê TA.api.stats(...) (README: contrato; campos em repository.stats()).
   O normalizador abaixo aceita nomes alternativos de campos e nunca assume que um campo existe. */
(function () {
  const h = TA.h;
  const F = TA.fmt;

  /* ------------------------------------------------------------------ leitura defensiva dos dados */
  const arr = (v) => (Array.isArray(v) ? v : []);
  const pick = (o, keys) => { if (!o || typeof o !== 'object') return undefined; for (const k of keys) if (o[k] !== undefined && o[k] !== null) return o[k]; return undefined; };
  const num = (v) => { if (v === null || v === undefined || v === '') return null; const n = Number(v); return Number.isFinite(n) ? n : null; };
  const nz = (v, d) => (v === null || v === undefined ? d : v);
  const pn = (o, keys) => num(pick(o, keys));

  /** KPIs (do período atual ou do anterior) -> números, com derivados quando o campo direto falta */
  function metrics(kp, series) {
    kp = kp || {};
    const m = {};
    m.runs = pn(kp, ['runs', 'traces', 'n_runs', 'total_runs', 'count']);
    if (m.runs === null && series) m.runs = series.reduce((a, p) => a + p.runs, 0);
    m.errors = pn(kp, ['errors', 'n_errors', 'error_runs', 'runs_error', 'error_count']);
    m.error_rate = pn(kp, ['error_rate', 'err_rate', 'errors_rate']);
    if (m.error_rate === null && m.errors !== null && m.runs) m.error_rate = m.errors / m.runs;
    m.input_tokens = pn(kp, ['input_tokens', 'tokens_in', 'prompt_tokens']);
    m.output_tokens = pn(kp, ['output_tokens', 'tokens_out', 'completion_tokens']);
    m.total_tokens = pn(kp, ['total_tokens', 'tokens']);
    if (m.total_tokens === null && (m.input_tokens !== null || m.output_tokens !== null)) m.total_tokens = nz(m.input_tokens, 0) + nz(m.output_tokens, 0);
    m.cache_read_tokens = pn(kp, ['cache_read_tokens', 'cached_tokens']);
    m.cost = pn(kp, ['cost_usd', 'cost', 'total_cost_usd']);
    m.p50 = pn(kp, ['latency_p50_s', 'duration_p50_s', 'p50_s', 'latency_p50', 'p50', 'duration_s_p50']);
    m.p95 = pn(kp, ['latency_p95_s', 'duration_p95_s', 'p95_s', 'latency_p95', 'p95', 'duration_s_p95']);
    m.ttft = pn(kp, ['ttft_avg_s', 'ttft_mean_s', 'avg_ttft_s', 'ttft_s', 'ttft_avg', 'ttft']);
    m.llm_calls = pn(kp, ['llm_calls', 'n_llm_calls']);
    m.tool_calls = pn(kp, ['tool_calls', 'n_tool_calls']);
    m.cache_hit = pn(kp, ['cache_hit_rate', 'cache_hit', 'cache_hit_ratio']);
    if (m.cache_hit === null && m.cache_read_tokens !== null && m.input_tokens) m.cache_hit = Math.min(1, m.cache_read_tokens / m.input_tokens);
    return m;
  }

  function normPoint(p) {
    const runs = nz(pn(p, ['runs', 'traces', 'count', 'n_runs']), 0);
    const errors = nz(pn(p, ['errors', 'n_errors', 'error_runs']), 0);
    let ok = pn(p, ['ok', 'completed', 'runs_ok', 'success']);
    if (ok === null) ok = Math.max(0, runs - errors);
    return {
      t: pick(p, ['t', 'ts', 'time', 'bucket', 'bucket_start', 'start', 'at', 'x']),
      runs, errors, ok, other: Math.max(0, runs - ok - errors),
      p50: pn(p, ['latency_p50_s', 'duration_p50_s', 'p50_s', 'p50', 'latency_p50']),
      p95: pn(p, ['latency_p95_s', 'duration_p95_s', 'p95_s', 'p95', 'latency_p95']),
      input: pn(p, ['input_tokens', 'tokens_in']), output: pn(p, ['output_tokens', 'tokens_out']),
      cost: pn(p, ['cost_usd', 'cost']),
    };
  }

  /* ------------------------------------------------------------------ pequenos blocos */
  /** variação vs período anterior: `goodUp` true/false = subir é bom/ruim; null = neutro; `ratio` = diferença em pontos percentuais */
  function deltaEl(cur, prev, { goodUp = null, ratio = false, fmt }) {
    if (cur === null || cur === undefined || prev === null || prev === undefined) return null;
    let change, text;
    if (ratio) {
      const pp = (cur - prev) * 100;
      change = pp;
      text = `${(Math.round(Math.abs(pp) * 10) / 10).toLocaleString('pt-BR')} p.p.`;
    } else {
      if (prev === 0) return null;
      change = (cur - prev) / Math.abs(prev);
      text = F.pct(Math.abs(change), Math.abs(change) < 0.1 ? 1 : 0);
    }
    const flat = ratio ? Math.abs(change) < 0.05 : Math.abs(change) < 0.005;
    const up = change > 0;
    const sentiment = flat || goodUp === null ? 'neutral' : (up === goodUp ? 'good' : 'bad');
    return h('span', { class: ['db-delta', sentiment], title: `Período anterior: ${fmt ? fmt(prev) : prev}` },
      flat ? '≈ ' : (up ? '▲ ' : '▼ '), flat ? '0%' : text);
  }

  function skeleton() {
    const box = () => h('div', { class: 'card db-sk' });
    return h('div', { class: 'db-skel' },
      h('div', { class: 'db-kpis' }, Array.from({ length: 9 }, box)),
      h('div', { class: 'db-grid' }, Array.from({ length: 6 }, () => h('div', { class: 'card db-sk db-sk-card' }))));
  }

  const optOf = (v) => {
    if (v && typeof v === 'object') { const val = pick(v, ['name', 'value', 'id', 'key']); return { value: val, label: String(pick(v, ['label', 'name', 'value']) ?? val) }; }
    return { value: v, label: String(v) };
  };
  const STATUS_COLOR = { completed: 'var(--ok)', error: 'var(--err)', cancelled: 'var(--warn)', running: 'var(--info)', unfinished: 'var(--faint)' };
  const STATUS_ORDER = ['completed', 'error', 'cancelled', 'running', 'unfinished'];

  /* ------------------------------------------------------------------ a view */
  TA.views.dashboard = {
    mount(ctx) {
      ctx.crumbs([{ label: 'Visão geral' }]);
      const state = {
        model: ctx.query.model || '', origin: ctx.query.origin || '', status: ctx.query.status || '',
        bucket: ['hour', 'day'].includes(ctx.query.bucket) ? ctx.query.bucket : 'auto', auto: [10, 30].includes(Number(ctx.query.auto)) ? Number(ctx.query.auto) : 0,
      };
      let charts = [], pending = [], data = null, token = 0, timer = null, dead = false;

      /* ---- cabeçalho e filtros ---- */
      const sub = h('div', { class: 'sub' }, 'Carregando…');
      const mkSel = (title, key, allLabel) => {
        const s = TA.ui.select({ options: [{ value: '', label: allLabel }], value: state[key], title, onChange: (v) => { state[key] = v; ctx.setQuery({ [key]: v || null }); load(false); } });
        return s;
      };
      const selModel = mkSel('Modelo', 'model', 'Todos os modelos');
      const selOrigin = mkSel('Origem (CLI ou web)', 'origin', 'Todas as origens');
      const selStatus = mkSel('Status do run', 'status', 'Todos os status');
      const selBucket = TA.ui.select({
        title: 'Agrupamento do tempo', value: state.bucket,
        options: [{ value: 'auto', label: 'Agrupar: auto' }, { value: 'hour', label: 'Por hora' }, { value: 'day', label: 'Por dia' }],
        onChange: (v) => { state.bucket = v; ctx.setQuery({ bucket: v === 'auto' ? null : v }); load(false); },
      });
      const segAuto = TA.ui.seg({
        value: state.auto, options: [{ value: 0, label: 'Desligado' }, { value: 10, label: '10 s' }, { value: 30, label: '30 s' }],
        onChange: (v) => setAuto(v),
      });
      function fillFilters(meta) {
        if (!meta || dead) return;
        const fill = (sel, key, all, list, lab) => {
          const opts = [{ value: '', label: all }];
          arr(list).map(optOf).forEach((o) => { if (o.value !== undefined && o.value !== null) opts.push({ value: String(o.value), label: lab ? lab(o.value) : o.label }); });
          if (state[key] && !opts.some((o) => o.value === state[key])) opts.push({ value: state[key], label: lab ? lab(state[key]) : state[key] });
          sel.setOptions(opts, state[key]);
        };
        fill(selModel, 'model', 'Todos os modelos', meta.models);
        fill(selOrigin, 'origin', 'Todas as origens', meta.origins);
        fill(selStatus, 'status', 'Todos os status', meta.statuses, (v) => TA.util.statusLabel(v));
      }
      const head = h('div', { class: 'page-head db-head' },
        h('div', null, h('h1', null, 'Visão geral'), sub),
        h('div', { class: 'spacer' }),
        h('div', { class: 'db-filters' }, selModel.el, selOrigin.el, selStatus.el, selBucket.el,
          h('div', { class: 'db-auto' }, h('span', { class: 'db-flabel' }, 'Atualizar'), segAuto.el)));
      const body = h('div', { class: 'db-body' });
      ctx.el.appendChild(h('div', { class: 'page db' }, head, body));

      function setAuto(sec) {
        state.auto = sec;
        ctx.setQuery({ auto: sec || null });
        if (timer) clearInterval(timer);
        timer = null;
        if (sec) timer = setInterval(() => { if (!document.hidden) load(true); }, sec * 1000);
      }
      function destroyCharts() { charts.forEach((c) => { try { c.destroy(); } catch (e) { /* ok */ } }); charts = []; pending = []; }

      const offMeta = TA.bus.on('meta', fillFilters);
      if (TA.state.meta) fillFilters(TA.state.meta);
      else TA.api.meta().then((m) => { TA.state.meta = m; fillFilters(m); }).catch(() => { /* sem filtros: segue só com "todos" */ });
      if (state.auto) setAuto(state.auto);
      ctx.onRefresh(() => load(true));
      ctx.onCleanup(() => { dead = true; if (timer) clearInterval(timer); offMeta(); destroyCharts(); });

      /* ---- carga ---- */
      async function load(silent) {
        const my = ++token;
        if (!silent || !data) { destroyCharts(); TA.util.clear(body); body.appendChild(skeleton()); }
        else sub.classList.add('busy');
        try {
          const s = await TA.api.stats({ model: state.model, origin: state.origin, status: state.status, bucket: state.bucket });
          if (my !== token || dead) return;
          data = s || {};
          sub.classList.remove('busy');
          render(data);
        } catch (e) {
          if (my !== token || dead) return;
          sub.classList.remove('busy');
          if (silent && data) { TA.ui.toast('Falha ao atualizar: ' + e.message, 'err'); return; }
          data = null;
          destroyCharts(); TA.util.clear(body); body.appendChild(TA.ui.error(e));
          sub.textContent = 'Não foi possível carregar os dados';
        }
      }

      /* ---- desenho ---- */
      function render(s) {
        destroyCharts();
        TA.util.clear(body);
        const series = arr(s.series).map(normPoint);
        const cur = metrics(s.kpis, series);
        const prev = s.prev_kpis ? metrics(s.prev_kpis) : null;
        const rg = s.range || {};
        const bucketTxt = rg.bucket === 'day' ? 'por dia' : rg.bucket === 'hour' ? 'por hora' : (rg.bucket || '');
        sub.textContent = [rg.from ? `${F.datetime(rg.from)} → ${F.datetime(rg.to || new Date().toISOString())}` : 'Desde o primeiro run', bucketTxt && `agrupado ${bucketTxt}`, cur.runs !== null && `${F.num(cur.runs)} traces`].filter(Boolean).join(' · ');
        if (!cur.runs) {
          body.appendChild(TA.ui.empty('Nenhum run no período', 'Amplie o intervalo de tempo no topo ou limpe os filtros acima.'));
          return;
        }
        body.appendChild(kpiRow(cur, prev));
        const grid = h('div', { class: 'db-grid' });
        body.appendChild(grid);
        pending = [];
        buildCards(grid, s, series, cur);
        pending.forEach((fn) => fn());     // os gráficos medem a largura: só depois de entrarem no DOM
        pending = [];
      }

      function kpiRow(c, p) {
        const ok = c.runs !== null && c.errors !== null ? c.runs - c.errors : null;
        const perRun = (v) => (v !== null && c.runs ? `${(v / c.runs).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} por run` : null);
        const defs = [
          { k: 'runs', label: 'Traces', val: c.runs, fmt: F.num, good: null, sub: ok !== null ? `${F.num(ok)} sem erro · ${F.num(c.errors)} com erro` : null },
          { k: 'error_rate', label: 'Taxa de erro', val: c.error_rate, fmt: (v) => F.pct(v, 1), good: false, ratio: true, kind: c.error_rate > 0.05 ? 'err' : '', sub: c.errors !== null ? `${F.num(c.errors)} de ${F.num(c.runs)} runs` : null },
          { k: 'total_tokens', label: 'Tokens totais', val: c.total_tokens, fmt: F.compact, good: null, title: c.total_tokens !== null ? F.num(c.total_tokens) + ' tokens' : null, sub: `entrada ${F.compact(c.input_tokens)} · saída ${F.compact(c.output_tokens)}` },
          { k: 'cost', label: 'Custo', val: c.cost, fmt: F.cost, good: false, sub: c.cost === null ? 'sem preço configurado' : (c.runs ? `média ${F.cost(c.cost / c.runs)} por run` : null) },
          { k: 'p50', label: 'Latência P50', val: c.p50, fmt: F.dur, good: false, sub: `P95 ${F.dur(c.p95)}` },
          { k: 'ttft', label: 'TTFT médio', val: c.ttft, fmt: F.dur, good: false, sub: 'tempo até o 1º token' },
          { k: 'llm_calls', label: 'Chamadas LLM', val: c.llm_calls, fmt: F.num, good: null, sub: perRun(c.llm_calls) },
          { k: 'tool_calls', label: 'Chamadas de tool', val: c.tool_calls, fmt: F.num, good: null, sub: perRun(c.tool_calls) },
          { k: 'cache_hit', label: 'Cache hit', val: c.cache_hit, fmt: (v) => F.pct(v, 1), good: true, ratio: true, sub: c.cache_read_tokens !== null ? `${F.compact(c.cache_read_tokens)} tokens lidos do cache` : null },
        ];
        return h('div', { class: 'db-kpis' }, defs.map((d) => {
          const dl = p ? deltaEl(d.val, p[d.k], { goodUp: d.good, ratio: !!d.ratio, fmt: d.fmt }) : null;
          return TA.ui.kpi({ label: d.label, value: [d.val === null ? '—' : d.fmt(d.val), dl], sub: d.sub, kind: d.kind, title: d.title });
        }));
      }

      /** cartão com um corpo que é preenchido depois que a grade entra no DOM */
      function chartCard(title, fn, o) {
        o = o || {};
        const box = h('div', { class: 'db-chart' });
        const card = TA.ui.card(title, box, { hint: o.hint });
        card.classList.add('db-card');
        pending.push(() => {
          try { const c = fn(box); if (c) charts.push(c); } catch (e) { console.error('[dashboard]', title, e); TA.util.clear(box); box.appendChild(TA.ui.error(e)); }
        });
        return card;
      }
      const noData = (text) => h('div', { class: 'ch-empty', style: { height: '120px' } }, text);

      function buildCards(grid, s, series, cur) {
        const q = () => ({ model: state.model, origin: state.origin, status: state.status });
        const bucketMs = (() => {
          const b = s.range && s.range.bucket;
          if (b === 'day') return 864e5;
          if (b === 'hour') return 36e5;
          const t0 = series[0] && Date.parse(series[0].t), t1 = series[1] && Date.parse(series[1].t);
          return t0 && t1 && t1 > t0 ? t1 - t0 : 36e5;
        })();

        // 1. traces por bucket
        grid.appendChild(chartCard('Traces ao longo do tempo', (box) => {
          const ser = [{ name: 'Sem erro', values: series.map((p) => p.ok), color: 'var(--ok)' }, { name: 'Com erro', values: series.map((p) => p.errors), color: 'var(--err)' }];
          if (series.some((p) => p.other > 0)) ser.push({ name: 'Outros', values: series.map((p) => p.other), color: 'var(--warn)' });
          return TA.charts.bars(box, {
            categories: series.map((p) => p.t), series: ser, stacked: true, yFormat: F.num, height: 220,
            onBarClick: ({ index }) => {
              const t = Date.parse(series[index] && series[index].t);
              if (!Number.isFinite(t)) { ctx.nav('runs', q()); return; }
              ctx.nav('runs', Object.assign(q(), { since: new Date(t).toISOString(), until: new Date(t + bucketMs).toISOString() }));
            },
          });
        }, { hint: 'clique em uma barra para abrir os runs' }));

        // 2. latência
        grid.appendChild(chartCard('Latência por run', (box) => TA.charts.line(box, {
          series: [{ name: 'P50', color: 'var(--c1)', points: series.map((p) => [p.t, p.p50]) }, { name: 'P95', color: 'var(--c3)', points: series.map((p) => [p.t, p.p95]) }],
          yFormat: F.dur, height: 220, emptyText: 'Sem dados de latência no período',
        }), { hint: 'P50 e P95' }));

        // 3. tokens
        grid.appendChild(chartCard('Tokens', (box) => TA.charts.line(box, {
          series: [{ name: 'Entrada', color: 'var(--c4)', points: series.map((p) => [p.t, p.input]) }, { name: 'Saída', color: 'var(--c2)', points: series.map((p) => [p.t, p.output]) }],
          stacked: true, area: true, yFormat: F.compact, height: 220, emptyText: 'Sem dados de tokens no período',
        }), { hint: 'entrada + saída' }));

        // 4. custo
        grid.appendChild(chartCard('Custo estimado', (box) => {
          if (!series.some((p) => p.cost !== null)) { box.appendChild(noData('Sem preço configurado para os modelos do período')); return null; }
          return TA.charts.line(box, { series: [{ name: 'Custo (USD)', color: 'var(--c3)', points: series.map((p) => [p.t, p.cost]) }], area: true, yFormat: F.cost, height: 220 });
        }, { hint: 'USD por intervalo' }));

        // 5. uso de tools
        const tools = arr(s.by_tool).map((t) => ({
          name: String(pick(t, ['name', 'tool', 'tool_name', 'key']) ?? '—'), calls: pn(t, ['calls', 'count', 'n', 'n_calls', 'tool_calls']),
          avg: pn(t, ['avg_duration_s', 'avg_s', 'mean_duration_s', 'avg_latency_s', 'duration_avg_s', 'avg_duration']), errors: pn(t, ['errors', 'n_errors', 'error_count']),
        })).sort((a, b) => nz(b.calls, 0) - nz(a.calls, 0));
        grid.appendChild(chartCard('Uso de tools', (box) => TA.charts.hbars(box, {
          items: tools.slice(0, 10).map((t) => ({
            label: t.name, value: t.calls, color: 'var(--k-tool)', href: TA.router.hashFor('data/tools', { name: t.name }),
            sub: [t.avg !== null && `média ${F.dur(t.avg)}`, t.errors && `${F.num(t.errors)} com erro`].filter(Boolean).join(' · '),
          })),
          valueFormat: F.num, emptyText: 'Nenhuma tool chamada no período',
        }), { hint: tools.length > 10 ? `top 10 de ${tools.length} · chamadas` : 'chamadas e latência média' }));

        // 6. por modelo
        const models = arr(s.by_model).map((m) => {
          const i = pn(m, ['input_tokens', 'tokens_in']), o = pn(m, ['output_tokens', 'tokens_out']);
          return {
            model: String(pick(m, ['model', 'name', 'key']) ?? '—'), runs: pn(m, ['runs', 'n_runs', 'count']),
            tokens: pn(m, ['total_tokens', 'tokens']) ?? (i !== null || o !== null ? nz(i, 0) + nz(o, 0) : null), cost: pn(m, ['cost_usd', 'cost']),
            lat: pn(m, ['latency_avg_s', 'avg_latency_s', 'avg_duration_s', 'latency_s', 'duration_avg_s', 'latency_p50_s', 'p50_s']),
          };
        }).sort((a, b) => nz(b.runs, 0) - nz(a.runs, 0));
        grid.appendChild(chartCard('Por modelo', (box) => {
          const dBox = h('div'), tBox = h('div', { class: 'db-mt' });
          box.append(dBox, tBox);
          const c = TA.charts.donut(dBox, { items: models.map((m, i) => ({ label: m.model, value: m.runs, color: `var(--c${(i % 8) + 1})` })), centerLabel: 'runs', valueFormat: F.num, emptyText: 'Sem runs por modelo' });
          tBox.appendChild(TA.ui.table({
            columns: [
              { key: 'model', label: 'Modelo', render: (r) => h('span', { class: 'mono db-cell-trunc', title: r.model }, r.model) },
              { key: 'runs', label: 'Runs', align: 'r', render: (r) => F.num(r.runs) },
              { key: 'tokens', label: 'Tokens', align: 'r', render: (r) => F.compact(r.tokens) },
              { key: 'cost', label: 'Custo', align: 'r', render: (r) => F.cost(r.cost) },
              { key: 'lat', label: 'Latência', align: 'r', title: 'Latência média por run', render: (r) => F.dur(r.lat) },
            ], rows: models, empty: 'Sem modelos no período',
          }).el);
          return c;
        }, { hint: 'runs, tokens, custo e latência' }));

        // 7. status
        const sc = s.status_counts && typeof s.status_counts === 'object' ? s.status_counts : {};
        const statusKeys = Object.keys(sc).sort((a, b) => { const ia = STATUS_ORDER.indexOf(a), ib = STATUS_ORDER.indexOf(b); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib); });
        grid.appendChild(chartCard('Status dos runs', (box) => TA.charts.donut(box, {
          items: statusKeys.map((k) => ({ label: TA.util.statusLabel(k), value: sc[k], color: STATUS_COLOR[k] || 'var(--muted)', onClick: () => ctx.nav('runs', Object.assign(q(), { status: k })) })),
          centerLabel: 'runs', centerValue: statusKeys.reduce((a, k) => a + nz(num(sc[k]), 0), 0), valueFormat: F.num, emptyText: 'Sem status no período',
        }), { hint: 'clique para filtrar os runs' }));

        // 8. por agente
        const agents = arr(s.by_agent).map((a) => {
          const i = pn(a, ['input_tokens', 'tokens_in']), o = pn(a, ['output_tokens', 'tokens_out']);
          const name = String(pick(a, ['agent', 'name', 'agent_name', 'key']) ?? '—');
          return {
            name, main: pick(a, ['is_main', 'main']) === true || /^(main|principal|agent|main_agent|agente)$/i.test(name),
            tokens: pn(a, ['total_tokens', 'tokens']) ?? (i !== null || o !== null ? nz(i, 0) + nz(o, 0) : null),
            llm: pn(a, ['llm_calls', 'n_llm_calls']), tools: pn(a, ['tool_calls', 'n_tool_calls']), cost: pn(a, ['cost_usd', 'cost']),
          };
        });
        const byTokens = agents.some((a) => a.tokens);
        agents.sort((a, b) => nz(byTokens ? b.tokens : b.llm, 0) - nz(byTokens ? a.tokens : a.llm, 0));
        grid.appendChild(chartCard('Por agente', (box) => TA.charts.hbars(box, {
          items: agents.slice(0, 10).map((a) => ({
            label: a.main ? `${a.name} (principal)` : a.name, value: byTokens ? a.tokens : a.llm, color: a.main ? 'var(--k-llm)' : 'var(--k-subagent)',
            sub: [a.llm !== null && `${F.num(a.llm)} LLM`, a.tools !== null && `${F.num(a.tools)} tools`, a.cost !== null && F.cost(a.cost)].filter(Boolean).join(' · '),
          })),
          valueFormat: byTokens ? F.compact : F.num, emptyText: 'Sem dados por agente',
        }), { hint: byTokens ? 'tokens · principal vs subagents' : 'chamadas LLM · principal vs subagents' }));

        // 9 e 10. histogramas
        const lh = s.latency_hist || {}, th = s.tokens_hist || {};
        grid.appendChild(chartCard('Distribuição da latência', (box) => TA.charts.hist(box, {
          edges: lh.edges, counts: lh.counts, xFormat: F.dur, color: 'var(--c1)', height: 190,
          markers: [cur.p50 !== null && { x: cur.p50, label: `P50 ${F.dur(cur.p50)}` }, cur.p95 !== null && { x: cur.p95, label: `P95 ${F.dur(cur.p95)}` }].filter(Boolean),
        }), { hint: 'runs por faixa de duração' }));
        grid.appendChild(chartCard('Distribuição de tokens por run', (box) => TA.charts.hist(box, {
          edges: th.edges, counts: th.counts, xFormat: F.compact, color: 'var(--c2)', height: 190,
        }), { hint: 'runs por faixa de tokens' }));

        // 11. runs mais lentos
        const slow = arr(s.slowest_runs);
        grid.appendChild(chartCard('Runs mais lentos', (box) => {
          box.appendChild(TA.ui.table({
            columns: [
              { key: 'run_id', label: 'Run', render: (r) => TA.router.link('runs/' + r.run_id, null, h('span', { class: 'mono' }, F.short(r.run_id))) },
              { key: 'user_message', label: 'Pergunta', render: (r) => h('span', { class: 'db-cell-trunc', title: r.user_message || '' }, F.trunc(r.user_message, 70) || '—') },
              { key: 'duration_s', label: 'Duração', align: 'r', render: (r) => F.dur(num(r.duration_s)) },
              { key: 'total_tokens', label: 'Tokens', align: 'r', render: (r) => F.compact(num(r.total_tokens)) },
              { key: 'status', label: 'Status', render: (r) => TA.ui.statusBadge(r.status) },
            ], rows: slow.slice(0, 8), onRowClick: (r) => ctx.nav('runs/' + r.run_id), empty: 'Nenhum run no período',
          }).el);
          return null;
        }, { hint: 'clique para abrir o trace' }));

        // 12. erros recentes
        const errs = arr(s.recent_errors);
        grid.appendChild(chartCard('Erros recentes', (box) => {
          if (!errs.length) { box.appendChild(noData('Nenhum erro no período')); return null; }
          box.appendChild(h('div', { class: 'db-errs' }, errs.slice(0, 8).map((e) => {
            const type = pick(e, ['type', 'error_type', 'exc_type', 'kind']);
            const msg = pick(e, ['message', 'error', 'msg', 'detail']);
            const where = pick(e, ['where', 'tool', 'span_name', 'name', 'agent', 'source']);
            const at = pick(e, ['at', 'ts', 'started_at', 'time', 'timestamp']);
            const runId = pick(e, ['run_id']);
            const spanId = pick(e, ['span_id']);
            const href = runId ? TA.router.hashFor('runs/' + runId, spanId ? { span: spanId } : null) : null;
            return h(href ? 'a' : 'div', { class: 'db-err', href },
              TA.ui.icon('alert'),
              h('div', { class: 'db-err-main' },
                h('div', { class: 'db-err-msg', title: String(msg || '') }, type ? h('b', null, String(type) + (msg ? ': ' : '')) : null, F.trunc(msg, 160) || (type ? '' : 'Erro sem mensagem')),
                h('div', { class: 'db-err-meta' }, [where && String(where), runId && 'run ' + F.short(runId), at && F.rel(at)].filter(Boolean).join(' · '))));
          })));
          return null;
        }, { hint: 'clique para ver o span' }));
      }

      load(false);
    },
  };
})();
