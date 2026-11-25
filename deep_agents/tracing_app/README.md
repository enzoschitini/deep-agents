# tracing_app: a interface do rastreamento (o "LangSmith" local)

Lê os JSONs gravados pelo `tracing/` (`deep_agents/data/tracing/`) e os mostra num **único HTML estático** servido
por um servidor Python (só biblioteca padrão). Só leitura: nada aqui escreve nos dados.

```
python -m deep_agents.tracing_app [--port 8100] [--data-dir PASTA] [--no-browser] [--host 127.0.0.1]
python -m deep_agents.tracing_app --build saida.html      # só grava o HTML único (sem dados)
python -m deep_agents.tracing_app --check                 # valida a sintaxe de todo o JS/CSS (usa quickjs_rs)
```

## Arquivos

```
tracing_app/
  __main__.py     CLI (argparse)
  build.py        monta o HTML único: src/index.template.html + css/*.css + js/*.js (ordem alfabética)
  server.py       ThreadingHTTPServer: GET / (HTML montado a cada request), GET /api/*, só 127.0.0.1
  repository.py   TraceRepository: lê/cacheia (por mtime) os JSONs e calcula listas, filtros, agregados
  src/
    index.template.html
    css/00_tokens.css 10_base.css 20_components.css 30_*.css ...   (um arquivo por view, prefixo = ordem)
    js/00_core.js 05_util.js 10_api.js 20_ui.js 30_router.js 40_shell.js   (base compartilhada)
    js/50_charts.js 55_dashboard.js 60_runs.js 65_sessions.js 70_trace_view.js 72_span_detail.js
        74_messages.js 80_prompts.js 85_data.js 99_boot.js                 (uma view/módulo por arquivo)
```

## Convenções do front-end (sem frameworks, sem CDN, sem build tools)

- Tudo vive no namespace global `TA` (`TA.util`, `TA.fmt`, `TA.api`, `TA.ui`, `TA.charts`, `TA.views`, `TA.bus`, `TA.state`).
  Cada arquivo é um script solto; os arquivos são concatenados em ordem alfabética. JS moderno (ES2020) é permitido.
- DOM por `TA.h(tag, attrs, ...children)` (nunca `innerHTML` com dados dos JSONs; textos vão como nós de texto).
- **View** = `TA.views.<nome> = { mount(ctx) { ...; return cleanupOpcional } }`. Nomes de view (rota → view):
  `#/` dashboard · `#/runs` runs · `#/runs/:id` trace · `#/sessions` sessions · `#/sessions/:id` session ·
  `#/prompts` prompts · `#/prompts/:hash` prompt · `#/data` data · `#/data/:kind` data (kind = `llm`, `tools`, `files`).
- `ctx`: `{ el, params, query, nav(path, query?), setQuery(obj), crumbs([{label, href?}]), actions([nodes]),
  onCleanup(fn), onRefresh(fn), range() }`. `el` é o contêiner (limpo) da view. `onRefresh(fn)` chama `fn` quando o
  usuário clica em atualizar ou muda o intervalo de tempo (`ctx.range()` → `{key, since}`); recarregue seus dados nele.
  `setQuery` troca a query da URL sem remontar a view (use para filtros/ordem/página/aba/seleção, para o link ser
  compartilhável). Limpezas (listeners globais, timers) vão em `ctx.onCleanup`.
- Estilo: variáveis CSS de `00_tokens.css` (tema claro/escuro por `[data-theme]`), classes de `20_components.css`.
  Cada view cria o seu CSS em `src/css/<NN>_<nome>.css` com todas as classes prefixadas (`.rv-` runs, `.tv-` trace...).
  Nunca use cores literais fora dos tokens (o tema escuro precisa funcionar).
- Português do Brasil nos textos da interface.

## API (JSON, todas GET; erros: `{ "error": "mensagem" }` com status 4xx/5xx)

Filtros comuns: `since`/`until` (ISO-8601, ou relativo: `30m` `1h` `24h` `7d` `30d` `2w`), `status`, `model`, `session`, `origin` (aceitam vários valores separados por vírgula). Erros: 400 (parâmetro/id inválido; ids e nomes de arquivo só `[A-Za-z0-9._-]+`) e 404, sempre `{"error": ...}`. Campos numéricos ausentes vêm `null`. `python -m deep_agents.tracing_app.dev_seed --out PASTA` gera dados sintéticos para desenvolvimento.

| Endpoint | Retorno |
|---|---|
| `/api/meta` | `{data_dir, n_runs, n_sessions, n_configs, first_run_at, last_run_at, models[], origins[], statuses[], generated_at}` |
| `/api/runs` | `{total, limit, offset, items[], facets{status{},model{},origin{},session{}}}`. Params: filtros comuns, `q` (busca em mensagem, resposta e run_id), `has_errors=1`, `tool` (nome), `min_duration`, `sort` (`started_at` `duration_s` `total_tokens` `input_tokens` `output_tokens` `cost_usd` `llm_calls` `tool_calls` `ttft_s`), `order` (`asc`/`desc`, padrão `desc`; valores nulos sempre por último), `limit` (50, máx. 500), `offset`. `facets` contam o conjunto filtrado por tudo MENOS a própria faceta. Item: `run_id, session_id, turn, origin, status, started_at, duration_s, user_message, answer_preview, model, config_hash, input_tokens, output_tokens, total_tokens, cache_read_tokens, cost_usd, llm_calls, tool_calls, subagent_calls, errors, ttft_s, tools[] (nomes únicos), skills_used[], path` (mais `ended_at`, `label`, `reasoning_tokens`) |
| `/api/runs/<id>` | o `run.json` completo |
| `/api/runs/<id>/trace` | `{run, root_ids[], spans[]}`: cada span do `spans.json` + `brief` (llm: `{model, purpose, input_tokens, output_tokens, cost_usd, latency_s, ttft_s, finish_reason, n_messages, tool_names[], requested_tools[]}`; tool: `{name, kind, status, duration_s, input_preview, output_preview, tool_call_id, subagent_type?}`; chain: `{}`) e `offset_s`/`duration_s` já numéricos |
| `/api/runs/<id>/spans/<span_id>` | `{span, parent_chain[] (do próprio span até a raiz), llm_call?(completo, com `tools_hash` resolvido em `tool_schemas[]`), tool_call?(completo), delegation?(só para `task`)}` |
| `/api/runs/<id>/files/<nome>` | o JSON bruto do arquivo (`run.json`, `llm_calls.json`, `events.json`, ...) |
| `/api/sessions` | `{items[]}`: `{session_id, started_at, last_run_at, n_runs, models[], totals{llm_calls,tool_calls,input_tokens,output_tokens,cost_usd}, first_message, n_errors, duration_s, statuses{}}` |
| `/api/sessions/<id>` | `{session, runs[] (itens de /api/runs, ordem do turno), messages[]: {role, content, run_id, at}}` |
| `/api/stats` | filtros comuns + `bucket` (`auto` `hour` `day`) → `{range{from,to,bucket}, kpis{}, prev_kpis{}|null (só com `since`), series[] (buckets vazios com zeros), status_counts{}, by_model[], by_tool[], by_agent[], latency_hist{edges,counts}, tokens_hist{edges,counts}, slowest_runs[] (8), recent_errors[] (10)}`; bucket em UTC. Campos exatos no docstring de `TraceRepository.stats()` (kpis: `runs errors error_rate cancelled input_tokens output_tokens total_tokens cache_read_tokens cache_hit_rate reasoning_tokens cost_usd latency_{avg,p50,p95,p99}_s avg_ttft_s llm_calls tool_calls subagent_calls avg_tokens_per_run`; series: `t runs errors ok cancelled input_tokens output_tokens total_tokens cost_usd p50_s p95_s avg_ttft_s llm_calls tool_calls`; by_tool: `name calls errors avg_s p95_s max_s total_s`) |
| `/api/configs` | `{items[]}`: `{hash, model, provider, created_at, system_prompt_chars, n_rules, n_skills, n_subagents, runs, first_used_at, last_used_at}` |
| `/api/configs/<hash>` | o arquivo `configs/<hash>.json` + `hash`, `created_at` (mtime do arquivo), `first_used_at`, `last_used_at`, `runs[]` (itens de /api/runs dos runs que o usaram) |
| `/api/configs/diff?a=<hash>&b=<hash>` | `{a, b, sections[]: {name, status (same/changed/added/removed), lines[]: {op (' '/'+'/'-'), text}}}` (seções: `model`, `system_prompt`, `summary_prompt`, `harness_profile`, `memory_files`, `regra: <path>`, `skill: <path>`, `subagent: <nome>`, `toolkit`, `dynamic_subagents`, `limits`, `streaming`, `skills_dirs`, `permissions`; `lines` traz o texto inteiro, inclusive linhas iguais) |
| `/api/llm_calls` | todas as chamadas ao LLM de todos os runs: filtros comuns (`since`/`until` valem por chamada; `session`/`origin` pelo run; `status` e `model` são os da chamada) + `run`, `agent`, `purpose` (`agent`/`summary`), `min_latency`, `q` (requisição e resposta completas), `sort` (`started_at agent purpose model status input_tokens output_tokens cache_read_tokens cost_usd latency_s ttft_s run_id`), `order`, `limit` (50, máx. 500), `offset` → `{total, limit, offset, items[]}`: `{llm_call_id, span_id, run_id, started_at, agent, purpose, model, status, input_tokens, output_tokens, cache_read_tokens, cost_usd, latency_s, ttft_s, finish_reason, requested_tools[], preview_in, preview_out}` |
| `/api/tool_calls` | idem para tools: `{tool_call_id, span_id, run_id, started_at, name, kind, agent, status, duration_s, input_preview, output_preview, output_chars}`; filtros extras `name`, `kind`, `agent`, `status`, `min_duration`, `q` (argumentos e saída completos), `sort` (`started_at name kind agent status duration_s output_chars run_id`) |

IDs e links: `span_id` = id do run do LangChain; o link para um span é `#/runs/<run_id>?span=<span_id>`.
