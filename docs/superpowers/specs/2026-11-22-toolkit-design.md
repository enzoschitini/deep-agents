# Toolkit do agente: seleção de tools + canal lateral

Data: 2026-11-22 · Status: aguardando aprovação

## Intenção
Dar ao agente principal uma toolkit modular. Cada arquivo em `toolkit/tools/` é um grupo de tools de um tema.
O `ToolkitBuilder` escolhe quais tools o agente enxerga e gerencia dois canais de dados:
- **Canal direto:** o que a tool devolve ao modelo (texto/JSON para ele processar).
- **Canal lateral:** dados estruturados publicados pela tool (ex.: `{domínio, título, link}` das páginas
  buscadas), com rastreabilidade (toolkit, tool, sessão, turno). Lido depois **pelo código** (CLI para mostrar
  fontes, banco para salvar), não pelo modelo.

## Metas
- Habilitar/desabilitar grupos e tools por configuração, sem mexer no código das tools.
- Toda tool publica no canal lateral por uma API única (`publish`), e o consumidor consulta por sessão/toolkit/tool.
- Funcionar também quando um subagente chama a tool (deep research).
- Primeira tool real: busca web com Tavily (`tools/tavily.py`), publicando as fontes.

## Fora do escopo (agora)
- Persistência em banco do canal lateral e a exibição das fontes na CLI (o canal fica pronto para isso).
- Tool que deixa o modelo consultar o canal lateral (o consumidor é o código).
- `table.py` (não existe no disco; entra quando você o criar, seguindo o mesmo contrato).

## Anti-metas
- Tool que só funciona se o modelo "lembrar" de pedir as fontes.
- Parâmetros ou lógica de provedor de LLM dentro da toolkit (continua em `ProviderRules`).

## Abordagens consideradas
- **A. Objeto `SideChannel` compartilhado (escolhida).** A tool publica no canal; o consumidor lê. Funciona com
  subagentes, é simples, independe do estado de mensagens. Custo: vive em memória; persistência é um consumidor futuro.
- **B. Artifact nativo do LangChain** (`content_and_artifact`). Rastreabilidade grátis, mas só lido após o turno e
  artifacts de subagentes não chegam ao agente principal. Descartada.
- **C. A + B juntos.** Mais completa, mais complexa; sem ganho agora. Descartada.
Escolha: A (decisão delegada ao Claude por você).

## Design
```
deep_agents/toolkit/
  build_toolkit.py   ToolkitBuilder, ToolkitConfig
  side_channel.py    SideChannel, Publication
  tools/
    base.py          ToolGroup (contrato dos grupos)
    tavily.py        TavilyTools
```

**`Publication`** (dataclass): `id`, `session_id`, `turn`, `toolkit`, `tool`, `kind` (ex.: `"sources"`),
`payload` (dict/list JSON-serializável), `created_at`.

**`SideChannel`**
- `publish(toolkit, tool, kind, payload)`: preenche sessão/turno atuais e guarda.
- `query(session_id=None, toolkit=None, tool=None, kind=None, turn=None) -> list[Publication]`.
- `subscribe(callback)`: consumidor em tempo real (CLI/banco no futuro).
- `begin_turn()`: a CLI chama a cada mensagem do usuário para marcar o turno.
- Recebe `session_provider: Callable[[], str]` (a CLI passa `memory.session_id`), então acompanha `/pulisci` e `/sessioni`.
- Thread-safe (lock), pois subagentes podem rodar tools em paralelo.

**`ToolGroup`** (base): atributos `name`, `description`; recebe o `SideChannel` no construtor; método
`tools() -> dict[str, callable]` com as tools do grupo (nome → função com docstring e type hints, que o
Deep Agents transforma em schema). Cada grupo é um arquivo.

**`TavilyTools`**: tool `internet_search(query, max_results=5, topic="general")`. Chama o `TavilyClient`
(chave em `TAVILY_API_KEY`), devolve ao modelo título, URL e trecho de cada resultado, e publica no canal
`kind="sources"` uma lista `{domain, title, url}`. Falha da API: devolve ao modelo texto de erro curto (não derruba o turno).

**`ToolkitBuilder(config, channel)`** com `ToolkitConfig`: `{grupo: {"enabled": bool, "tools": [nomes] | None}}`.
- `build() -> list[callable]`: só tools habilitadas (grupo habilitado e, se `tools` informado, só as listadas).
- Nome de grupo/tool inexistente na config: erro explícito (não no-op silencioso).
- Expõe `channel` para o chamador.

**Integração**
- `AgentBuilder.__init__(config, memory=None, toolkit=None)`; `build_tools()` devolve `toolkit.build()`.
  O `{"type": "web_search"}` nativo da OpenAI sai (não passa por código nosso, não publica).
- `cli/__main__.py` cria o `SideChannel(session_provider=lambda: memory.session_id)` e o `ToolkitBuilder` uma vez e
  os passa à fábrica `create_agent`, para sobreviverem às reconstruções (`/modello`), como o `MemoryBuilder`.
- `ChatCLI` chama `channel.begin_turn()` ao receber cada mensagem. Nenhum desenho novo no terminal agora.
- `pyproject.toml`: adicionar `tavily-python`.
- `agent_prompts`/`prompts/skills/busca-na-web`: revisar para a tool continuar chamada `internet_search`
  (mantém o nome atual para não quebrar prompts).

**Testes** (`tests/`): `SideChannel` (publish/query/filtros/sessão/thread-safety), `ToolkitBuilder`
(habilitar/desabilitar, nomes inválidos), `TavilyTools` com cliente fake (retorno ao modelo + publicação).

## Decisões minhas (confira)
1. Tavily substitui o `web_search` nativo da OpenAI.
2. Canal em memória, escopo por `session_id` e `turn`; sem `tool_call_id` (exigiria `ToolRuntime`, complexidade sem uso agora).
3. Config da toolkit definida em código (`cli/__main__.py`), não em arquivo externo.
4. Comentários/docstrings em português e nomes em inglês, como o `CLAUDE.md` pede.

## Deixado ao implementador
Formato exato dos trechos devolvidos ao modelo; limite de tamanho dos resultados; nomes internos dos módulos de teste.
