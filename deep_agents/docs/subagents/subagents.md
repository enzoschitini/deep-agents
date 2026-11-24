# Subagents no Deep Agents: normais e dinâmicos

Material de estudo. Não faz parte do runtime. O script de teste dos subagents dinâmicos é [dynamic_subagents.py](dynamic_subagents.py).

## 1. Subagents normais

### O que são

Um subagent é um agente separado que o agente principal chama pela tool `task`. Ele **não** é só um prompt com tools. A diferença está no **contexto isolado**: o subagent roda numa conversa própria e em branco, e o principal recebe apenas a resposta final.

### Por que usar em vez de passar as tools direto ao principal

| Aspecto | Tools no principal | Subagent |
|---|---|---|
| Contexto | Compartilhado: cada resultado bruto (busca, página) entra no histórico e fica lá nos turnos seguintes | Isolado: o trabalho pesado fica fora, só a conclusão volta |
| Paralelismo | Um único fio de raciocínio | Várias `task` na mesma rodada, uma por ângulo, ao mesmo tempo |
| Prompt | Tudo no system prompt do principal | Instruções próprias do papel; o principal só precisa saber *quando* delegar |
| Tools | O principal carrega todas | Cada subagent vê só as dele |
| Limite de chamadas | Um só | Separado (`SUBAGENT_CALL_LIMIT`) |
| Modelo | O do principal | Pode ser outro, mais barato (neste projeto todos usam o do gateway) |

O ganho principal é o primeiro: reduz custo e evita estourar o contexto. O `CLAUDE.md` do pacote registra o problema que isso evita: reenviar resultados brutos de busca custava cerca de 24 mil tokens por pergunta.

### Quando compensa

- Tarefa que gera muito material intermediário (várias buscas, leitura de páginas longas).
- Trabalho divisível em partes independentes (ex.: 3+ ângulos de pesquisa em paralelo).
- Papel com instruções longas ou específicas que poluiriam o prompt do principal.

### Quando não compensa

- **Tarefa curta:** uma busca única ou uma resposta simples fica mais cara e lenta, porque cada `task` é uma chamada extra de modelo.
- **Principal precisa ver o resultado inteiro:** ele só vê o resumo do subagent, o que pode perder detalhe. Por isso o `redator` devolve o post completo e a regra `08_subagentes.md` manda o principal entregá-lo sem resumir.
- **Muita troca de contexto entre etapas:** o subagent não enxerga a conversa. Tudo o que ele precisa tem que ir na `description` da `task`.

## 2. Subagents dinâmicos

### O que "dinâmico" significa

Dinâmico **não** quer dizer que o modelo cria papéis novos. Quer dizer que o modelo decide **em tempo de execução** quais subagents despachar, quantos, e com qual tarefa, escrevendo código JavaScript que roda no `eval` (REPL do `CodeInterpreterMiddleware`, pacote `langchain-quickjs`).

O `task()` dentro do `eval` aceita só:

| Campo | Função |
|---|---|
| `description` | Instruções da tarefa |
| `subagentType` | Nome de um subagent **já registrado** em `subagents=[...]` |
| `responseSchema` | (opcional) JSON schema para saída estruturada, devolvida já como objeto |

Não há campo para system prompt nem tools. O código-fonte confirma: `call_subagent_task_tool` em `langchain_quickjs/_subagent.py` repassa `subagent_type` à tool `task` do Deep Agents, que resolve o nome na lista registrada.

### O que é dinâmico, na prática

- **Quantidade:** vem dos dados. 5 tickets = 5 chamadas; 500 = 500.
- **Composição:** o código decide quais papéis chamar e em que ordem.
- **Tarefa de cada instância:** gerada em runtime (ex.: um estilo diferente por instância).
- **Fluxo:** `Promise.all`, loops, votação, torneio. As etapas seguintes dependem dos resultados das anteriores.
- **Saída:** `responseSchema` entrega objetos que o código manipula sem parsear texto.

Exemplo real de uma execução do `dynamic_subagents.py` (pedido: "gere 4 nomes para um app de finanças e faça um torneio com o juiz"): 4 instâncias de `criador` em paralelo, depois 2 semifinais e 1 final com o `juiz`. Foram 7 chamadas de 2 papéis, orquestradas por código. Os resultados intermediários ficaram em variáveis JS, e o principal só viu o resumo final.

### Para que serve

A função prática é fazer **código** orquestrar o trabalho, e não o modelo turno a turno.

- **Paralelismo em massa:** `Promise.all` despacha dezenas de subagents de uma vez, sem uma ida ao modelo por rodada.
- **Menos contexto no principal:** resultados intermediários ficam em variáveis JS.
- **Fluxo determinístico:** loops e condicionais são `for` e `if`, não dependem do modelo lembrar a próxima etapa.
- **Escala sob demanda.**

Casos de uso:

- Processar lotes (classificar ou analisar centenas de itens, um subagent por item).
- Votação e verificação adversarial (3 verificadores por afirmação, mantendo o que a maioria confirmar).
- Gerar N opções e selecionar com torneio.
- Pipeline com etapas dependentes (classificar e depois analisar com o subagent certo por categoria).
- Map-reduce (dividir, processar em paralelo, consolidar).

### Quando não compensa

- Pedidos simples ou lineares: responder direto ou usar um `task` é mais barato.
- Poucos itens (2 ou 3): a orquestração só soma latência e tokens. O torneio de 4 nomes levou cerca de 1,5 minuto e 7 chamadas.
- Etapas que exigem julgamento aberto no meio do caminho: o fluxo fixo atrapalha.

### Quer papéis criados na hora?

Duas alternativas, ambas fora do recurso padrão:

1. **Subagent genérico:** registrar um `especialista` com system prompt neutro; o papel vai na `description` de cada `task()`. É simples e usa só o que já existe.
2. **Tool própria:** uma tool exposta ao `eval` que recebe `{nome, system_prompt, tools}` e monta um subagent com `create_agent`. Dá mais flexibilidade, mas o modelo passa a definir prompts e permissões, o que exige mais cuidado.

## 3. Comparação rápida

| | Tools no principal | Subagent normal | Subagent dinâmico |
|---|---|---|---|
| Quem decide o fluxo | O modelo, a cada turno | O modelo, a cada turno | Código JS escrito pelo modelo |
| Contexto do principal | Cresce a cada chamada | Só recebe a conclusão de cada `task` | Só recebe o resultado final do script |
| Paralelismo | Não | Algumas `task` por rodada | Centenas, via `Promise.all` |
| Novos papéis em runtime | Não se aplica | Não | Não (só novas instâncias dos registrados) |
| Melhor para | Consultas pequenas | Pesquisa pesada, divisão em poucos ângulos | Lotes, votação, torneios, pipelines |

## 4. Como ver o que o dinâmico está fazendo

O `langchain_quickjs` emite eventos de ciclo de vida de cada `task()` no stream `custom` do LangGraph:

| Evento | Campos |
|---|---|
| `start` | `id`, `subagent_type`, `label`, `description` (truncada em 200 chars), `eval_id` |
| `complete` | `id`, `duration_ms`, `eval_id` |
| `error` | `id`, `duration_ms`, `error`, `eval_id` |

Todos têm `type: "subagent"`. O `id` é chave de idempotência: se o `eval` for reexecutado (retomada após interrupção), o `start` repete o mesmo `id`, então deve-se fazer upsert, não append.

O `dynamic_subagents.py` usa `agent.stream(..., stream_mode=["updates", "custom"], subgraphs=True)`. Cada item vem como `(namespace, modo, dados)`: `custom` traz esses eventos e `updates` traz as mensagens do agente e dos subagents.

## 5. Neste projeto

- Subagents normais: [subagents/](../../subagents/) (`pesquisador`, `redator`), compilados como `CompiledSubAgent` por causa do `HarnessProfile` (detalhes no `CLAUDE.md` do pacote). A regra de delegação está em `prompts/rules/08_subagentes.md`.
- Subagents dinâmicos: só no script de teste [dynamic_subagents.py](dynamic_subagents.py), ainda não integrados ao agente principal.
