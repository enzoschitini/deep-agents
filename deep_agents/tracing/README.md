# tracing: rastreamento de execuções (o "LangSmith" local)

Cada resposta do agente (um *run*) vira uma pasta de JSONs em `deep_agents/data/tracing/` (ignorada pelo git).
Só dados por enquanto: uma futura interface lê estes arquivos. Todo o módulo é encapsulado na classe `Tracer`
(`tracing/tracer.py`); o resto do projeto só a chama.

## Passo 1: o que coletar e de onde

| Dado | Fonte | Arquivo |
|---|---|---|
| Identidade do run: run_id, sessão, turno, origem (cli/web), rótulo, status, horários, duração | `AgentStreamer` + `Tracer.begin_run/end_run` | `run.json` |
| Entrada do usuário e histórico enviado ao agente (mensagens completas) | `begin_run(messages=)` (serializado ANTES do LangGraph converter a lista) | `conversation.json` |
| Resposta final e estado final do agente (mensagens com tools, todos, arquivos virtuais) | `RunResult.state` | `conversation.json` |
| Configuração do agente: modelo e parâmetros, kwargs resolvidos por `ProviderRules`, system prompt completo (com a data), perfil do harness, regras `.md`, skills, toolkit, subagents (prompt, tools), limites, resumo de contexto, permissões, opções de streaming | `snapshot.py` (lê os mesmos arquivos/constantes que montam o agente); deduplicado por hash | `configs/<hash>.json` (o run só guarda o hash) |
| Ambiente: Python, SO, versões das libs, commit git (e se há alterações) | `snapshot.py` | `run.json` |
| Cada chamada ao LLM: mensagens enviadas (system prompt, histórico, resultados de tools), schemas das tools, parâmetros da invocação, resposta completa (texto, tool_calls, reasoning, `response_metadata`), tokens (entrada, saída, cache, reasoning), custo, latência, tempo até o 1º token, tokens/s, motivo de parada, erro e retries, propósito (agente ou resumo de contexto) | callbacks do LangChain (`on_chat_model_start/end/error`, `on_llm_new_token`, `on_retry`) + `CallMetrics` do `MetricsCallbackHandler` | `llm_calls.json` |
| Cada chamada de tool: nome, tipo (tool, task, eval, skill, arquivo, todos, async), argumentos completos, saída completa, erro, duração, qual chamada ao LLM a pediu, qual agente a rodou | callbacks (`on_tool_start/end/error`) + `classify` | `tool_calls.json` |
| Árvore de execução (tipo LangSmith): chains/nós do LangGraph/middlewares, LLMs e tools, com pai/filho, início/fim, offset no run, status | callbacks (`on_chain_*`, `run_id`/`parent_run_id`) | `spans.json` |
| Subagents: delegações `task` (tarefa, resultado, tools e LLMs que fizeram, tokens/custo), subagents dinâmicos (QuickJS) e tarefas assíncronas | spans + eventos `custom` do stream | `subagents.json` |
| Todos os eventos do streaming, em ordem (`seq`), com `label`, `visibility`, `parent_id` | `StreamEvent` via sink do bus | `events.json` |
| Resposta em streaming: segmentos de texto (intermediário x final), reasoning, tempos (1º delta, duração do stream), nº de deltas | eventos `response`/`reasoning` | `response.json` |
| Fontes: URLs consultadas e todas as publicações do canal lateral | `SideChannel.query(turn=)` | `sources.json` |
| Erros, retries e avisos (limite de chamadas ao modelo, falhas de callback, notices) | callbacks + eventos | `errors.json` |
| Totais, por agente, por tool, tempos (LLM, tools, ttft) | calculado no fim a partir do que foi coletado | `run.json` |

Regras: segredos nunca são gravados (chaves como `api_key`, `authorization`, `headers`, `token`, `secret` viram
`[redacted]`); textos acima de `max_str_chars` são cortados com um aviso do tamanho original; o tracing nunca
derruba a resposta (todo erro dele é engolido e logado em `deep_agents.tracing`).

## Passo 2: estrutura dos arquivos

```
data/tracing/
  index.json                  lista leve de runs (uma linha por run) para listagens e filtros
  sessions.json               agregado por sessão (runs, modelos, totais)
  configs/<hash>.json         snapshot da configuração do agente (um por hash de conteúdo)
  runs/<run_id>/
    run.json                  resumo do run (identidade, status, totais, tempos, por agente, por tool, ambiente)
    conversation.json         mensagens de entrada, mensagens finais, todos, arquivos virtuais
    spans.json                árvore de execução (flat, com pai/filhos e referências aos detalhes)
    llm_calls.json            cada chamada ao LLM, completa
    tool_calls.json           cada chamada de tool, completa
    subagents.json            delegações (estáticas, dinâmicas, assíncronas) com rollup
    events.json               todos os StreamEvent
    response.json             a resposta em streaming
    sources.json              fontes e publicações do canal lateral
    errors.json               erros, retries, avisos
```

Convenções comuns: `schema_version`, horários em ISO-8601 UTC com milissegundos (`started_at`, `ended_at`) mais
`start_offset_s` (segundos desde o início do run, para cascatas/waterfall), `duration_s`, `status` em
`running | completed | error | cancelled | unfinished`. Os ids se cruzam: `span_id` = id do run do LangChain;
`llm_call_id` e `tool_call_id` apontam para o span; `tool_call_id` é o mesmo id que o modelo gerou.

### run.json
```
schema_version, run_id, label, session_id, turn, origin, status
started_at, ended_at, duration_s
input   {user_message, history_messages, history_chars}
output  {answer, answer_chars, n_sources}
model   {spec, provider, model_id, temperature, thinking, max_tokens, timeout, max_retries, extra, resolved_kwargs, models_used}
config_hash, config_path
totals  {llm_calls, main_llm_calls, subagent_llm_calls, summary_llm_calls, input_tokens, output_tokens, total_tokens,
         cache_read_tokens, cache_creation_tokens, reasoning_tokens, cost_usd, tool_calls, subagent_calls,
         dynamic_subagents, errors}
timing  {wall_time_s, llm_time_s, tool_time_s, time_to_first_llm_token_s, time_to_first_response_delta_s,
         response_stream_s, n_response_deltas}
by_agent {<agente>: {llm_calls, input_tokens, output_tokens, cost_usd, tool_calls, llm_time_s}}
by_tool  {<tool>: {calls, errors, total_s, avg_s, max_s}}
skills_used[], files_touched[{path, ops[]}], report_summary (RunReport.summary()), stats (RunStats)
error {type, message, traceback} | null
environment {python, platform, packages{}, git{commit, branch, dirty}}
tags[], annotations{}          (reservados para a futura interface)
index_entry {…}                (a mesma linha que vai para o index.json; é o que `rebuild_index()` lê)
files {<arquivo>: {bytes}}
```

### llm_calls.json
`{schema_version, run_id, tool_schemas: {<hash>: [schema, ...]}, calls: [...]}`; cada chamada:
```
llm_call_id, span_id, parent_span_id, seq, status, purpose (agent|summary)
agent, agent_id, ns[], node, step, parent_tool_call_id (a task que a originou), caused_tool_call_ids[]
model {requested, returned, provider, class}
invocation_params{} (sem segredos e sem tools), tools_hash, tool_names[], tags[], metadata{}
started_at, ended_at, start_offset_s, latency_s, ttft_s, n_stream_chunks, streamed
request  {n_messages, chars, messages[ {type, id, name, content, tool_calls, tool_call_id, ...} ]}
response {message{...}, text, tool_calls[], finish_reason, response_id, system_fingerprint, service_tier,
          response_metadata{}, llm_output{}}
usage {input_tokens, output_tokens, total_tokens, cache_read_tokens, cache_creation_tokens, reasoning_tokens,
       audio_in_tokens, audio_out_tokens, usage_source}
cost_usd, tokens_per_second, retries[], error {type, message} | null
```

### tool_calls.json
`{schema_version, run_id, calls: [...]}`; cada chamada:
```
tool_call_id, span_id, parent_span_id, seq, name, kind (tool|subagent|code_eval|todos|skill|file|async_task|summarization),
status, agent, agent_id, ns[], parent_tool_call_id, caused_by_llm_call_id
started_at, ended_at, start_offset_s, duration_s
input {…argumentos completos…}, input_str
output {type, content, text, status, tool_call_id, artifact, update_keys}, output_chars
error {type, message} | null, tags[], metadata{}, data{} (do classificador: skill, op/path, todos…)
```

### spans.json
`{schema_version, run_id, root_ids[], spans: [ {span_id, parent_id, children[], type (chain|llm|tool), name, seq, status,
node, step, agent, agent_id, ns[], depth, started_at, ended_at, start_offset_s, duration_s, tags[], error, ref {llm_call_id|tool_call_id}, io{...}} ]}`

### subagents.json
`{schema_version, run_id, delegations: [ {id, type (static|dynamic|async), subagent_type, description, status,
started_at, ended_at, duration_s, result, error, parent_id, llm_call_ids[], tool_call_ids[], totals{llm_calls,
input_tokens, output_tokens, cost_usd, tool_calls}} ]}`

### events.json · response.json · sources.json · errors.json · conversation.json
- `events.json`: `{schema_version, run_id, count, events: [StreamEvent.to_dict()]}`
- `response.json`: `{answer, segments[{message_id, final, text, n_deltas, first_delta_at, last_delta_at}], intermediate_texts[], reasoning{text, n_deltas}, timing{...}}`
- `sources.json`: `{sources[{domain,title,url}], publications[{id, toolkit, tool, kind, payload, created_at, session_id, turn}]}`
- `errors.json`: `{errors[{where, name, type, message, span_id, at}], retries[], warnings[{type, message}]}`
- `conversation.json`: `{input_messages[], final_messages[], todos[], files{<path>: {chars, content}}, state_keys[]}`

### Globais
- `index.json`: `{schema_version, updated_at, runs: [{run_id, session_id, turn, origin, status, started_at, duration_s,
  user_message, answer_preview, model, config_hash, input_tokens, output_tokens, cost_usd, llm_calls, tool_calls,
  subagent_calls, errors, path}]}`; refeito por `Tracer.rebuild_index()` a partir dos `run.json` se se perder.
- `sessions.json`: `{schema_version, sessions: {<session_id>: {session_id, started_at, last_run_at, n_runs, run_ids[], models[], totals{}}}}`

## Passo 3: como usar (código)

```python
tracer = Tracer(TraceOptions(), config_snapshot=..., session_provider=...)       # bootstrap.py cria um só
streamer = AgentStreamer(agent, gateway, channel=channel, tracer=tracer, origin="cli")   # CLI e servidor web
```
O `AgentStreamer` chama `tracer.begin_run`, liga o callback e o sink de eventos e fecha com `tracer.end_run`.
Leitura (para a futura UI): `tracer.list_runs()`, `tracer.load_run(run_id)`, `tracer.rebuild_index()`.
Desligar: `TraceOptions(enabled=False)` ou a variável de ambiente `DEEP_AGENTS_TRACING=0`.

Limitações conhecidas: os arquivos do run são gravados ao fim (durante o run só existe `run.json` com
`status: running`; um processo morto no meio deixa esse status); o `index.json` é lido/regravado sem trava entre
processos (CLI e servidor ao mesmo tempo podem perder uma linha: use `rebuild_index()`); dentro de subagents
dinâmicos (QuickJS) não há chamadas ao LLM/tools rastreáveis (só início/fim/erro).
