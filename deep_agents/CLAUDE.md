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
| `agent.py` | `AgentBuilder(config).build()` → `(agent, gateway)` (métodos `build_model`/`build_prompt`/`build_tools`). Monta `create_deep_agent` com o modelo do gateway, a tool `internet_search` (web_search nativo da OpenAI), tudo de prompt vem da fachada `AgentPrompts` (system prompt, regras via `memory=`, skills via `skills=`, backend, permissões). |
| `model/` | Camada de modelos. `ModelConfig` (spec `"provider:modelo"`, temperature, thinking, timeout…), `LLMGateway` (cria o modelo e coleta métricas em `gateway.history`), `ProviderRules` (renomeia/descarta/fixa parâmetros por provedor, ex.: `reasoning_effort` na OpenAI, `thinking` budget na Anthropic), `metrics*.py` (tokens, latência, custo, tool runs). |
| `prompts/` | `agent_prompts.py` (`AgentPrompts`, fachada usada pelo `agent.py`), `system.py` (`SYSTEM_PROMPT` e os textos do perfil do harness), `rules/` (vários `.md` temáticos carregados em ordem alfabética), `skills/<nome>/SKILL.md` (uma pasta por skill, passada em `skills=`; o agente só lê o `SKILL.md` completo sob demanda; hoje: `busca-na-web`), `harness_profile.py` (`HarnessProfiler`, perfil do harness registrado por modelo). A pasta é montada **somente leitura** em `/prompts/`. |
| `cli/` | `ChatCLI` (`app.py`, ciclo e comandos), `Renderer` (`renderer.py`, tudo o que se desenha), `commands.py` (registry de comandos `/…`), `models.py` (lista/escolha de modelos), `prompt.py`, `banner.py`, `theme.py` (cores). |
| `utils/json_manager.py` | `manage_result_json`: salva o resultado completo do agente em `data/agent_result.json`. |
| `docs/` | Material de estudo (prompts isolados `docs/system_prompt/01..06`, mapa da doc). Não faz parte do runtime. |

## Fluxo

`cli/__main__.py` define `MODEL_SPEC`/`MODEL` → `create_agent` (`AgentBuilder(config).build()`) → `ChatCLI(agent, gateway, agent_factory=create_agent).run()`. Trocar modelo/temperatura/thinking no chat chama `agent_factory` de novo (a conversa continua; em caso de erro mantém a configuração anterior).

## Convenções

- **Idiomas misturados de propósito**: textos da interface da CLI (mensagens, comandos `/aiuto`, `/modello`…) em **italiano**; comentários e docstrings em **português**; nomes de código em inglês. Manter isso ao editar.
- Imports no topo dos entry points usam `# noqa: E402` porque o `sys.path` é ajustado antes (permite rodar com o botão Play). Não "arrumar".
- Todo desenho no terminal passa pelo `Renderer`; `ChatCLI` não imprime direto. Erros: `view.error(e, contexto)` — sempre passar o contexto (onde falhou).
- Parâmetros específicos de provedor pertencem a `ProviderRules`, não ao `LLMGateway` nem à CLI. Para suportar um provedor/modelo novo, estender `DEFAULT_RULES`.
- O agente não pode escrever em `/prompts/**` (permissão `deny`); mudanças em `prompts/rules/*.md` são feitas por você no disco.
- `HarnessProfiler.register(spec)` precisa rodar para cada modelo (inclusive após `/modello`); chaves com nome errado em `tool_description_overrides` viram no-op silencioso.
- Testes ficam em `tests/` na raiz do repo (`LLMGateway` aceita `model=` para injetar um modelo fake).
