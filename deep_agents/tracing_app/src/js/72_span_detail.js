/* Painel de detalhe de um span (lado direito do trace): prompts, mensagens, tools, tokens.
   Expõe: TA.spanDetail.render(el, {runId, spanId, trace, onSelect?}) -> Promise.
   `onSelect(spanId)` (opcional): se existir, os links para outros spans chamam-no em vez de trocar o hash da URL. */
(function () {
  const h = TA.h;
  const num = (n) => TA.fmt.num(n);
  const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
  const hasKeys = (v) => v !== null && typeof v === 'object' && Object.keys(v).length > 0;
  const nz = (v) => v !== null && v !== undefined;

  TA.spanDetail = { render };

  /* ================================================================== índice do trace (para links entre spans) */
  function indexTrace(trace) {
    if (trace && trace._sdIx) return trace._sdIx;
    const ix = { byId: {}, toolByCall: {}, kids: {}, spans: [] };
    if (trace && Array.isArray(trace.spans)) {
      ix.spans = trace.spans;
      trace.spans.forEach((s) => {
        ix.byId[s.span_id] = s;
        const tcid = (s.brief && s.brief.tool_call_id) || (s.ref && s.ref.tool_call_id);
        if (tcid) ix.toolByCall[tcid] = s;
        const p = s.parent_id || '';
        (ix.kids[p] = ix.kids[p] || []).push(s);
      });
      try { Object.defineProperty(trace, '_sdIx', { value: ix, enumerable: false }); } catch (e) { /* objeto congelado */ }
    }
    return ix;
  }
  const offsetOf = (s) => (nz(s.offset_s) ? s.offset_s : (nz(s.start_offset_s) ? s.start_offset_s : 0));

  function descendants(ix, id) {
    const out = [];
    const stack = (ix.kids[id] || []).slice().reverse();
    while (stack.length) {
      const s = stack.pop();
      out.push(s);
      (ix.kids[s.span_id] || []).slice().reverse().forEach((k) => stack.push(k));
    }
    return out;
  }

  /* ================================================================== componentes pequenos */
  function section(title, node, hint) {
    return h('div', { class: 'sd-sec' }, h('div', { class: 'sd-sec-head' }, h('h4', null, title), hint ? h('span', { class: 'hint' }, hint) : null), node);
  }

  function idChip(label, value) {
    if (!value) return null;
    return h('button', { type: 'button', class: 'sd-id', title: `Copiar ${label}: ${value}`, onClick: () => TA.util.copy(value) },
      h('span', { class: 'k' }, label), h('span', { class: 'v' }, TA.fmt.short(value, 12)), TA.ui.icon('copy', 'sm'));
  }

  function chips(list) {
    const a = Array.isArray(list) ? list.filter((x) => x !== null && x !== undefined && x !== '') : [];
    return a.length ? h('div', { class: 'sd-chips' }, a.map((t) => TA.ui.chip(String(t), true))) : h('span', { class: 'muted' }, '—');
  }

  /** árvore JSON, ou "—" quando vazio */
  function tree(v, expand) {
    if (v === null || v === undefined || (typeof v === 'object' && !Object.keys(v).length)) return h('span', { class: 'muted' }, '—');
    return h('div', { class: 'sd-tree' }, TA.ui.jsonTree(v, { expand: expand === undefined ? 1 : expand }));
  }

  /** texto longo com alternância Markdown/Texto, contagem e copiar */
  function richText(text, { md = true, maxHeight = 560 } = {}) {
    text = text === null || text === undefined ? '' : (typeof text === 'string' ? text : TA.util.pretty(text));
    if (!text) return h('div', { class: 'muted' }, '(vazio)');
    let mode = md && text.length <= 40000 ? 'md' : 'text';
    const host = h('div', { class: 'sd-rich-body' });
    function paint() {
      TA.util.clear(host);
      if (mode === 'md') host.appendChild(h('div', { class: 'sd-scroll', style: { maxHeight: maxHeight + 'px' } }, TA.ui.markdown(text)));
      else host.appendChild(h('pre', { class: 'ms-pre sd-scroll', style: { maxHeight: maxHeight + 'px' } }, text.length > 300000 ? text.slice(0, 300000) + '\n… (cortado)' : text));
    }
    const seg = TA.ui.seg({ options: [{ value: 'md', label: 'Markdown' }, { value: 'text', label: 'Texto' }], value: mode, onChange: (v) => { mode = v; paint(); } });
    paint();
    return h('div', { class: 'sd-rich' }, h('div', { class: 'sd-rich-bar' }, seg.el, h('span', { class: 'xs muted' }, `${num(text.length)} caracteres`), h('span', { class: 'spacer' }), TA.ui.copyBtn(text)), host);
  }

  /** barra empilhada com legenda */
  function stackBar(segs, total) {
    const live = segs.filter((s) => s.value > 0);
    if (!total || !live.length) return h('div', { class: 'muted xs' }, 'Sem dados.');
    return h('div', { class: 'sd-stack-wrap' },
      h('div', { class: 'sd-stack-bar' }, live.map((s) => h('span', { class: 'sd-seg', title: `${s.label}: ${num(s.value)}`, style: { width: (100 * s.value / total) + '%', background: s.color } }))),
      h('div', { class: 'sd-legend' }, live.map((s) => h('span', null, h('i', { style: { background: s.color } }), `${s.label} ${num(s.value)}`))));
  }

  function errInfo(x) {
    if (!x) return null;
    if (typeof x === 'string') return { type: 'Erro', message: x };
    return { type: x.type || x.name || 'Erro', message: x.message || x.msg || (typeof x.error === 'string' ? x.error : ''), traceback: x.traceback || null };
  }

  function errorBanner(C) {
    const { span, tool, llm } = C;
    let e = errInfo(span.error) || errInfo(tool && tool.error) || errInfo(llm && llm.error);
    if (!e && tool && tool.output && tool.output.is_error) e = { type: 'Erro da tool', message: tool.output.text || '' };
    if (!e && span.status === 'error') e = { type: 'Erro', message: 'O span terminou com status de erro (sem detalhes registrados).' };
    if (!e) return null;
    return h('div', { class: 'sd-err', role: 'alert' },
      TA.ui.icon('alert'),
      h('div', { class: 'sd-err-main' },
        h('div', { class: 'sd-err-type' }, e.type),
        e.message ? h('pre', { class: 'sd-err-msg' }, e.message) : null,
        e.traceback ? h('details', { class: 'sd-err-tb' }, h('summary', null, 'Traceback'), h('pre', null, String(e.traceback))) : null));
  }

  /* ================================================================== navegação entre spans */
  function makeNav(C) {
    C.href = (id) => TA.router.hashFor('runs/' + C.runId, Object.assign({}, TA.router.parse().query, { span: id }));
    C.clickFor = (id) => (e) => {
      if (!C.onSelect || (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1))) return;
      e.preventDefault();
      C.onSelect(id);
    };
    C.go = (id) => { if (C.onSelect) C.onSelect(id); else location.hash = C.href(id); };
    C.link = (id, kids, cls) => h('a', { href: C.href(id), class: cls || null, onClick: C.clickFor(id) }, kids);
    C.toolRef = (callId) => {
      const s = C.ix.toolByCall[callId];
      if (!s) return null;
      return { href: C.href(s.span_id), onClick: C.clickFor(s.span_id), status: s.status, duration_s: s.duration_s };
    };
  }

  function kindOf(C) {
    if (C.tool) return C.tool.kind || 'tool';
    if (C.span.type === 'llm') return 'llm';
    if (C.span.type === 'tool') return 'tool';
    return 'chain';
  }

  /** lista de spans (tabela clicável) */
  function spanTable(C, spans, empty) {
    const rows = spans.slice();
    return TA.ui.table({
      columns: [
        { key: 'name', label: 'Span', render: (s) => h('span', { class: 'row', style: 'gap:6px' }, TA.ui.kindIcon(s.type === 'llm' ? 'llm' : s.type === 'tool' ? (s.brief && s.brief.kind) || 'tool' : 'chain'), h('span', { class: 'truncate' }, s.name || s.span_id)) },
        { key: 'detail', label: 'Detalhe', render: (s) => {
          const b = s.brief || {};
          if (s.type === 'llm') return h('span', { class: 'muted' }, [b.model, b.purpose === 'summary' ? 'resumo' : null, nz(b.input_tokens) ? `${num(b.input_tokens)} → ${num(b.output_tokens)} tok` : null].filter(Boolean).join(' · '));
          if (s.type === 'tool') return h('span', { class: 'muted truncate', style: 'display:block;max-width:420px' }, TA.fmt.trunc(b.input_preview || '', 110));
          return h('span', { class: 'muted' }, s.agent || '');
        } },
        { key: 'duration_s', label: 'Duração', align: 'r', render: (s) => TA.fmt.dur(s.duration_s) },
        { key: 'status', label: 'Status', render: (s) => TA.ui.statusBadge(s.status) },
      ],
      rows, empty: empty || 'Nenhum span.', onRowClick: (s) => C.go(s.span_id), rowId: (s) => s.span_id,
    }).el;
  }

  /* ================================================================== cabeçalho */
  function normChain(chain, spanId) {
    let c = (Array.isArray(chain) ? chain : []).filter((x) => x && typeof x === 'object');
    c = c.filter((x) => x.span_id !== spanId);
    if (c.length > 1 && c[0].parent_id && !c[c.length - 1].parent_id) c = c.slice().reverse();
    return c;
  }

  function header(C, switchTo) {
    const { span, llm, tool, deleg } = C;
    const kind = kindOf(C);
    const [, kindLabel] = TA.ui.kindMeta(kind);
    const name = tool ? tool.name || span.name : span.name;
    const crumbs = normChain(C.data.parent_chain, C.spanId);

    // irmãos (anterior/próximo) dentro do mesmo pai
    const sibs = (C.ix.kids[span.parent_id || ''] || []).slice().sort((a, b) => (a.seq || 0) - (b.seq || 0) || offsetOf(a) - offsetOf(b));
    const at = sibs.findIndex((s) => s.span_id === C.spanId);
    const sibBtn = (dir, label) => {
      const t = at >= 0 ? sibs[at + dir] : null;
      return h('button', { type: 'button', class: 'btn sm icon', disabled: !t, title: t ? `${label}: ${t.name}` : `Sem ${label.toLowerCase()}`, 'aria-label': label, onClick: () => t && C.go(t.span_id) }, dir < 0 ? '←' : '→');
    };

    const off = nz(span.start_offset_s) ? span.start_offset_s : span.offset_s;
    const meta = h('div', { class: 'sd-meta' },
      h('span', { class: 'sd-m', title: 'Duração' }, TA.ui.icon('clock', 'sm'), TA.fmt.dur(span.duration_s)),
      nz(off) ? h('span', { class: 'sd-m', title: span.started_at ? 'Início: ' + TA.fmt.datetime(span.started_at) : 'Início' }, 'início +' + TA.fmt.dur(off)) : null,
      span.agent ? h('span', { class: 'sd-m', title: 'Agente' }, TA.ui.icon('bot', 'sm'), span.agent) : null,
      llm && llm.model && llm.model.requested ? h('span', { class: 'sd-m mono', title: 'Modelo' }, llm.model.returned || llm.model.requested) : null,
      llm && llm.usage && nz(llm.usage.input_tokens) ? h('span', { class: 'sd-m', title: 'Tokens de entrada → saída' }, `${num(llm.usage.input_tokens)} → ${num(llm.usage.output_tokens)} tok`) : null,
      llm && nz(llm.cost_usd) ? h('span', { class: 'sd-m', title: 'Custo' }, TA.fmt.cost(llm.cost_usd)) : null,
      tool && nz(tool.output_chars) ? h('span', { class: 'sd-m', title: 'Tamanho da saída' }, `${num(tool.output_chars)} car. de saída`) : null);

    return h('div', { class: 'sd-head' },
      h('div', { class: 'sd-title-row' },
        TA.ui.kindIcon(kind),
        h('h2', { class: 'sd-title', title: name }, name || '(sem nome)'),
        TA.ui.badge(kindLabel, null),
        TA.ui.statusBadge(span.status),
        llm && llm.purpose === 'summary' ? TA.ui.badge('resumo de contexto', 'warn', 'Chamada feita pelo middleware de resumo, não pelo agente') : null,
        deleg ? TA.ui.badge('subagent: ' + (deleg.subagent_type || '?'), 'pink') : null,
        h('span', { class: 'spacer' }),
        at >= 0 ? h('span', { class: 'xs muted' }, `${at + 1}/${sibs.length}`) : null,
        sibs.length > 1 ? [sibBtn(-1, 'Irmão anterior'), sibBtn(1, 'Próximo irmão')] : null),
      crumbs.length ? h('nav', { class: 'sd-crumbs', 'aria-label': 'Ancestrais do span' }, crumbs.map((c) => [
        C.link(c.span_id, [h('span', { class: ['kind-dot', 'kind-' + (c.type === 'llm' ? 'llm' : c.type === 'tool' ? 'tool' : 'chain')] }), TA.fmt.trunc(c.name || c.span_id, 36)], 'sd-crumb'),
        h('span', { class: 'sd-sep' }, '›'),
      ]), h('span', { class: 'sd-crumb cur' }, TA.fmt.trunc(span.name || '', 36))) : null,
      meta,
      h('div', { class: 'sd-ids' }, idChip('span', C.spanId), idChip('tool_call', tool && tool.tool_call_id), idChip('llm_call', llm && llm.llm_call_id), idChip('run', C.runId)));
  }

  /* ================================================================== abas (com lembrança por tipo de span) */
  function tabsView(C, group, items, defaultId) {
    const saved = TA.util.store.get('sd.tab.' + group, defaultId);
    let active = items.some((i) => i.id === saved) ? saved : defaultId;
    const host = h('div', { class: 'sd-panel' });
    const cache = {};
    function show(id) {
      active = id;
      if (!cache[id]) {
        const it = items.find((i) => i.id === id);
        try { cache[id] = it.render(); } catch (e) { console.error(e); cache[id] = TA.ui.error(e); }
      }
      TA.util.clear(host);
      host.appendChild(cache[id]);
    }
    const tabs = TA.ui.tabs({
      items: items.map((i) => ({ id: i.id, label: i.label, count: i.count })), active,
      onChange: (id) => { TA.util.store.set('sd.tab.' + group, id); show(id); },
    });
    show(active);
    return { el: h('div', { class: 'sd-tabs' }, tabs.el, host), switchTo(id) { tabs.set(id); show(id); } };
  }

  /* ================================================================== LLM */
  function llmInput(C, switchTo) {
    const { llm } = C;
    const req = llm.request || {};
    const msgs = Array.isArray(req.messages) ? req.messages : [];
    if (!msgs.length) return TA.ui.empty('Sem mensagens registradas', 'Esta chamada não guardou a entrada (ainda em andamento ou falhou antes de enviar).');
    return h('div', { class: 'sd-stack' },
      h('div', { class: 'sd-actions' },
        h('span', { class: 'muted' }, `Enviado ao modelo: ${TA.ui.messageStats(msgs)}`, nz(req.chars) && req.chars !== null ? ` (request: ${num(req.chars)} caracteres)` : ''),
        h('span', { class: 'spacer' }),
        TA.ui.copyBtn(() => TA.util.pretty(msgs), 'Copiar JSON'),
        h('button', { type: 'button', class: 'btn sm', onClick: () => switchTo('output') }, 'Ver saída →')),
      TA.ui.messages(msgs, { collapseSystem: true, markdown: true, toolRef: C.toolRef }));
  }

  function finishKind(r) { return { stop: 'ok', end_turn: 'ok', tool_calls: 'info', tool_use: 'info', length: 'warn', max_tokens: 'warn' }[r] || ''; }

  function llmOutput(C) {
    const { llm } = C;
    const r = llm.response || {};
    let msg = r.message;
    const calls = Array.isArray(r.tool_calls) ? r.tool_calls : [];
    if (!msg && (r.text || calls.length)) msg = { type: 'ai', content: r.text || '', tool_calls: calls };
    else if (msg && calls.length && !(Array.isArray(msg.tool_calls) && msg.tool_calls.length)) msg = Object.assign({}, msg, { tool_calls: calls });
    if (!msg) return TA.ui.empty('Sem resposta', llm.error ? 'A chamada falhou antes de devolver uma resposta.' : 'Nenhuma resposta registrada.');
    const u = llm.usage || {};
    return h('div', { class: 'sd-stack' },
      h('div', { class: 'sd-actions' },
        r.finish_reason ? h('span', { class: ['badge', finishKind(r.finish_reason)] }, 'finish: ' + r.finish_reason) : null,
        calls.length ? TA.ui.badge(`${calls.length} ${calls.length === 1 ? 'tool pedida' : 'tools pedidas'}`, 'info') : null,
        nz(u.output_tokens) ? h('span', { class: 'muted' }, `${num(u.output_tokens)} tokens de saída`) : null,
        u.reasoning_tokens ? h('span', { class: 'muted' }, `${num(u.reasoning_tokens)} de raciocínio`) : null,
        h('span', { class: 'spacer' }),
        TA.ui.copyBtn(() => TA.util.pretty(msg), 'Copiar JSON')),
      TA.ui.messages([msg], { toolbar: false, collapseSystem: false, markdown: true, toolRef: C.toolRef }));
  }

  function normSchema(s) {
    const f = s && isObj(s.function) ? s.function : (s || {});
    return { name: f.name || (s && s.name) || '?', description: f.description || (s && s.description) || '', params: f.parameters || f.input_schema || (s && (s.parameters || s.input_schema)) || null, raw: s };
  }

  function typeOf(p) {
    if (!p) return '';
    if (Array.isArray(p.enum)) return 'enum: ' + p.enum.join(' | ');
    if (Array.isArray(p.anyOf)) return p.anyOf.map(typeOf).join(' | ');
    if (p.type === 'array') return 'array<' + (p.items ? typeOf(p.items) || '?' : '?') + '>';
    return Array.isArray(p.type) ? p.type.join(' | ') : (p.type || '');
  }

  function paramsTable(params) {
    const props = params && isObj(params.properties) ? params.properties : null;
    if (!props || !Object.keys(props).length) return h('div', { class: 'muted xs' }, 'Sem parâmetros.');
    const req = new Set(Array.isArray(params.required) ? params.required : []);
    return h('table', { class: 't sd-ptable' }, h('thead', null, h('tr', null, ['Parâmetro', 'Tipo', 'Padrão', 'Descrição'].map((x) => h('th', null, x)))),
      h('tbody', null, Object.entries(props).map(([k, p]) => h('tr', null,
        h('td', null, h('span', { class: 'mono' }, k), req.has(k) ? h('span', { class: 'sd-req', title: 'obrigatório' }, '*') : null),
        h('td', { class: 'mono' }, typeOf(p) || '—'),
        h('td', { class: 'mono' }, p && p.default !== undefined ? JSON.stringify(p.default) : '—'),
        h('td', null, (p && p.description) || '—')))));
  }

  function llmTools(C) {
    const { llm } = C;
    const raw = Array.isArray(llm.tool_schemas) ? llm.tool_schemas : [];
    const requested = new Set(((llm.response && llm.response.tool_calls) || []).map((c) => c.name));
    if (!raw.length) {
      const names = Array.isArray(llm.tool_names) ? llm.tool_names : [];
      return names.length ? h('div', { class: 'sd-stack' }, h('div', { class: 'muted' }, 'Schemas não disponíveis; só os nomes:'), chips(names)) : TA.ui.empty('Nenhuma tool disponível nesta chamada');
    }
    const schemas = raw.map(normSchema);
    const list = h('div', { class: 'sd-toollist' });
    const cards = schemas.map((s) => {
      const asked = requested.has(s.name);
      const d = h('details', { class: ['sd-tool', asked && 'asked'], open: asked },
        h('summary', null,
          h('span', { class: 'sd-tool-name' }, s.name),
          asked ? TA.ui.badge('pedida', 'info') : null,
          h('span', { class: 'sd-tool-desc' }, TA.fmt.trunc(s.description.split('\n')[0], 130))),
        h('div', { class: 'sd-tool-body' },
          s.description ? h('pre', { class: 'ms-pre sd-desc' }, s.description) : h('div', { class: 'muted' }, 'Sem descrição.'),
          paramsTable(s.params),
          h('details', { class: 'ms-reason' }, h('summary', null, ' JSON do schema'), TA.ui.jsonTree(s.raw, { expand: 3 }))));
      return { el: d, hay: (s.name + ' ' + s.description).toLowerCase() };
    });
    cards.forEach((c) => list.appendChild(c.el));
    const search = TA.ui.searchInput({ placeholder: 'Filtrar tools…', delay: 120, onInput: (q) => { const t = q.toLowerCase(); cards.forEach((c) => c.el.classList.toggle('hidden', !!t && !c.hay.includes(t))); } });
    return h('div', { class: 'sd-stack' },
      h('div', { class: 'sd-actions' }, h('span', { class: 'muted' }, `${schemas.length} tools disponíveis · ${requested.size} pedida${requested.size === 1 ? '' : 's'}`), h('span', { class: 'spacer' }), search.el), list);
  }

  function llmUsage(C) {
    const { llm } = C;
    const u = llm.usage || {};
    const inT = u.input_tokens || 0, outT = u.output_tokens || 0;
    const total = nz(u.total_tokens) ? u.total_tokens : inT + outT;
    const cacheR = u.cache_read_tokens || 0, cacheW = u.cache_creation_tokens || 0, reas = u.reasoning_tokens || 0;
    const kpis = h('div', { class: 'grid grid-4' },
      TA.ui.kpi({ label: 'Tokens de entrada', value: num(u.input_tokens), sub: cacheR ? `${TA.fmt.pct(inT ? cacheR / inT : 0, 0)} vieram do cache` : null }),
      TA.ui.kpi({ label: 'Tokens de saída', value: num(u.output_tokens), sub: reas ? `${num(reas)} de raciocínio` : null }),
      TA.ui.kpi({ label: 'Custo', value: nz(llm.cost_usd) ? TA.fmt.cost(llm.cost_usd) : '—', sub: nz(llm.cost_usd) ? null : 'sem preço cadastrado' }),
      TA.ui.kpi({ label: 'Latência', value: TA.fmt.dur(llm.latency_s), sub: nz(llm.ttft_s) ? `1º token em ${TA.fmt.dur(llm.ttft_s)}` : null }));

    const bars = h('div', { class: 'grid grid-2' },
      TA.ui.card('Entrada', stackBar([
        { label: 'cache lido', value: cacheR, color: 'var(--c1)' },
        { label: 'cache criado', value: cacheW, color: 'var(--c3)' },
        { label: 'sem cache', value: Math.max(0, inT - cacheR - cacheW), color: 'var(--c4)' }], inT)),
      TA.ui.card('Saída', stackBar([
        { label: 'raciocínio', value: reas, color: 'var(--c5)' },
        { label: 'resposta', value: Math.max(0, outT - reas), color: 'var(--c2)' }], outT)));

    const row = (label, value, tokens, note) => h('tr', null,
      h('td', null, label),
      h('td', { class: 'r num' }, value),
      h('td', { class: 'sd-bar-cell' }, tokens !== undefined && total ? h('div', { class: 'sd-bar' }, h('span', { style: { width: Math.min(100, 100 * tokens / total) + '%' } })) : null),
      h('td', { class: 'muted' }, note || ''));
    const table = h('div', { class: 'table-wrap' }, h('table', { class: 't sd-usage' },
      h('thead', null, h('tr', null, h('th', null, 'Métrica'), h('th', { class: 'r' }, 'Valor'), h('th', null, 'Proporção do total'), h('th', null, 'Observação'))),
      h('tbody', null,
        row('Tokens de entrada', num(u.input_tokens), inT),
        row('Tokens de saída', num(u.output_tokens), outT),
        row('Total de tokens', num(total), total),
        row('Cache lido', num(u.cache_read_tokens), cacheR, inT && cacheR ? TA.fmt.pct(cacheR / inT) + ' da entrada' : ''),
        row('Cache criado', num(u.cache_creation_tokens), cacheW),
        row('Raciocínio', num(u.reasoning_tokens), reas, 'incluído na saída'),
        row('Áudio (entrada)', num(u.audio_in_tokens)),
        row('Áudio (saída)', num(u.audio_out_tokens)),
        row('Custo', nz(llm.cost_usd) ? TA.fmt.cost(llm.cost_usd) : '—', undefined, nz(llm.cost_usd) ? '' : 'modelo sem preço cadastrado'),
        row('Latência total', TA.fmt.dur(llm.latency_s)),
        row('Tempo até o 1º token (TTFT)', TA.fmt.dur(llm.ttft_s)),
        row('Tokens por segundo', nz(llm.tokens_per_second) ? Number(llm.tokens_per_second).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) : '—'),
        row('Chunks de stream', num(llm.n_stream_chunks), undefined, llm.streamed ? 'resposta em streaming' : 'sem streaming'),
        row('Retries', num((llm.retries || []).length)),
        row('Fonte do uso', u.usage_source || '—'))));
    return h('div', { class: 'sd-stack' }, kpis, bars, table,
      Array.isArray(llm.retries) && llm.retries.length ? section('Retries', tree(llm.retries, 2)) : null);
  }

  function llmMeta(C) {
    const { llm, span } = C;
    const r = llm.response || {};
    const m = llm.model || {};
    const link = (id) => (C.ix.toolByCall[id] ? C.link(C.ix.toolByCall[id].span_id, [h('span', { class: 'mono' }, TA.fmt.short(id, 16))]) : h('span', { class: 'mono' }, TA.fmt.short(id, 16)));
    return h('div', { class: 'sd-stack' },
      TA.ui.card('Modelo e execução', TA.ui.kv([
        ['Modelo pedido', m.requested ? h('span', { class: 'mono' }, m.requested) : null],
        ['Modelo retornado', m.returned || r.model_returned ? h('span', { class: 'mono' }, m.returned || r.model_returned) : null],
        ['Classe', m.class ? h('span', { class: 'mono' }, m.class) : null],
        ['Provider', m.provider],
        ['Propósito', llm.purpose === 'summary' ? 'resumo de contexto (middleware)' : llm.purpose],
        ['Agente', llm.agent], ['agent_id', llm.agent_id ? h('span', { class: 'mono' }, llm.agent_id) : null],
        ['Nó / step', [llm.node, nz(llm.step) ? 'step ' + llm.step : null].filter(Boolean).join(' · ') || null],
        ['Namespace', Array.isArray(llm.ns) && llm.ns.length ? h('span', { class: 'mono' }, llm.ns.join(' › ')) : null],
        ['finish_reason', r.finish_reason], ['response_id', r.response_id ? h('span', { class: 'mono' }, r.response_id) : null],
        ['service_tier', r.service_tier], ['system_fingerprint', r.system_fingerprint],
        ['Iniciada', llm.started_at ? TA.fmt.datetime(llm.started_at) : null], ['Terminada', llm.ended_at ? TA.fmt.datetime(llm.ended_at) : null],
        ['Pedida por (task)', llm.parent_tool_call_id ? link(llm.parent_tool_call_id) : null],
        ['Tools pedidas', Array.isArray(llm.caused_tool_call_ids) && llm.caused_tool_call_ids.length ? h('div', { class: 'sd-chips' }, llm.caused_tool_call_ids.map(link)) : null],
        ['tools_hash', llm.tools_hash ? h('span', { class: 'mono' }, llm.tools_hash) : null],
        ['seq', nz(llm.seq) ? llm.seq : (nz(span.seq) ? span.seq : null)],
      ])),
      hasKeys(llm.invocation_params) ? section('Parâmetros da invocação', tree(llm.invocation_params, 1)) : null,
      (llm.tags || []).length ? section('Tags', chips(llm.tags)) : null,
      hasKeys(llm.metadata) ? section('Metadados (LangChain)', tree(llm.metadata, 1)) : null,
      hasKeys(r.response_metadata) ? section('response_metadata', tree(r.response_metadata, 1)) : null,
      hasKeys(r.llm_output) ? section('llm_output', tree(r.llm_output, 1)) : null,
      hasKeys(r.generation_info) ? section('generation_info', tree(r.generation_info, 1)) : null);
  }

  function jsonTab(obj) {
    return h('div', { class: 'sd-stack' },
      h('div', { class: 'sd-actions' }, h('span', { class: 'muted' }, 'Registro completo, como gravado em disco.'), h('span', { class: 'spacer' }), TA.ui.copyBtn(() => TA.util.pretty(obj), 'Copiar JSON')),
      h('div', { class: 'sd-tree sd-tree-big' }, TA.ui.jsonTree(obj, { expand: 1 })));
  }

  function buildLlm(C) {
    const llm = C.llm;
    if (!llm) {
      return tabsView(C, 'llm', [{ id: 'json', label: 'JSON', render: () => jsonTab(C.span) }], 'json');
    }
    const msgs = (llm.request && llm.request.messages) || [];
    const calls = (llm.response && llm.response.tool_calls) || [];
    const schemas = llm.tool_schemas || llm.tool_names || [];
    let tv;
    const switchTo = (id) => tv.switchTo(id);
    tv = tabsView(C, 'llm', [
      { id: 'input', label: 'Entrada', count: msgs.length, render: () => llmInput(C, switchTo) },
      { id: 'output', label: 'Saída', count: calls.length || undefined, render: () => llmOutput(C) },
      { id: 'tools', label: 'Tools', count: schemas.length || undefined, render: () => llmTools(C) },
      { id: 'usage', label: 'Uso', render: () => llmUsage(C) },
      { id: 'meta', label: 'Metadados', render: () => llmMeta(C) },
      { id: 'json', label: 'JSON', render: () => jsonTab(llm) },
    ], 'input');
    return tv;
  }

  /* ================================================================== TOOL */
  function longStr(v) { return typeof v === 'string' && (v.length > 140 || v.includes('\n')); }

  function argsView(input, inputStr) {
    const modes = [{ value: 'fields', label: 'Campos' }, { value: 'json', label: 'JSON' }];
    if (inputStr) modes.push({ value: 'raw', label: 'Texto' });
    const host = h('div', { class: 'sd-args' });
    let mode = isObj(input) ? 'fields' : 'json';
    const mdKeys = /^(description|prompt|instructions?|task|message|text|content|query)$/;
    function paint() {
      TA.util.clear(host);
      if (mode === 'raw') { host.appendChild(TA.ui.code(inputStr, { maxHeight: 520 })); return; }
      if (mode === 'json' || !isObj(input)) { host.appendChild(h('div', { class: 'sd-tree' }, TA.ui.jsonTree(input === undefined ? {} : input, { expand: 3 }))); return; }
      const keys = Object.keys(input);
      if (!keys.length) { host.appendChild(h('div', { class: 'muted' }, '(sem argumentos)')); return; }
      keys.forEach((k) => {
        const v = input[k];
        let body;
        if (longStr(v)) body = richText(v, { md: mdKeys.test(k) && !/^(command|code)$/.test(k), maxHeight: 420 });
        else if (v !== null && typeof v === 'object') body = h('div', { class: 'sd-tree' }, TA.ui.jsonTree(v, { expand: 2 }));
        else body = h('span', { class: ['sd-val', typeof v === 'string' ? 's' : typeof v === 'number' ? 'n' : 'b'] }, v === null ? 'null' : String(v));
        host.appendChild(h('div', { class: 'sd-field' }, h('div', { class: 'sd-field-k' }, k), h('div', { class: 'sd-field-v' }, body)));
      });
    }
    paint();
    const seg = TA.ui.seg({ options: modes, value: mode, onChange: (v) => { mode = v; paint(); } });
    return h('div', { class: 'sd-stack' }, h('div', { class: 'sd-actions' }, seg.el, h('span', { class: 'spacer' }), TA.ui.copyBtn(() => TA.util.pretty(input), 'Copiar JSON')), host);
  }

  function toolOutputText(tool) {
    const o = tool.output;
    if (o === null || o === undefined) return null;
    if (typeof o === 'string') return o;
    if (nz(o.text)) return o.text;
    if (o.message && typeof o.message.content === 'string') return o.message.content;
    if (typeof o.content === 'string') return o.content;
    if (o.content !== undefined) return TA.util.pretty(o.content);
    return null;
  }

  const MD_HINT = /^(#{1,6} |\s*[-*] \S|\s*\d+\. \S|```|\*\*\S)/m;

  function outputView(text, toolName) {
    const parsed = TA.ui.tryJson(text);
    const looksSearch = toolName === 'internet_search' || /^\[1\] .*\nhttps?:\/\//.test(text);
    const search = looksSearch && text.length < 400000 ? TA.ui.searchResults(text) : null;
    const modes = [];
    if (search) modes.push({ value: 'results', label: 'Resultados' });
    if (parsed !== undefined) modes.push({ value: 'json', label: 'Árvore JSON' });
    modes.push({ value: 'md', label: 'Markdown' }, { value: 'text', label: 'Texto' });
    let mode = search ? 'results' : parsed !== undefined ? 'json' : (MD_HINT.test(text) && text.length <= 40000 ? 'md' : 'text');
    const host = h('div', { class: 'sd-out' });
    function paint() {
      TA.util.clear(host);
      if (mode === 'results' && search) host.appendChild(search);
      else if (mode === 'json' && parsed !== undefined) host.appendChild(h('div', { class: 'sd-tree' }, TA.ui.jsonTree(parsed, { expand: 2 })));
      else if (mode === 'md') host.appendChild(h('div', { class: 'sd-scroll sd-md-box', style: { maxHeight: '620px' } }, TA.ui.markdown(text)));
      else host.appendChild(TA.ui.code(text.length > 300000 ? text.slice(0, 300000) + '\n… (cortado; use Copiar para o texto completo)' : text, { maxHeight: 620 }));
    }
    paint();
    const seg = TA.ui.seg({ options: modes, value: mode, onChange: (v) => { mode = v; paint(); } });
    return { bar: seg.el, host };
  }

  function toolInput(C) {
    return argsView(C.tool.input, C.tool.input_str);
  }

  function toolOutput(C) {
    const { tool } = C;
    const text = toolOutputText(tool);
    const o = tool.output;
    const isErr = (o && o.is_error) || tool.status === 'error' || !!tool.error;
    const kids = [];
    const e = errInfo(tool.error);
    if (e && e.message && !(text && text === e.message)) kids.push(h('div', { class: 'sd-outerr' }, h('b', null, e.type + ': '), e.message));
    if (text === null || text === '') {
      kids.push(tool.status === 'running' ? TA.ui.empty('Ainda em execução', 'A saída aparece quando a tool terminar.') : TA.ui.empty(isErr ? 'A tool falhou sem saída' : 'Saída vazia'));
      return h('div', { class: 'sd-stack' }, kids);
    }
    const view = outputView(text, tool.name);
    kids.push(h('div', { class: 'sd-actions' }, view.bar,
      h('span', { class: 'muted xs' }, `${num(nz(tool.output_chars) ? tool.output_chars : text.length)} caracteres · ~${num(TA.ui.estimateTokens(text.length))} tokens`),
      isErr ? TA.ui.badge('erro', 'err') : null,
      h('span', { class: 'spacer' }), TA.ui.copyBtn(text, 'Copiar saída')));
    kids.push(h('div', { class: isErr ? 'sd-errbox' : null }, view.host));
    if (o && Array.isArray(o.update_keys) && o.update_keys.length) kids.push(h('div', { class: 'xs muted' }, 'Atualiza o estado do agente: ', chips(o.update_keys)));
    return h('div', { class: 'sd-stack' }, kids);
  }

  function toolMeta(C) {
    const { tool, span } = C;
    const llmSpan = tool.caused_by_llm_call_id ? C.ix.byId[tool.caused_by_llm_call_id] : null;
    const parentTask = tool.parent_tool_call_id ? C.ix.toolByCall[tool.parent_tool_call_id] : null;
    return h('div', { class: 'sd-stack' },
      TA.ui.card('Execução', TA.ui.kv([
        ['Tipo (kind)', tool.kind], ['Agente', tool.agent],
        ['agent_id', tool.agent_id ? h('span', { class: 'mono' }, tool.agent_id) : null],
        ['Namespace', Array.isArray(tool.ns) && tool.ns.length ? h('span', { class: 'mono' }, tool.ns.join(' › ')) : null],
        ['Pedida pela chamada LLM', tool.caused_by_llm_call_id ? (C.link(tool.caused_by_llm_call_id, [h('span', { class: 'mono' }, TA.fmt.short(tool.caused_by_llm_call_id, 16)), llmSpan && llmSpan.brief && llmSpan.brief.model ? ' · ' + llmSpan.brief.model : '', ' ', TA.ui.icon('external', 'sm')])) : null],
        ['Dentro da task', tool.parent_tool_call_id ? (parentTask ? C.link(parentTask.span_id, [h('span', { class: 'mono' }, TA.fmt.short(tool.parent_tool_call_id, 16)), ' ', TA.ui.icon('external', 'sm')]) : h('span', { class: 'mono' }, tool.parent_tool_call_id)) : null],
        ['Iniciada', tool.started_at ? TA.fmt.datetime(tool.started_at) : null], ['Terminada', tool.ended_at ? TA.fmt.datetime(tool.ended_at) : null],
        ['Duração', TA.fmt.dur(tool.duration_s)],
        ['Nó / step', [span.node, nz(span.step) ? 'step ' + span.step : null].filter(Boolean).join(' · ') || null],
        ['seq', nz(tool.seq) ? tool.seq : null],
      ])),
      (tool.tags || []).length ? section('Tags', chips(tool.tags)) : null,
      hasKeys(tool.data) ? section('Dados do classificador', tree(tool.data, 2), 'skill, caminho/operação, todos…') : null,
      tool.error ? section('Erro', tree(tool.error, 2)) : null,
      hasKeys(tool.metadata) ? section('Metadados (LangChain)', tree(tool.metadata, 1)) : null);
  }

  /* ================================================================== delegação (task) */
  function childSpansOf(C) {
    const { deleg, ix, span } = C;
    const set = new Map();
    const llmIds = new Set(deleg && deleg.llm_call_ids || []);
    const toolIds = new Set(deleg && deleg.tool_call_ids || []);
    descendants(ix, span.span_id).forEach((s) => { if (s.type === 'llm' || s.type === 'tool') set.set(s.span_id, s); });
    llmIds.forEach((id) => { if (ix.byId[id]) set.set(id, ix.byId[id]); });
    toolIds.forEach((id) => { const s = ix.toolByCall[id]; if (s) set.set(s.span_id, s); });
    set.delete(span.span_id);
    return Array.from(set.values()).sort((a, b) => offsetOf(a) - offsetOf(b) || (a.seq || 0) - (b.seq || 0));
  }

  function delegationTab(C) {
    const { deleg, tool } = C;
    const t = deleg.totals || {};
    const kids = childSpansOf(C);
    const typeLabel = { static: 'estático', dynamic: 'dinâmico (JS)', async: 'assíncrono' }[deleg.type] || deleg.type;
    return h('div', { class: 'sd-stack' },
      h('div', { class: 'sd-actions' },
        TA.ui.badge(deleg.subagent_type || (tool && tool.data && tool.data.subagent_type) || 'subagent', 'pink'),
        typeLabel ? TA.ui.chip(typeLabel) : null,
        TA.ui.statusBadge(deleg.status),
        nz(deleg.duration_s) ? h('span', { class: 'muted' }, TA.fmt.dur(deleg.duration_s)) : null),
      h('div', { class: 'grid grid-5' },
        TA.ui.kpi({ label: 'Chamadas LLM', value: num(t.llm_calls) }),
        TA.ui.kpi({ label: 'Tools', value: num(t.tool_calls) }),
        TA.ui.kpi({ label: 'Tokens de entrada', value: TA.fmt.compact(t.input_tokens) }),
        TA.ui.kpi({ label: 'Tokens de saída', value: TA.fmt.compact(t.output_tokens) }),
        TA.ui.kpi({ label: 'Custo', value: nz(t.cost_usd) ? TA.fmt.cost(t.cost_usd) : '—' })),
      deleg.error ? h('div', { class: 'sd-outerr' }, h('b', null, 'Erro da delegação: '), String(typeof deleg.error === 'string' ? deleg.error : (deleg.error.message || TA.util.pretty(deleg.error)))) : null,
      section('Tarefa enviada ao subagent', richText(deleg.description || (tool && tool.input && tool.input.description) || '', { md: true, maxHeight: 360 })),
      section('Resultado devolvido', richText(deleg.result || '', { md: true, maxHeight: 420 })),
      section(`O que o subagent fez (${kids.length} spans)`, spanTable(C, kids, 'Sem spans internos (subagent dinâmico ou rastro indisponível).')));
  }

  function buildTool(C) {
    const { tool, deleg } = C;
    if (!tool) return tabsView(C, 'tool', [{ id: 'json', label: 'JSON', render: () => jsonTab(C.span) }], 'json');
    const group = deleg ? 'task' : 'tool';
    const items = [];
    if (deleg) items.push({ id: 'deleg', label: 'Delegação', count: childSpansOf(C).length || undefined, render: () => delegationTab(C) });
    items.push(
      { id: 'input', label: 'Entrada', render: () => toolInput(C) },
      { id: 'output', label: 'Saída', count: nz(tool.output_chars) && tool.output_chars ? TA.fmt.compact(tool.output_chars) : undefined, render: () => toolOutput(C) },
      { id: 'meta', label: 'Metadados', render: () => toolMeta(C) },
      { id: 'json', label: 'JSON', render: () => jsonTab(tool) });
    return tabsView(C, group, items, deleg ? 'deleg' : 'input');
  }

  /* ================================================================== CHAIN */
  function chainSummary(C) {
    const { span, ix } = C;
    const io = span.io || {};
    const desc = descendants(ix, span.span_id);
    let nLlm = 0, nTool = 0, tin = 0, tout = 0, cost = 0, hasCost = false;
    desc.forEach((s) => {
      const b = s.brief || {};
      if (s.type === 'llm') { nLlm++; tin += b.input_tokens || 0; tout += b.output_tokens || 0; if (nz(b.cost_usd)) { cost += b.cost_usd; hasCost = true; } }
      else if (s.type === 'tool') nTool++;
    });
    const ioRows = Object.entries(io).map(([k, v]) => [k, Array.isArray(v) && v.every((x) => typeof x === 'string') ? chips(v) : (v !== null && typeof v === 'object') ? tree(v, 1) : v]);
    return h('div', { class: 'sd-stack' },
      desc.length ? h('div', { class: 'grid grid-5' },
        TA.ui.kpi({ label: 'Spans internos', value: num(desc.length) }),
        TA.ui.kpi({ label: 'Chamadas LLM', value: num(nLlm) }),
        TA.ui.kpi({ label: 'Tools', value: num(nTool) }),
        TA.ui.kpi({ label: 'Tokens (in → out)', value: `${TA.fmt.compact(tin)} → ${TA.fmt.compact(tout)}` }),
        TA.ui.kpi({ label: 'Custo', value: hasCost ? TA.fmt.cost(cost) : '—' })) : null,
      TA.ui.card('Entradas e saídas (io)', ioRows.length ? TA.ui.kv(ioRows) : h('span', { class: 'muted' }, 'Sem dados de io.')),
      TA.ui.card('Execução', TA.ui.kv([
        ['Nó', span.node], ['Step', nz(span.step) ? span.step : null], ['Agente', span.agent],
        ['Namespace', Array.isArray(span.ns) && span.ns.length ? h('span', { class: 'mono' }, span.ns.join(' › ')) : null],
        ['Profundidade', nz(span.depth) ? span.depth : null],
        ['Iniciado', span.started_at ? TA.fmt.datetime(span.started_at) : null], ['Terminado', span.ended_at ? TA.fmt.datetime(span.ended_at) : null],
      ])),
      (span.tags || []).length ? section('Tags', chips(span.tags)) : null,
      hasKeys(span.metadata) ? section('Metadados', tree(span.metadata, 1)) : null);
  }

  function buildChain(C) {
    const kids = (C.ix.kids[C.span.span_id] || []).slice().sort((a, b) => offsetOf(a) - offsetOf(b) || (a.seq || 0) - (b.seq || 0));
    const n = kids.length || (Array.isArray(C.span.children) ? C.span.children.length : 0);
    return tabsView(C, 'chain', [
      { id: 'summary', label: 'Resumo', render: () => chainSummary(C) },
      { id: 'children', label: 'Filhos', count: n || undefined, render: () => (kids.length ? spanTable(C, kids) : TA.ui.empty('Sem filhos', n ? 'O trace completo não foi carregado, então só há os ids.' : 'Este span não tem spans filhos.')) },
      { id: 'json', label: 'JSON', render: () => jsonTab(C.span) },
    ], 'summary');
  }

  /* ================================================================== entrada principal */
  function scrollTop(el) {
    let n = el;
    for (let i = 0; n && i < 4; i++, n = n.parentNode) { try { n.scrollTop = 0; } catch (e) { /* ignora */ } }
  }

  function draw(el, C) {
    const kindTool = C.span.type === 'tool' || !!C.tool;
    let body;
    if (C.span.type === 'llm' || (C.llm && !kindTool)) body = buildLlm(C);
    else if (kindTool) body = buildTool(C);
    else body = buildChain(C);
    // o cabeçalho precisa do `switchTo` das abas só para o LLM, que cuida dele por dentro; aqui só montamos
    const root = h('div', { class: 'sd-root' }, errorBanner(C), header(C), body.el);
    TA.util.clear(el);
    el.appendChild(root);
    scrollTop(el);
  }

  /** Carrega e desenha o span `spanId` do run `runId` dentro de `el`. */
  async function render(el, opts) {
    const { runId, spanId, trace, onSelect } = opts || {};
    const token = {};
    el._sdToken = token;
    TA.util.clear(el);
    el.appendChild(TA.ui.loading('Carregando span…'));
    if (!runId || !spanId) { TA.util.clear(el); el.appendChild(TA.ui.empty('Nenhum span selecionado', 'Escolha um span na árvore ao lado.')); return; }
    let data;
    try {
      data = await TA.api.span(runId, spanId);
    } catch (e) {
      if (el._sdToken !== token) return;
      TA.util.clear(el);
      el.appendChild(TA.ui.error(e));
      return;
    }
    if (el._sdToken !== token) return;
    let tr = trace;
    if (!tr || !Array.isArray(tr.spans)) { try { tr = await TA.api.trace(runId); } catch (e) { tr = null; } }
    if (el._sdToken !== token) return;
    try {
      if (!data || !data.span) { TA.util.clear(el); el.appendChild(TA.ui.empty('Span não encontrado', spanId)); return; }
      const C = {
        runId, spanId, data, span: data.span, llm: data.llm_call || null, tool: data.tool_call || null, deleg: data.delegation || null,
        trace: tr, ix: indexTrace(tr), onSelect,
      };
      makeNav(C);
      draw(el, C);
    } catch (e) {
      console.error(e);
      TA.util.clear(el);
      el.appendChild(TA.ui.error(e));
    }
  }
})();
