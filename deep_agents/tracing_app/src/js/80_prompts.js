/* Prompts & configurações: lista de versões (`#/prompts`) e detalhe/comparação de uma versão (`#/prompts/:hash`).
   Cada `configs/<hash>.json` é um snapshot da configuração declarada do agente (system prompt com a data do dia, regras, skills,
   subagents, limites...). Classes CSS: prefixo `.pm-` (src/css/70_prompts.css). */
(function () {
  const h = TA.h;

  /* ------------------------------------------------------------------ utilitários */
  const words = (s) => { const t = String(s || '').trim(); return t ? t.split(/\s+/).length : 0; };
  const tokensOf = (chars) => Math.round((chars || 0) / 4);   // estimativa grosseira: ~4 caracteres por token
  const linesOf = (s) => (s ? String(s).split('\n').length : 0);
  const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
  const entries = (o) => (isObj(o) ? Object.entries(o) : []);
  const hashChip = (hash) => h('span', { class: 'pm-hash', title: hash }, TA.fmt.short(hash, 8));
  const link = (path, query, ...kids) => TA.router.link(path, query, ...kids);

  /** bloco de texto longo, com copiar */
  function textBlock(text, maxHeight) {
    const t = text === null || text === undefined ? '' : String(text);
    if (!t) return h('div', { class: 'pm-none' }, 'vazio');
    return h('div', { class: 'pm-code' }, TA.ui.code(t, { maxHeight: maxHeight || 520 }));
  }

  /** linha de métricas de um texto: caracteres · palavras · linhas · tokens estimados */
  function textStats(text, extra) {
    const chars = text ? String(text).length : 0;
    return h('div', { class: 'pm-stats' },
      stat('Caracteres', TA.fmt.num(chars)), stat('Palavras', TA.fmt.num(words(text))),
      stat('Linhas', TA.fmt.num(linesOf(text))), stat('Tokens (≈ chars/4)', '≈ ' + TA.fmt.num(tokensOf(chars))), extra || null);
  }
  function stat(label, value) { return h('div', { class: 'pm-stat' }, h('div', { class: 'v num' }, value), h('div', { class: 'l' }, label)); }

  function section(title, body, opts) { return h('div', { class: 'pm-section' }, TA.ui.card(title, body, opts)); }

  /** acordeão com corpo renderizado sob demanda. items: [{title, meta: Node[], render: () => Node, open?}] */
  function accordion(items) {
    const parts = items.map((it) => {
      const body = h('div', { class: 'pm-acc-body hidden' });
      const head = h('button', { type: 'button', class: 'pm-acc-head', 'aria-expanded': 'false' },
        TA.ui.icon('chevR', 'pm-chev'), h('span', { class: 'pm-acc-title' }, it.title), h('span', { class: 'spacer' }), it.meta || null);
      const root = h('div', { class: 'pm-acc-item' }, head, body);
      let built = false;
      const set = (open) => {
        if (open && !built) {
          built = true;
          try { body.appendChild(it.render()); } catch (e) { body.appendChild(TA.ui.error(e)); }
        }
        body.classList.toggle('hidden', !open);
        root.classList.toggle('open', open);
        head.setAttribute('aria-expanded', open ? 'true' : 'false');
      };
      head.addEventListener('click', () => set(body.classList.contains('hidden')));
      if (it.open) set(true);
      return { root, set };
    });
    const tools = h('div', { class: 'pm-acc-tools' },
      h('button', { class: 'btn sm ghost', onClick: () => parts.forEach((p) => p.set(true)) }, 'Expandir tudo'),
      h('button', { class: 'btn sm ghost', onClick: () => parts.forEach((p) => p.set(false)) }, 'Recolher tudo'));
    return h('div', { class: 'pm-acc' }, parts.length > 1 ? tools : null, parts.map((p) => p.root));
  }

  /** arquivo de texto (regra/skill): sha, caracteres, tokens; alterna texto bruto/markdown quando disponível */
  function fileItem(f) {
    const chars = f.chars !== undefined && f.chars !== null ? f.chars : String(f.text || '').length;
    const truncated = f.text && String(f.text).length < chars;
    return {
      title: f.path || '(sem caminho)',
      meta: h('span', { class: 'pm-meta' },
        f.sha256 ? h('span', { class: 'pm-sha', title: 'sha256 (16 primeiros)' }, String(f.sha256).slice(0, 12)) : null,
        h('span', { class: 'muted num' }, TA.fmt.num(chars) + ' car.'),
        h('span', { class: 'faint num' }, '≈ ' + TA.fmt.num(tokensOf(chars)) + ' tok.'),
        truncated ? TA.ui.badge('truncado', 'warn', 'O snapshot guarda só parte do texto') : null),
      render() {
        const raw = textBlock(f.text, 560);
        if (typeof TA.ui.markdown !== 'function') return raw;
        const mdBox = h('div', { class: 'pm-md hidden' });
        let mdBuilt = false;
        const sw = TA.ui.seg({
          options: [{ value: 'raw', label: 'Texto' }, { value: 'md', label: 'Markdown' }], value: 'raw',
          onChange: (v) => {
            if (v === 'md' && !mdBuilt) { mdBuilt = true; try { mdBox.appendChild(TA.ui.markdown(String(f.text || ''))); } catch (e) { mdBox.appendChild(TA.ui.error(e)); } }
            raw.classList.toggle('hidden', v === 'md'); mdBox.classList.toggle('hidden', v !== 'md');
          },
        });
        return h('div', null, h('div', { class: 'pm-body-tools' }, sw.el), raw, mdBox);
      },
    };
  }

  /* ================================================================== LISTA */
  TA.views.prompts = {
    mount(ctx) {
      ctx.crumbs([{ label: 'Prompts' }]);
      const q = ctx.query;
      const state = { sort: q.sort || 'created_at', order: q.order === 'asc' ? 'asc' : 'desc', sel: (q.sel ? String(q.sel).split(',') : []).slice(0, 2), items: [] };
      let gone = false;
      ctx.onCleanup(() => { gone = true; });

      const page = h('div', { class: 'page pm' });
      ctx.el.appendChild(page);
      page.appendChild(h('div', { class: 'page-head' },
        h('div', null, h('h1', null, 'Prompts & configurações'),
          h('div', { class: 'sub' }, 'Cada hash é uma versão da configuração do agente: system prompt (com a data do dia), regras, skills, subagents e limites. Selecione duas versões para comparar.'))));
      const kpis = h('div', { class: 'grid grid-4 pm-kpis' });
      const bar = h('div', { class: 'pm-bar' });
      const tableBox = h('div', { class: 'pm-tablebox' }, TA.ui.loading());
      page.append(kpis, bar, tableBox);

      const compareBtn = h('button', { class: 'btn primary', onClick: goCompare }, TA.ui.icon('branch', 'sm'), 'Comparar');
      const selInfo = h('span', { class: 'muted small' });
      bar.append(compareBtn, selInfo, h('span', { class: 'spacer' }));
      const clearBtn = h('button', { class: 'btn sm ghost', onClick: () => { state.sel = []; syncSel(); } }, 'Limpar seleção');
      bar.appendChild(clearBtn);

      let table = null;

      function byHash(hash) { return state.items.find((i) => i.hash === hash); }
      function goCompare() {
        if (state.sel.length !== 2) return;
        // A = a mais antiga, B = a mais nova
        const [x, y] = state.sel.map(byHash);
        const older = x && y && (x.created_at || '') > (y.created_at || '') ? [state.sel[1], state.sel[0]] : state.sel;
        ctx.nav('prompts/' + older[0], { diff: older[1] });
      }
      function syncSel() {
        ctx.setQuery({ sel: state.sel.join(',') });
        compareBtn.disabled = state.sel.length !== 2;
        clearBtn.classList.toggle('hidden', !state.sel.length);
        selInfo.textContent = state.sel.length === 2 ? '2 versões selecionadas' : state.sel.length === 1 ? 'Selecione mais uma versão' : 'Selecione 2 versões para comparar';
        if (table) table.setRows(sorted());
      }
      function toggle(hash, on) {
        state.sel = state.sel.filter((x) => x !== hash);
        if (on) state.sel.push(hash);
        if (state.sel.length > 2) state.sel = state.sel.slice(-2);   // mantém as duas mais recentes escolhas
        syncSel();
      }
      function sorted() {
        const k = state.sort, dir = state.order === 'asc' ? 1 : -1;
        return state.items.slice().sort((a, b) => {
          const va = a[k], vb = b[k];
          if (va === vb) return 0;
          if (va === null || va === undefined) return 1;
          if (vb === null || vb === undefined) return -1;
          return (va > vb ? 1 : -1) * dir;
        });
      }

      function columns(latest) {
        return [
          { key: 'sel', label: '', width: '34px', render: (r) => h('input', {
            type: 'checkbox', class: 'pm-check', checked: state.sel.includes(r.hash), title: 'Selecionar para comparar', 'aria-label': 'Selecionar ' + r.hash,
            onClick: (e) => { e.stopPropagation(); toggle(r.hash, e.target.checked); },
          }) },
          { key: 'hash', label: 'Versão', sortable: true, render: (r) => h('span', { class: 'pm-hashcell' },
            link('prompts/' + r.hash, null, h('span', { class: 'pm-hash' }, TA.fmt.short(r.hash, 8))),
            r.hash === latest ? TA.ui.badge('mais recente', 'accent') : null) },
          { key: 'model', label: 'Modelo', sortable: true, render: (r) => h('span', { class: 'mono small' }, r.model || '—') },
          { key: 'created_at', label: 'Criada em', sortable: true, render: (r) => h('span', { class: 'nowrap', title: r.created_at || '' }, TA.fmt.datetime(r.created_at)) },
          { key: 'system_prompt_chars', label: 'System prompt', sortable: true, align: 'r', title: 'Caracteres do system prompt', render: (r) => TA.fmt.num(r.system_prompt_chars) },
          { key: 'n_rules', label: 'Regras', sortable: true, align: 'r', render: (r) => TA.fmt.num(r.n_rules) },
          { key: 'n_skills', label: 'Skills', sortable: true, align: 'r', render: (r) => TA.fmt.num(r.n_skills) },
          { key: 'n_subagents', label: 'Subagents', sortable: true, align: 'r', render: (r) => TA.fmt.num(r.n_subagents) },
          { key: 'runs', label: 'Runs', sortable: true, align: 'r', title: 'Runs que usaram esta versão', render: (r) => TA.fmt.num(r.runs) },
          { key: 'last_used_at', label: 'Último uso', sortable: true, render: (r) => h('span', { class: 'nowrap muted', title: r.last_used_at || '' }, TA.fmt.rel(r.last_used_at)) },
        ];
      }

      async function load() {
        try {
          const res = await TA.api.configs();
          if (gone) return;
          state.items = (res && res.items) || [];
          state.sel = state.sel.filter((x) => byHash(x));
          const latest = state.items.slice().sort((a, b) => ((b.created_at || '') > (a.created_at || '') ? 1 : -1))[0];
          const models = new Set(state.items.map((i) => i.model).filter(Boolean));
          const totalRuns = TA.util.sum(state.items, (i) => i.runs || 0);
          const maxChars = Math.max(0, ...state.items.map((i) => i.system_prompt_chars || 0));
          TA.util.clear(kpis);
          kpis.append(
            TA.ui.kpi({ label: 'Versões', value: TA.fmt.num(state.items.length), sub: latest ? 'última: ' + TA.fmt.rel(latest.created_at) : null }),
            TA.ui.kpi({ label: 'Modelos distintos', value: TA.fmt.num(models.size), sub: Array.from(models).slice(0, 2).join(', ') }),
            TA.ui.kpi({ label: 'Runs cobertos', value: TA.fmt.num(totalRuns) }),
            TA.ui.kpi({ label: 'Maior system prompt', value: TA.fmt.num(maxChars) + ' car.', sub: '≈ ' + TA.fmt.num(tokensOf(maxChars)) + ' tokens' }));
          TA.util.clear(tableBox);
          if (!state.items.length) { tableBox.appendChild(TA.ui.empty('Nenhuma configuração ainda', 'As versões aparecem aqui depois do primeiro run rastreado.')); return; }
          table = TA.ui.table({
            columns: columns(latest && latest.hash), rows: sorted(), sort: { key: state.sort, order: state.order },
            rowId: (r) => r.hash, onRowClick: (r) => ctx.nav('prompts/' + r.hash),
            onSort: (key, order) => { state.sort = key; state.order = order; ctx.setQuery({ sort: key, order }); table.setSort({ key, order }); table.setRows(sorted()); },
          });
          tableBox.appendChild(table.el);
          syncSel();
        } catch (e) { if (!gone) { TA.util.clear(tableBox); tableBox.appendChild(TA.ui.error(e)); } }
      }
      ctx.onRefresh(load);
      syncSel();
      load();
    },
  };

  /* ================================================================== DETALHE */
  const TABS = [
    ['system', 'System prompt'], ['harness', 'Perfil do harness'], ['rules', 'Regras'], ['skills', 'Skills'], ['subagents', 'Subagents'],
    ['model', 'Modelo & limites'], ['perms', 'Permissões'], ['json', 'JSON'], ['diff', 'Comparar'],
  ];

  TA.views.prompt = {
    mount(ctx) {
      const hash = ctx.params.hash;
      ctx.crumbs([{ label: 'Prompts', href: TA.router.hashFor('prompts') }, { label: TA.fmt.short(hash, 8) }]);
      const state = { tab: ctx.query.tab || (ctx.query.diff ? 'diff' : 'system'), diff: ctx.query.diff || '' };
      if (!TABS.some((t) => t[0] === state.tab)) state.tab = 'system';
      let gone = false;
      let token = 0;
      ctx.onCleanup(() => { gone = true; });

      const page = h('div', { class: 'page pm' });
      ctx.el.appendChild(page);
      const head = h('div', { class: 'pm-head' });
      const tabsBox = h('div', { class: 'pm-tabsbox' });
      const body = h('div', { class: 'pm-tabbody' });
      page.append(head, tabsBox, body);
      head.appendChild(TA.ui.loading());

      let cfg = null, meta = null, all = [], tabs = null;

      function renderHead() {
        TA.util.clear(head);
        const P = cfg.prompts || {};
        const M = cfg.model || {};
        const runs = cfg.runs || [];
        const sysChars = P.system_prompt ? String(P.system_prompt).length : (meta && meta.system_prompt_chars) || 0;
        const created = cfg.created_at || (meta && meta.created_at);
        head.append(
          h('div', { class: 'pm-title' },
            h('h1', null, 'Configuração ', h('span', { class: 'pm-hash big' }, TA.fmt.short(hash, 8))),
            TA.ui.badge(M.spec || (meta && meta.model) || 'modelo ?', 'purple'),
            h('span', { class: 'spacer' }),
            TA.ui.copyBtn(hash, 'Copiar hash'),
            link('prompts', null, '← todas as versões')),
          h('div', { class: 'sub pm-sub' }, h('span', { class: 'mono', title: hash }, hash), ' · criada em ', TA.fmt.datetime(created),
            meta && meta.last_used_at ? ' · último uso ' + TA.fmt.rel(meta.last_used_at) : ''),
          h('div', { class: 'grid grid-5 pm-kpis' },
            TA.ui.kpi({ label: 'Runs que usaram', value: TA.fmt.num(runs.length), sub: runs.length ? link('runs', { model: M.spec }, 'ver no Traces →') : null }),
            TA.ui.kpi({ label: 'System prompt', value: TA.fmt.num(sysChars), sub: '≈ ' + TA.fmt.num(tokensOf(sysChars)) + ' tokens' }),
            TA.ui.kpi({ label: 'Regras · Skills', value: `${(P.rules || []).length} · ${(P.skills || []).length}` }),
            TA.ui.kpi({ label: 'Subagents', value: TA.fmt.num(entries(cfg.subagents).length), sub: entries(cfg.subagents).filter(([, s]) => s && s.enabled).length + ' habilitados' }),
            TA.ui.kpi({ label: 'Limite de chamadas', value: cfg.limits && cfg.limits.model_call_limit !== undefined ? TA.fmt.num(cfg.limits.model_call_limit) : '—', sub: 'ao modelo por resposta' })),
          runsBlock(runs));
      }

      /** lista dos runs que usaram esta versão */
      function runsBlock(runs) {
        if (!runs.length) return h('div', { class: 'pm-runs muted small' }, 'Nenhum run registrado com esta versão.');
        let showAll = false;
        const box = h('div', { class: 'pm-runbox' });
        const paint = () => {
          TA.util.clear(box);
          const rows = showAll ? runs : runs.slice(0, 6);
          const t = TA.ui.table({
            rows, rowId: (r) => r.run_id, onRowClick: (r) => ctx.nav('runs/' + r.run_id),
            columns: [
              { key: 'started_at', label: 'Quando', render: (r) => h('span', { class: 'nowrap', title: r.started_at || '' }, TA.fmt.datetime(r.started_at)) },
              { key: 'run_id', label: 'Run', render: (r) => link('runs/' + r.run_id, null, h('span', { class: 'pm-hash' }, TA.fmt.short(r.run_id))) },
              { key: 'status', label: 'Status', render: (r) => TA.ui.statusBadge(r.status) },
              { key: 'user_message', label: 'Mensagem', render: (r) => h('span', { class: 'pm-trunc', title: r.user_message || '' }, TA.fmt.trunc(r.user_message, 110)) },
              { key: 'total_tokens', label: 'Tokens', align: 'r', render: (r) => TA.fmt.num(r.total_tokens) },
              { key: 'cost_usd', label: 'Custo', align: 'r', render: (r) => TA.fmt.cost(r.cost_usd) },
              { key: 'duration_s', label: 'Duração', align: 'r', render: (r) => TA.fmt.dur(r.duration_s) },
            ],
          });
          box.appendChild(t.el);
          if (runs.length > 6) box.appendChild(h('button', { class: 'btn sm ghost', onClick: () => { showAll = !showAll; paint(); } }, showAll ? 'Mostrar menos' : `Mostrar todos os ${runs.length} runs`));
        };
        paint();
        return h('details', { class: 'pm-runs', open: runs.length <= 6 }, h('summary', null, `Runs que usaram esta versão (${runs.length})`), box);
      }

      /* ---------------------------------------------------------------- abas */
      const R = {
        system() {
          const P = cfg.prompts || {};
          if (P.error) return TA.ui.error(P.error);
          return h('div', null,
            textStats(P.system_prompt, h('div', { class: 'pm-stat grow' }, h('div', { class: 'l' }, 'Texto exatamente como enviado como system prompt (inclui a data do dia). O perfil do harness e as regras entram à parte.'))),
            textBlock(P.system_prompt, 680));
        },

        harness() {
          const P = cfg.prompts || {};
          const hp = P.harness_profile;
          if (!hp) return TA.ui.empty('Sem perfil do harness', 'Este snapshot não registrou o perfil.');
          if (hp.error) return TA.ui.error(hp.error);
          const over = entries(hp.tool_description_overrides);
          const excl = hp.excluded_tools || [];
          return h('div', { class: 'pm-stack' },
            section('Prompt base', h('div', null, h('p', { class: 'pm-note' }, 'Substitui o system prompt base do harness para o modelo.'), textBlock(hp.base_system_prompt, 320))),
            section('Sufixo do system prompt', h('div', null, h('p', { class: 'pm-note' }, 'Anexado ao final do prompt do agente principal.'), textBlock(hp.system_prompt_suffix, 320))),
            section('Descrições de tools sobrescritas', over.length
              ? h('div', { class: 'pm-stack' }, over.map(([name, txt]) => h('div', { class: 'pm-over' }, h('div', { class: 'pm-over-name' }, TA.ui.kindIcon('tool'), h('span', { class: 'mono bold' }, name)), textBlock(txt, 220))))
              : h('div', { class: 'pm-none' }, 'nenhuma sobrescrita'), { hint: over.length + ' tool(s)' }),
            section('Tools excluídas', excl.length ? h('div', { class: 'pm-chips' }, excl.map((t) => TA.ui.chip(t, true))) : h('div', { class: 'pm-none' }, 'nenhuma'), { hint: 'o agente não enxerga estas tools' }));
        },

        rules() {
          const P = cfg.prompts || {};
          const rules = P.rules || [];
          const mem = P.memory_files || [];
          const total = TA.util.sum(rules, (r) => r.chars || 0);
          return h('div', { class: 'pm-stack' },
            h('div', { class: 'pm-stats' }, stat('Regras', TA.fmt.num(rules.length)), stat('Caracteres', TA.fmt.num(total)), stat('Tokens (≈)', '≈ ' + TA.fmt.num(tokensOf(total)))),
            rules.length ? accordion(rules.map(fileItem)) : TA.ui.empty('Sem regras', 'Nenhum arquivo .md em prompts/rules neste snapshot.'),
            mem.length ? section('Ordem de carga (memory=)', h('ol', { class: 'pm-ol' }, mem.map((m) => h('li', { class: 'mono small' }, m))), { hint: 'as regras entram no prompt nesta ordem' }) : null);
        },

        skills() {
          const P = cfg.prompts || {};
          const sk = P.skills || [];
          const dirs = P.skills_dirs || [];
          return h('div', { class: 'pm-stack' },
            h('div', { class: 'pm-stats' }, stat('Skills', TA.fmt.num(sk.length)), stat('Caracteres', TA.fmt.num(TA.util.sum(sk, (r) => r.chars || 0)))),
            sk.length ? accordion(sk.map(fileItem)) : TA.ui.empty('Sem skills', 'Nenhum SKILL.md neste snapshot.'),
            h('p', { class: 'pm-note' }, 'O agente só vê nome e descrição da skill no prompt; o SKILL.md completo é lido sob demanda.'),
            dirs.length ? section('Pastas de skills', h('div', { class: 'pm-chips' }, dirs.map((d) => TA.ui.chip(d, true)))) : null);
        },

        subagents() {
          const subs = entries(cfg.subagents);
          const dyn = cfg.dynamic_subagents;
          const runs = cfg.runs || [];
          const withSub = runs.filter((r) => (r.subagent_calls || 0) > 0).length;
          const parts = [];
          parts.push(h('div', { class: 'pm-stats' },
            stat('Subagents', TA.fmt.num(subs.length)),
            stat('Habilitados', TA.fmt.num(subs.filter(([, s]) => s && s.enabled).length)),
            stat('Runs com delegação', `${withSub} de ${runs.length}`),
            dyn ? stat('Dinâmicos', dyn.enabled ? 'ligados' : 'desligados') : null,
            h('span', { class: 'spacer' }),
            link('runs', { tool: 'task' }, h('span', { class: 'btn sm' }, TA.ui.icon('external', 'sm'), 'Ver runs que chamaram task'))));
          if (!subs.length) parts.push(TA.ui.empty('Sem subagents', 'Esta versão não declara subagents.'));
          else parts.push(accordion(subs.map(([name, s]) => {
            s = s || {};
            return {
              title: name,
              open: subs.length === 1,
              meta: h('span', { class: 'pm-meta' }, TA.ui.badge(s.enabled ? 'habilitado' : 'desabilitado', s.enabled ? 'ok' : ''),
                h('span', { class: 'faint num' }, TA.fmt.num(String(s.system_prompt || '').length) + ' car.')),
              render() {
                const tk = entries(s.toolkit);
                return h('div', { class: 'pm-stack' },
                  h('div', null, h('div', { class: 'pm-label' }, 'Descrição (o que o agente principal lê para decidir delegar)'), h('div', { class: 'pm-desc' }, s.description || '—')),
                  h('div', null, h('div', { class: 'pm-label' }, 'Tools'),
                    tk.length ? h('div', { class: 'pm-chips' }, tk.map(([g, v]) => {
                      const tools = v && v.tools;
                      return TA.ui.chip(`${g}: ${Array.isArray(tools) ? tools.join(', ') : 'todas as tools'}${v && v.enabled === false ? ' (desligado)' : ''}`, true);
                    })) : h('span', { class: 'pm-none' }, 'nenhuma')),
                  h('div', null, h('div', { class: 'pm-label' }, 'System prompt'), textStats(s.system_prompt), textBlock(s.system_prompt, 460)),
                  link('runs', { tool: 'task' }, 'Ver eventos reais de delegação em Traces →'));
              },
            };
          })));
          if (dyn) {
            parts.push(section('Subagents dinâmicos', TA.ui.kv([
              ['Habilitados', dyn.enabled ? 'sim' : 'não'], ['Concorrência máxima', dyn.max_concurrency === null || dyn.max_concurrency === undefined ? 'padrão (' + ((cfg.limits || {}).dynamic_max_concurrency ?? '—') + ')' : dyn.max_concurrency]]),
            { hint: 'tool eval (REPL JavaScript) despacha os papéis registrados' }));
          }
          return h('div', { class: 'pm-stack' }, parts);
        },

        model() {
          const M = cfg.model || {};
          const P = cfg.prompts || {};
          const L = cfg.limits || {};
          const S = cfg.streaming || {};
          const LIMIT_DESC = {
            model_call_limit: 'Teto de chamadas ao modelo por resposta (agente principal)',
            subagent_call_limit: 'Teto de chamadas por tarefa delegada a um subagent',
            dynamic_max_concurrency: 'Paralelismo máximo dos subagents dinâmicos',
            summary_trigger_tokens: 'Tokens de contexto que disparam o resumo',
            trim_tokens_to_summarize: 'Tokens enviados ao resumo (vazio = tudo)',
            keep_messages: 'Mensagens recentes mantidas depois do resumo',
          };
          const val = (v) => (v === null || v === undefined ? h('span', { class: 'faint' }, '—') : typeof v === 'object' ? h('span', { class: 'mono' }, JSON.stringify(v)) : h('span', { class: 'mono' }, String(v)));
          return h('div', { class: 'pm-stack' },
            h('div', { class: 'grid grid-2' },
              section('Modelo', TA.ui.kv([
                ['Spec', val(M.spec)], ['Provedor', val(M.provider)], ['Modelo', val(M.model_id)], ['Temperature', val(M.temperature)],
                ['Thinking', val(M.thinking)], ['Max tokens', val(M.max_tokens)], ['Timeout (s)', val(M.timeout)], ['Max retries', val(M.max_retries)]])),
              section('Limites', h('div', { class: 'pm-limits' }, entries(L).map(([k, v]) => h('div', { class: 'pm-limit' },
                h('div', { class: 'pm-limit-k' }, h('span', { class: 'mono' }, k), h('div', { class: 'muted xs' }, LIMIT_DESC[k] || '')),
                h('div', { class: 'pm-limit-v num' }, v === null || v === undefined ? '—' : TA.fmt.num(v))))))),
            h('div', { class: 'grid grid-2' },
              section('Parâmetros resolvidos (resolved_kwargs)', h('div', null,
                h('p', { class: 'pm-note' }, 'O que as regras do provedor (ProviderRules) fazem com a configuração antes de chamar a API.'),
                entries(M.resolved_kwargs).length ? TA.ui.jsonTree(M.resolved_kwargs, { expand: 2 }) : h('div', { class: 'pm-none' }, 'vazio'))),
              section('Extra', entries(M.extra).length ? TA.ui.jsonTree(M.extra, { expand: 2 }) : h('div', { class: 'pm-none' }, 'sem parâmetros extras'))),
            section('Resumo de contexto (summary prompt)', h('div', null,
              h('p', { class: 'pm-note' }, `Dispara quando o contexto passa de ${L.summary_trigger_tokens !== undefined && L.summary_trigger_tokens !== null ? TA.fmt.num(L.summary_trigger_tokens) : '?'} tokens; mantém as ${L.keep_messages ?? '?'} últimas mensagens.`),
              textStats(P.summary_prompt), textBlock(P.summary_prompt, 320))),
            section('Streaming', entries(S).length ? TA.ui.kv(entries(S).map(([k, v]) => [h('span', { class: 'mono' }, k), val(typeof v === 'string' ? TA.fmt.trunc(v, 80) : v)])) : h('div', { class: 'pm-none' }, 'sem opções registradas')),
            section('Toolkit', entries(cfg.toolkit).length ? h('div', { class: 'pm-chips' }, entries(cfg.toolkit).map(([g, v]) =>
              TA.ui.chip(`${g}: ${v && Array.isArray(v.tools) ? v.tools.join(', ') : 'todas as tools'}${v && v.enabled === false ? ' (desligado)' : ''}`, true))) : h('div', { class: 'pm-none' }, 'nenhum grupo')));
        },

        perms() {
          const P = cfg.prompts || {};
          const perms = Array.isArray(P.permissions) ? P.permissions : [];
          if (!perms.length) return TA.ui.empty('Sem permissões registradas', 'O snapshot não traz regras de acesso ao disco.');
          return h('div', { class: 'pm-stack' },
            h('p', { class: 'pm-note' }, 'Avaliadas em ordem: a primeira regra que casa com a operação e o caminho vale; sem nenhuma que case, a operação é permitida.'),
            TA.ui.table({
              rows: perms,
              columns: [
                { key: 'i', label: '#', width: '40px', render: (r, i) => h('span', { class: 'muted num' }, i + 1) },
                { key: 'mode', label: 'Modo', width: '90px', render: (r) => TA.ui.badge(r.mode || '—', r.mode === 'deny' ? 'err' : r.mode === 'allow' ? 'ok' : '') },
                { key: 'operations', label: 'Operações', render: (r) => h('div', { class: 'pm-chips' }, (r.operations || []).map((o) => TA.ui.chip(o))) },
                { key: 'paths', label: 'Caminhos', render: (r) => h('div', { class: 'pm-chips' }, (r.paths || []).map((p) => TA.ui.chip(p, true))) },
              ],
            }).el);
        },

        json() {
          const { runs, ...rest } = cfg;   // `runs` vem da API, não do arquivo
          const text = TA.util.pretty(rest);
          return h('div', { class: 'pm-stack' },
            h('div', { class: 'pm-body-tools' },
              TA.ui.copyBtn(() => text, 'Copiar JSON'),
              h('button', { class: 'btn sm ghost', onClick: () => downloadText(`config_${hash}.json`, text) }, TA.ui.icon('download', 'sm'), 'Baixar'),
              h('span', { class: 'muted small' }, TA.fmt.bytes(text.length) + ' · arquivo configs/' + hash + '.json')),
            h('div', { class: 'pm-json' }, TA.ui.jsonTree(rest, { expand: 1 })));
        },

        diff() { return renderDiff(); },
      };

      function downloadText(name, text) {
        const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
        const a = h('a', { href: url, download: name });
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }

      /* ---------------------------------------------------------------- comparação */
      function renderDiff() {
        const box = h('div', { class: 'pm-stack' });
        const results = h('div', { class: 'pm-diffres' });
        const others = all.filter((c) => c.hash !== hash);
        if (!others.length) {
          box.appendChild(TA.ui.empty('Só existe uma versão', 'Não há outra configuração para comparar. Uma nova versão nasce quando prompts, regras, skills, subagents ou limites mudam.'));
          return box;
        }
        const opts = [{ value: '', label: 'Escolha a versão para comparar…' }].concat(
          others.slice().sort((a, b) => ((b.created_at || '') > (a.created_at || '') ? 1 : -1)).map((c) => ({
            value: c.hash, label: `${TA.fmt.short(c.hash, 8)} · ${c.model || '?'} · ${c.created_at ? TA.fmt.datetime(c.created_at) : 'sem data'}`,
          })));
        const sel = TA.ui.select({ options: opts, value: state.diff, onChange: (v) => { state.diff = v; ctx.setQuery({ diff: v, tab: 'diff' }); run(); }, title: 'Versão B' });
        const swap = h('button', { class: 'btn sm', title: 'Inverter A e B', onClick: () => { if (state.diff) ctx.nav('prompts/' + state.diff, { diff: hash }); } }, '⇄ Inverter');
        box.appendChild(h('div', { class: 'pm-diffbar' },
          h('span', { class: 'pm-ab a' }, 'A'), h('span', { class: 'pm-hash' }, TA.fmt.short(hash, 8)), h('span', { class: 'muted' }, '(esta versão)'),
          h('span', { class: 'pm-arrow' }, '→'), h('span', { class: 'pm-ab b' }, 'B'), sel.el, swap));
        box.appendChild(results);
        let myTok = 0;

        function run() {
          const t = ++myTok;
          TA.util.clear(results);
          if (!state.diff) { results.appendChild(TA.ui.empty('Escolha a versão B', 'Linhas em vermelho existem só em A; em verde, só em B.')); return; }
          results.appendChild(TA.ui.loading('Comparando…'));
          TA.api.configDiff(hash, state.diff).then((d) => {
            if (gone || t !== myTok) return;
            TA.util.clear(results);
            results.appendChild(diffView(d));
          }, (e) => { if (!gone && t === myTok) { TA.util.clear(results); results.appendChild(TA.ui.error(e)); } });
        }
        run();
        return box;
      }

      function diffView(d) {
        const secs = (d && d.sections) || [];
        const changed = secs.filter((s) => s.status && s.status !== 'same');
        let adds = 0, dels = 0;
        secs.forEach((s) => (s.lines || []).forEach((l) => { if (l.op === '+') adds++; else if (l.op === '-') dels++; }));
        let showSame = false;
        const list = h('div', { class: 'pm-diffsecs' });
        const summary = h('div', { class: 'pm-diffsum' },
          h('b', null, changed.length === 0 ? 'Nenhuma diferença' : `${changed.length} ${changed.length === 1 ? 'seção alterada' : 'seções alteradas'}`),
          h('span', { class: 'muted' }, ` de ${secs.length}`),
          h('span', { class: 'pm-add num' }, '+' + TA.fmt.num(adds)), h('span', { class: 'pm-del num' }, '−' + TA.fmt.num(dels)),
          h('span', { class: 'spacer' }),
          secs.length !== changed.length ? TA.ui.check({ label: `Mostrar ${secs.length - changed.length} iguais`, checked: false, onChange: (v) => { showSame = v; paint(); } }) : null);
        function paint() {
          TA.util.clear(list);
          const vis = secs.filter((s) => showSame || (s.status && s.status !== 'same'));
          if (!vis.length) list.appendChild(TA.ui.empty('Versões idênticas', 'Todas as seções são iguais.'));
          vis.forEach((s) => list.appendChild(diffSection(s)));
        }
        paint();
        return h('div', { class: 'pm-stack' }, summary, list);
      }

      const STATUS = { same: ['igual', ''], changed: ['alterada', 'warn'], added: ['adicionada em B', 'ok'], removed: ['removida em B', 'err'] };

      function diffSection(s) {
        const lines = s.lines || [];
        let a = 0, r = 0;
        lines.forEach((l) => { if (l.op === '+') a++; else if (l.op === '-') r++; });
        const st = STATUS[s.status] || [s.status || '—', ''];
        const bodyEl = h('div', { class: 'pm-diffbody' });
        const open = s.status !== 'same';
        const root = h('div', { class: ['pm-diffsec', open && 'open'] });
        const head = h('button', { type: 'button', class: 'pm-diffhead', 'aria-expanded': String(open) },
          TA.ui.icon('chevR', 'pm-chev'), h('span', { class: 'pm-acc-title' }, s.name || '(sem nome)'), TA.ui.badge(st[0], st[1]),
          h('span', { class: 'spacer' }), a ? h('span', { class: 'pm-add num' }, '+' + a) : null, r ? h('span', { class: 'pm-del num' }, '−' + r) : null);
        let built = false;
        const set = (o) => {
          if (o && !built) { built = true; bodyEl.appendChild(diffLines(lines)); }
          bodyEl.classList.toggle('hidden', !o); root.classList.toggle('open', o); head.setAttribute('aria-expanded', String(o));
        };
        head.addEventListener('click', () => set(bodyEl.classList.contains('hidden')));
        root.append(head, bodyEl);
        bodyEl.classList.add('hidden');
        set(open);
        return root;
      }

      /** linhas de um diff, dobrando trechos longos sem mudança (mantém 3 linhas de contexto ao redor) */
      function diffLines(lines) {
        const CTX = 3;
        const n = lines.length;
        const keep = new Array(n).fill(false);
        const anyChange = lines.some((l) => l.op === '+' || l.op === '-');
        if (!anyChange) { for (let i = 0; i < Math.min(n, 12); i++) keep[i] = true; }
        else lines.forEach((l, i) => { if (l.op === '+' || l.op === '-') for (let k = Math.max(0, i - CTX); k <= Math.min(n - 1, i + CTX); k++) keep[k] = true; });
        const wrap = h('div', { class: 'pm-diff' });
        const rowOf = (l) => {
          const op = l.op === '+' || l.op === '-' ? l.op : ' ';
          return h('div', { class: ['pm-line', op === '+' && 'add', op === '-' && 'del'] }, h('span', { class: 'pm-op' }, op === ' ' ? '' : op === '-' ? '−' : '+'), h('span', { class: 'pm-txt' }, l.text === '' ? ' ' : l.text));
        };
        let i = 0;
        while (i < n) {
          if (keep[i]) { wrap.appendChild(rowOf(lines[i])); i++; continue; }
          let j = i;
          while (j < n && !keep[j]) j++;
          const hidden = lines.slice(i, j);
          const fold = h('button', { type: 'button', class: 'pm-fold' }, `⋯ ${hidden.length} ${hidden.length === 1 ? 'linha igual' : 'linhas iguais'} (clique para mostrar)`);
          fold.addEventListener('click', () => { const frag = document.createDocumentFragment(); hidden.forEach((l) => frag.appendChild(rowOf(l))); fold.replaceWith(frag); });
          wrap.appendChild(fold);
          i = j;
        }
        if (!n) wrap.appendChild(h('div', { class: 'pm-none' }, 'sem linhas'));
        return wrap;
      }

      /* ---------------------------------------------------------------- orquestração */
      function paintTab() {
        const my = ++token;
        TA.util.clear(body);
        try {
          const node = R[state.tab]();
          if (my === token) body.appendChild(node);
        } catch (e) { body.appendChild(TA.ui.error(e)); }
      }

      function buildTabs() {
        TA.util.clear(tabsBox);
        const P = cfg.prompts || {};
        const counts = { rules: (P.rules || []).length, skills: (P.skills || []).length, subagents: entries(cfg.subagents).length, perms: Array.isArray(P.permissions) ? P.permissions.length : null };
        tabs = TA.ui.tabs({
          items: TABS.map(([id, label]) => ({ id, label, count: counts[id] })), active: state.tab,
          onChange: (id) => { state.tab = id; ctx.setQuery({ tab: id, diff: id === 'diff' ? state.diff : null }); paintTab(); },
        });
        tabsBox.appendChild(tabs.el);
      }

      async function load() {
        try {
          const [c, list] = await Promise.all([TA.api.config(hash), TA.api.configs().catch(() => null)]);
          if (gone) return;
          cfg = c || {};
          all = (list && list.items) || [];
          meta = all.find((x) => x.hash === hash) || null;
          renderHead(); buildTabs(); paintTab();
        } catch (e) {
          if (gone) return;
          TA.util.clear(head); TA.util.clear(tabsBox); TA.util.clear(body);
          head.appendChild(TA.ui.error(e));
        }
      }
      ctx.onRefresh(() => { TA.util.clear(head); head.appendChild(TA.ui.loading()); load(); });
      load();
    },
  };
})();
