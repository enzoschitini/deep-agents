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
| `agent.py` | `build_agent(config)` → `(agent, gateway)`. Monta `create_deep_agent` com o modelo do gateway, a tool `internet_search` (web_search nativo da OpenAI), instruções `/system_prompt/instructions/*.md` (via `memory=`) e permissões. |
| `model/` | Camada de modelos. `ModelConfig` (spec `"provider:modelo"`, temperature, thinking, timeout…), `LLMGateway` (cria o modelo e coleta métricas em `gateway.history`), `ProviderRules` (renomeia/descarta/fixa parâmetros por provedor, ex.: `reasoning_effort` na OpenAI, `thinking` budget na Anthropic), `metrics*.py` (tokens, latência, custo, tool runs). |
| `system_prompt/` | `instructions/` (`prompts.py` com `SYSTEM_PROMPT` e os textos do perfil do harness + vários `.md` temáticos carregados em ordem alfabética; a pasta `system_prompt/` é montada **somente leitura** em `/system_prompt/`), `harness_profile.py` (`HarnessProfiler`, perfil do harness registrado por modelo). |
| `cli/` | `ChatCLI` (`app.py`, ciclo e comandos), `Renderer` (`renderer.py`, tudo o que se desenha), `commands.py` (registry de comandos `/…`), `models.py` (lista/escolha de modelos), `prompt.py`, `banner.py`, `theme.py` (cores). |
| `utils/json_manager.py` | `manage_result_json`: salva o resultado completo do agente em `data/agent_result.json`. |
| `docs/` | Material de estudo (prompts isolados `docs/system_prompt/01..06`, mapa da doc). Não faz parte do runtime. |

## Fluxo

`cli/__main__.py` define `MODEL_SPEC`/`MODEL` → `build_agent` → `ChatCLI(agent, gateway, agent_factory=build_agent).run()`. Trocar modelo/temperatura/thinking no chat chama `agent_factory` de novo (a conversa continua; em caso de erro mantém a configuração anterior).

## Convenções

- **Idiomas misturados de propósito**: textos da interface da CLI (mensagens, comandos `/aiuto`, `/modello`…) em **italiano**; comentários e docstrings em **português**; nomes de código em inglês. Manter isso ao editar.
- Imports no topo dos entry points usam `# noqa: E402` porque o `sys.path` é ajustado antes (permite rodar com o botão Play). Não "arrumar".
- Todo desenho no terminal passa pelo `Renderer`; `ChatCLI` não imprime direto. Erros: `view.error(e, contexto)` — sempre passar o contexto (onde falhou).
- Parâmetros específicos de provedor pertencem a `ProviderRules`, não ao `LLMGateway` nem à CLI. Para suportar um provedor/modelo novo, estender `DEFAULT_RULES`.
- O agente não pode escrever em `/system_prompt/**` (permissão `deny`); mudanças em `system_prompt/instructions/*.md` são feitas por você no disco.
- `HarnessProfiler.register(spec)` precisa rodar para cada modelo (inclusive após `/modello`); chaves com nome errado em `tool_description_overrides` viram no-op silencioso.
- Testes ficam em `tests/` na raiz do repo (`LLMGateway` aceita `model=` para injetar um modelo fake).
