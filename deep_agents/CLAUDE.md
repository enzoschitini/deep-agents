# deep_agents

Pacote principal do projeto: um agente de pesquisa construído sobre LangChain **Deep Agents** (`deepagents`), com uma CLI de chat no terminal (rich + prompt-toolkit). Python >= 3.14, dependências gerenciadas com `uv` (`pyproject.toml` na raiz do repo).

## Comandos

```bash
python -m deep_agents.cli          # abre o chat (a partir da raiz do repo); também roda direto via `python deep_agents/cli/__main__.py`
DEEP_AGENTS_DEBUG=1 python -m deep_agents.cli   # erros da CLI com traceback completo
```

As chaves de API ficam no `.env` da raiz (carregado com `load_dotenv()` em `agent.py` e `harness_profile.py`). Nunca commitar nem ler o `.env` sem necessidade.

## Estrutura

| Pasta/arquivo | Papel |
|---|---|
| `config.py` | Ajustes do agente: `MODEL_CALL_LIMIT` (teto de chamadas ao modelo por resposta, hoje 10; usado em `agent.py` via `ModelCallLimitMiddleware`). |
| `agent.py` | `AgentBuilder(config).build()` → `(agent, gateway)` (métodos `build_model`/`build_prompt`/`build_tools`). Monta `create_deep_agent` com o modelo do gateway, as tools vindas do `ToolkitBuilder` (hoje `internet_search` via Tavily), tudo de prompt vem da fachada `AgentPrompts` (system prompt, regras via `memory=`, skills via `skills=`, backend, permissões). |
| `model/` | Camada de modelos. `ModelConfig` (spec `"provider:modelo"`, temperature, thinking, timeout…), `LLMGateway` (cria o modelo e coleta métricas em `gateway.history`), `ProviderRules` (renomeia/descarta/fixa parâmetros por provedor, ex.: `reasoning_effort` na OpenAI, `thinking` budget na Anthropic), `metrics*.py` (tokens, latência, custo, tool runs). |
| `prompts/` | `agent_prompts.py` (`AgentPrompts`, fachada usada pelo `agent.py`), `system.py` (`SYSTEM_PROMPT` e os textos do perfil do harness), `rules/` (vários `.md` temáticos carregados em ordem alfabética), `skills/<nome>/SKILL.md` (uma pasta por skill, passada em `skills=`; o agente só lê o `SKILL.md` completo sob demanda; hoje: `busca-na-web`), `harness_profile.py` (`HarnessProfiler`, perfil do harness registrado por modelo). A pasta é montada **somente leitura** em `/prompts/`. `workspace.py` (`WorkspaceAccess`): **acesso ao disco real**, só à pasta do pacote `deep_agents/`, montada em `/workspace/` (`FilesystemBackend(virtual_mode=True)`) + `FilesystemPermission` em ordem (primeira que casa vale; sem match = permitido, daí o `deny /**` final): nega segredos (`.*`, `*.key`, `*.pem`) em qualquer lugar, `*.py` e `memory/` só leitura, `/prompts/` só leitura, resto negado. O glob **não casa dotfiles com `**`**, por isso têm regra própria. Sem shell (`execute`), que as permissões não cobrem. O agente é instruído em `rules/07_arquivos.md`. Testes: `tests/test_workspace_permissions.py` (rodar com `uv run --with pytest python -m pytest tests`). |
| `memory/` | Histórico de mensagens de conversas anteriores (uma linha por mensagem: `session_id`, `role` = `human`/`ai`, `content`). `config.py` (ajustes: `SUMMARY_EVERY_INTERACTIONS`, `KEEP_MESSAGES`). `MemoryBuilder` (`build_memory.py`, fachada) tem `summarization()` (`SummarizationMiddleware`: resume o contexto passando de N interações) e controla a **sessão atual** (`session_id` único por data/hora, `new_session()`, `resume()`, `sessions()`, `history()`, `record_turn()`). A CLI grava as mensagens a cada turno. **O agente não tem tool nem regra de acesso ao histórico salvo** (só o resumo de contexto): sessão nova começa do zero e o passado só entra ao retomar uma sessão com `/sessioni`. `storage/`: `StorageMemory` envolve um backend recebido pronto (o `MemoryBuilder` o escolhe pelo nome: `local_csv` → `local_database.csv`; `fake_vectorial` → RAM, similaridade fake); todos implementam `MemoryRepository` (definido em `storage_memory.py`, junto com `MemoryRecord` e `SessionInfo`). Os bancos são simulados; a integração com o agente é real. |
| `toolkit/` | Tools do agente. `tools/<tema>.py`: um grupo por tema (subclasse de `ToolGroup` em `tools/base.py`; hoje `tavily.py` → `internet_search`). `ToolkitBuilder` (`build_toolkit.py`) recebe `{grupo: {"enabled", "tools"}}` (definido em `cli/__main__.py`: `TOOLKIT`) e devolve só as tools habilitadas; nome desconhecido é erro. **Dois canais**: o retorno da tool vai ao modelo; o **canal lateral** (`SideChannel`, `side_channel.py`) recebe `publish(toolkit, tool, kind, payload)` (ex.: `kind="sources"` com `{domain,title,url}`) e é lido pelo código com `query(session_id=, toolkit=, tool=, kind=, turn=)` ou `subscribe(cb)`. O canal e o builder são criados uma vez na CLI (sobrevivem ao `/modello`); `ChatCLI(toolkit=...)` chama `begin_turn()` a cada mensagem e, ao fim do turno, desenha (via `Renderer`) uma linha `⚙ strumento in uso` por tool da toolkit usada (`tools_used`; resumos personalizados em `TOOL_SUMMARIES`) e o painel `Fonti` lido do canal (`kind="sources"`). Ainda não há consumidor de banco. Grupo novo: criar o arquivo e registrar em `DEFAULT_GROUPS`. |
| `cli/` | `ChatCLI` (`app.py`, ciclo e comandos), `Renderer` (`renderer.py`, tudo o que se desenha), `commands.py` (registry de comandos `/…`), `models.py` (lista/escolha de modelos), `prompt.py`, `banner.py`, `theme.py` (cores). |
| `utils/json_manager.py` | `manage_result_json`: salva o resultado completo do agente em `data/agent_result.json`. |
| `docs/` | Material de estudo (prompts isolados `docs/system_prompt/01..06`, mapa da doc). Não faz parte do runtime. |

## Fluxo

`cli/__main__.py` define `MODEL_SPEC`/`MODEL`, cria um `MemoryBuilder` e a fábrica `create_agent` (`AgentBuilder(config, memory=memory).build()`) → `ChatCLI(agent, gateway, agent_factory=create_agent, memory=memory).run()`. Trocar modelo/temperatura/thinking no chat chama `agent_factory` de novo (a conversa continua; em caso de erro mantém a configuração anterior).

**Sessões**: cada execução da CLI começa uma sessão nova e vazia; o banner mostra o ID e o nº de mensagens. `/pulisci` abre outra sessão nova (a anterior continua salva) e `/sessioni` lista as salvas num seletor; escolher uma carrega o histórico como contexto e a conversa continua nela (`/sessioni <id>` retoma direto). Sem `memory=`, essas funções ficam desligadas.

## Convenções

- **Idiomas misturados de propósito**: textos da interface da CLI (mensagens, comandos `/aiuto`, `/modello`…) em **italiano**; comentários e docstrings em **português**; nomes de código em inglês. Manter isso ao editar.
- Imports no topo dos entry points usam `# noqa: E402` porque o `sys.path` é ajustado antes (permite rodar com o botão Play). Não "arrumar".
- Todo desenho no terminal passa pelo `Renderer`; `ChatCLI` não imprime direto. Erros: `view.error(e, contexto)` — sempre passar o contexto (onde falhou).
- Parâmetros específicos de provedor pertencem a `ProviderRules`, não ao `LLMGateway` nem à CLI. Para suportar um provedor/modelo novo, estender `DEFAULT_RULES`.
- O agente só acessa `/workspace/` (pasta `deep_agents/`) e não escreve em `/prompts/**`, `*.py` nem `memory/` (permissões `deny`); mudanças em `prompts/rules/*.md` são feitas por você no disco.
- `HarnessProfiler.register(spec)` precisa rodar para cada modelo (inclusive após `/modello`); chaves com nome errado em `tool_description_overrides` viram no-op silencioso.
- Testes ficam em `tests/` na raiz do repo (`LLMGateway` aceita `model=` para injetar um modelo fake).
