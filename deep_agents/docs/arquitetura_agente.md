# Arquitetura de construção do agente

Padrão para adicionar qualquer recurso novo ao agente (modelo, prompt, ferramentas, memória, subagentes…).
Siga este documento em toda feature nova, para o projeto continuar uniforme.

## A ideia em uma frase

**Cada recurso do agente vive em uma pasta própria, com uma classe principal (fachada) que esconde os detalhes.
O `agent.py` só monta as peças: um método `build_*` por recurso, que chama a classe principal da pasta.**

```
agent.py  ──►  AgentBuilder
                 ├── build_model()   ──►  model/    →  LLMGateway
                 ├── build_prompt()  ──►  prompts/  →  AgentPrompts
                 ├── build_tools()   ──►  tools/    →  (classe principal da pasta)
                 └── build()         ──►  junta tudo em create_deep_agent(...)
```

## Regras

1. **Uma pasta por recurso**, dentro de `deep_agents/` (`model/`, `prompts/`, `tools/`, …).
2. **Dentro da pasta, arquivos pequenos**, cada um com uma responsabilidade (config, regras, textos, métricas…).
   Todo o trabalho de preparar o recurso acontece ali, nunca no `agent.py`.
3. **Uma classe principal por pasta**, a fachada. É a única coisa que o `agent.py` importa daquela pasta.
   Ela expõe propriedades/métodos com exatamente o que o `create_deep_agent` precisa.
4. **O `agent.py` não conhece detalhes**: sem caminhos de arquivo, sem montar backend, sem renomear parâmetros de provedor.
   Se você está escrevendo isso no `agent.py`, o código pertence à pasta do recurso.
5. **Um método `build_<recurso>()` por recurso** na classe `AgentBuilder`. Ele instancia/usa a classe principal
   e devolve o que o `create_deep_agent` espera (um objeto, uma lista ou um `dict` de argumentos).
6. **`build()` só junta**: chama os `build_*` e passa o resultado para `create_deep_agent`. Sem lógica própria.
7. **Textos de prompt ficam fora do código**: regras longas em `.md`, textos curtos em um `.py` de constantes.
8. **Sem função solta de construção** além da classe (ex.: nada de `build_agent()` depois do `AgentBuilder`).
   Quem precisa de uma fábrica (a CLI) a define do seu lado: `AgentBuilder(config).build()`.

## Como está hoje

| Recurso | Pasta | Classe principal | Método no `AgentBuilder` | O que a pasta contém |
|---|---|---|---|---|
| Modelo | `model/` | `LLMGateway` | `build_model()` | `model_config.py` (`ModelConfig`), `provider_rules.py` (regras por provedor), `metrics*.py` (tokens, latência, custo) |
| Prompt | `prompts/` | `AgentPrompts` (`agent_prompts.py`) | `build_prompt()` | `system.py` (textos), `harness_profile.py` (perfil por modelo), `rules/*.md` (regras carregadas via `memory=`) |
| Ferramentas | — | ainda não existe | `build_tools()` | hoje devolve `[internet_search]` direto no `agent.py` (pendente de extrair, ver abaixo) |

`AgentBuilder` (em `agent.py`):

```python
class AgentBuilder:
    def __init__(self, config):
        self.config = config
        self.gateway = LLMGateway(config)      # classe principal de model/
        self.prompts = AgentPrompts()          # classe principal de prompts/

    def build_model(self):  return self.gateway.build()
    def build_prompt(self): ...                # usa self.prompts.* e devolve os kwargs de prompt
    def build_tools(self):  ...

    def build(self):
        agent = create_deep_agent(model=self.build_model(), tools=self.build_tools(), **self.build_prompt())
        return agent, self.gateway
```

## Como adicionar um recurso novo

Exemplo: ferramentas (o mesmo vale para memória de longo prazo, subagentes, skills, middleware…).

1. **Crie a pasta**: `deep_agents/tools/`.
2. **Crie os arquivos do recurso**, um por responsabilidade (ex.: `search.py` com a definição de `internet_search`,
   `registry.py` com a lista de ferramentas ativas).
3. **Crie a classe principal** (ex.: `AgentTools` em `tools/agent_tools.py`) com o que o agente precisa:
   ```python
   class AgentTools:
       @property
       def tools(self) -> list: ...
   ```
4. **Ligue no `AgentBuilder`**: instancie no `__init__` e use no método `build_tools()`:
   ```python
   self.tools = AgentTools()
   def build_tools(self): return self.tools.tools
   ```
5. **Se o recurso entra no `create_deep_agent` por um parâmetro novo** (ex.: `subagents=`), adicione um método
   `build_subagents()` e passe o resultado em `build()`. Recurso que gera vários argumentos devolve um `dict` e entra com `**`.
6. **Atualize** o `CLAUDE.md` (tabela de estrutura) e a tabela "Como está hoje" deste documento.

## Checklist antes de abrir o PR

- [ ] O recurso tem pasta própria e uma classe principal?
- [ ] O `agent.py` só importa a classe principal, sem detalhes internos da pasta?
- [ ] Existe um `build_<recurso>()` no `AgentBuilder`, sem lógica além de chamar a classe principal?
- [ ] Textos longos de prompt estão em `.md` ou em constantes, não espalhados no código?
- [ ] `CLAUDE.md` e a tabela deste documento estão atualizados?
- [ ] Se o recurso depende do modelo (como o perfil do harness), ele é refeito a cada troca de modelo (`/modello`)?
      A CLI reconstrói o agente com `AgentBuilder(config).build()`, então o `build_*` correspondente deve rodar de novo.

## Observações

- **Reconstrução a cada troca**: `build_prompt()` chama `register_harness(spec)` porque o perfil do harness é registrado
  por modelo. Qualquer recurso que dependa do `spec` do modelo deve ser (re)feito dentro do seu `build_*`, não no `__init__`
  de módulo.
- **Nomes dos métodos de prompt**: `AgentPrompts` expõe `system_prompt`, `memory_files`, `backend`, `permissions` e
  `register_harness`. O `build_prompt()` apenas os agrupa nos nomes de parâmetro do `create_deep_agent`
  (`system_prompt`, `memory`, `backend`, `permissions`).
- **Pendência conhecida**: `internet_search` ainda está definido direto em `agent.py`. Ao extraí-lo para `tools/`,
  este documento deixa de ter exceções.
