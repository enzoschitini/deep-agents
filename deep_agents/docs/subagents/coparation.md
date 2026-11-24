# Delegação no Deep Agents: Subagents, Dynamic Subagents e Async Subagents

Resumo das três formas de delegar trabalho no Deep Agents (LangChain), baseado na documentação oficial (seção *Delegation*) e nos testes feitos com os scripts desta pasta.

## Visão geral em uma frase cada

| Tipo | Em uma frase |
|---|---|
| **Subagents (síncronos)** | O agente principal chama um subagent pela ferramenta `task`, **espera** o resultado e só recebe o texto final (o trabalho intermediário fica isolado). |
| **Dynamic subagents** | O agente escreve **código JavaScript** num interpretador e chama `task()` de dentro de loops e `Promise.all`, orquestrando muitos subagents de forma programática. |
| **Async subagents** | O supervisor **lança tarefas em background** em um servidor, recebe um `task_id` na hora e continua conversando; pode checar, atualizar e cancelar. |

Os três constroem uma sobre a outra: os dynamic subagents usam os mesmos subagents síncronos por baixo (o `task()` do JS dispara a mesma execução), e os async subagents são um mecanismo à parte, que roda em servidor.

---

## 1. Subagents (síncronos)

**O que é.** Você declara uma lista de subagents (`name`, `description`, `system_prompt`, e opcionalmente `tools`, `model`, `middleware`, `skills`, `response_format`, `interrupt_on`, `permissions`). O agente principal decide quando delegar, usando o `description` como guia. Ele fica bloqueado até o subagent terminar e recebe só a resposta final.

**Ideia central: "context quarantine".** O trabalho intermediário (buscas, leituras, tentativas) não polui o contexto do agente principal.

**Pontos importantes**
- Existe um subagent `general-purpose` criado automaticamente (mesmas ferramentas e modelo do principal), a menos que você defina um com esse nome.
- `tools`, quando definido, **substitui** as ferramentas herdadas.
- `system_prompt` não é herdado do agente principal.
- Cada subagent pode usar um `model` diferente.
- `mode: "fork"` (beta) faz o subagent herdar a conversa do pai.
- `response_format` faz o pai receber JSON no schema definido, em vez de texto livre.
- Também há `CompiledSubAgent`, em que você entrega um grafo LangGraph já compilado.

**Quando usar**
- Tarefa de vários passos que encheria o contexto do agente principal.
- Domínio especializado que pede instruções ou ferramentas próprias (revisor de segurança, analista financeiro).
- Tarefa que se beneficia de outro modelo (por exemplo, um com contexto grande para documentos longos).
- O agente precisa do resultado **antes de continuar**.

**Quando evitar.** Tarefas simples de um passo, ou quando o agente principal precisa enxergar o contexto intermediário.

**Exemplo de caso de uso:** "Pesquise a fundo este tema e me devolva um resumo de 10 linhas." O principal espera e usa o resumo.

---

## 2. Dynamic subagents

**O que é.** Com o `CodeInterpreterMiddleware` (pacote `langchain-quickjs`), o agente ganha uma ferramenta `eval` (REPL JavaScript) e um global `task()`:

```js
const review = await task({
  description: "Revise src/auth/login.ts. Cite linhas.",
  subagentType: "reviewer",
  responseSchema: { /* opcional: saída estruturada */ },
});
```

Em vez de escolher uma chamada de ferramenta por vez, o modelo escreve um programa que faz fan-out, filtra, vota e sintetiza. Para ativar, inclua a palavra **"workflow"** no pedido; sem ela, o agente tende a responder direto.

**Padrões que a documentação lista**
- **Classify and act:** classifica cada item e manda para o subagent especializado.
- **Fan-out and synthesize:** mesma tarefa em muitos itens em paralelo, depois síntese.
- **Adversarial verification:** achados passam por vários verificadores; fica o que a maioria confirma.
- **Generate and filter:** várias propostas independentes, filtradas e ranqueadas em código.
- **Tournament:** variações disputam entre si, com um juiz, em rodadas eliminatórias.
- **Loop until done:** varredura repetida, deduplicando, até não aparecer nada novo.

**Pontos importantes**
- Está em **beta** (requer `langchain-quickjs>=0.2.0`, Python 3.11+).
- Continua **bloqueante**: o `eval` só termina quando todas as chamadas terminam (a concorrência é paralela, mas o agente espera).
- O `task()` roda dentro de um `eval` já aprovado, então `interrupt_on` do pai **não** é aplicado a cada despacho. Se precisar de aprovação, proteja o próprio `eval`.
- O timeout do `eval` (padrão 5 s) mede só o tempo dentro da VM JavaScript, não a espera pelos subagents.
- O estado JS pode persistir entre turnos (`mode="thread"`, padrão).
- Pode ser combinado com *programmatic tool calling* (PTC), por exemplo para listar arquivos com `glob` e despachar um subagent por arquivo. O PTC vem desligado e exige allowlist.
- Desligar: `CodeInterpreterMiddleware(subagents=False)`.

**Quando usar**
- Muitas unidades independentes (revisar todos os arquivos de uma pasta, triar um lote de tickets).
- Precisa de várias perspectivas, votação ou verificação cruzada.
- Quer comportamento **determinístico** de orquestração (loops e condições em código, não decididos a cada passo pelo modelo).
- Análise recursiva, mantendo o conjunto de dados em variáveis do interpretador.

**Exemplo de caso de uso:** "Rode um workflow que classifique 200 tickets e analise cada um com o subagent certo."

---

## 3. Async subagents

**O que é.** O supervisor lança subagents que rodam **em outra thread, num servidor** que implemente o Agent Protocol (LangSmith Agent Server, `langgraph dev` ou um servidor próprio). O lançamento retorna imediatamente com um `task_id` (que é o ID da thread do subagent).

**As cinco ferramentas do supervisor**

| Ferramenta | Função |
|---|---|
| `start_async_task` | Inicia a tarefa e devolve o `task_id` |
| `check_async_task` | Status, resultado, erro ou pedido pendente |
| `update_async_task` | Envia instruções novas (por padrão **interrompe** a execução e reinicia; `update_strategy="enqueue"` enfileira) |
| `cancel_async_task` | Cancela |
| `list_async_tasks` | Lista as tarefas com status ao vivo |

**Configuração (`AsyncSubAgent`)**: `name`, `description`, `graph_id` (obrigatórios); `url` (sem ele, transporte ASGI no mesmo servidor; com ele, HTTP remoto), `headers`, `mode` (`isolated` ou `fork`), `update_strategy`, `webhook`, `notify_parent`.

**Pontos importantes**
- No Agent Server, o subagent **avisa o supervisor** quando termina, falha ou precisa de entrada; o supervisor não precisa fazer polling. Um subagent que termina pode acordar um supervisor ocioso.
- Os metadados das tarefas ficam num canal de estado próprio (`async_tasks`), então sobrevivem à compactação do histórico de mensagens.
- Um subagent pode pausar pedindo entrada humana (`interrupt()`); nesse caso aparece como `waiting`, e quem responde é o seu app, na thread do subagent.
- Os subagents são **stateful**: mantêm estado na própria thread entre interações.
- Em desenvolvimento local, aumente o pool (`langgraph dev --n-jobs-per-worker 10`); cada execução ativa ocupa um slot, e três tarefas simultâneas exigem 4 (1 supervisor + 3 subagents).
- Problemas comuns: o supervisor fazer polling logo após o lançamento (reforce no system prompt), reportar status antigo, ou truncar o `task_id`.
- Partes dependem de versão do `deepagents` (notificações, `update_strategy` e `webhook`/`notify_parent` estão em beta).

**Quando usar**
- Tarefas **longas** que não devem travar a conversa.
- Várias tarefas em paralelo que o usuário quer acompanhar de forma interativa.
- Precisa **mudar o rumo no meio** (update) ou **cancelar**.
- Subagents com escala ou recursos diferentes, mantidos por outro time (transporte HTTP).

**Exemplo de caso de uso:** "Pesquise sobre RAG e, enquanto isso, escreva um post sobre agentes." O supervisor responde na hora com os dois `task_id`s, você continua conversando, e as notificações chegam quando cada um terminar.

---

## Comparativo lado a lado

| Dimensão | Subagents | Dynamic subagents | Async subagents |
|---|---|---|---|
| Quem decide a delegação | O modelo, uma chamada de `task` por vez | O modelo escreve **código** que decide e repete | O modelo, via `start_async_task` |
| O supervisor espera? | Sim | Sim (até o `eval` terminar) | **Não**, retorna um `task_id` |
| Paralelismo | Possível, mas bloqueante | Sim, `Promise.all` em lote | Sim, não bloqueante |
| Onde roda | Dentro da execução do agente | Dentro da execução, via `eval` | Em **thread própria, num servidor** |
| Infra extra | Nenhuma | `langchain-quickjs` | Servidor Agent Protocol (`langgraph dev`, LangSmith, etc.) |
| Resultado | Retorno da ferramenta | Valor retornado no JS (tipado com `responseSchema`) | Notificação ou `check_async_task` |
| Atualizar no meio | Não | Não | Sim (`update_async_task`) |
| Cancelar | Não, sem parar o supervisor | Não | Sim (`cancel_async_task`) |
| Estado entre chamadas | Sem estado | Sem estado nos subagents (variáveis JS podem persistir) | Com estado na thread do subagent |
| Maturidade (segundo a doc) | Estável; partes em beta (`fork`) | Beta | Partes em beta |

## Como escolher

1. **O agente precisa do resultado para continuar?** Use **subagents** (ou **dynamic**, se forem muitos).
2. **São muitas unidades independentes, com loops, votação, torneio ou filtros?** Use **dynamic subagents**, com a palavra "workflow".
3. **A tarefa é longa e você quer continuar conversando, acompanhar, redirecionar ou cancelar?** Use **async subagents**.
4. **Dúvida?** Comece com subagents simples. Suba para dynamic quando surgir fan-out, e para async quando a espera passar a incomodar.

## Os scripts de teste

- `dynamic_subagents_chat.py`: chat em loop com 5 subagents e o interpretador. Mostra o JS que o agente escreve e as respostas de cada subagent.
- `async_demo/async_subagents_chat.py` + `langgraph.json`: sobe o `langgraph dev`, abre um chat que continua livre enquanto `researcher` e `writer` rodam em background, e mostra as notificações quando terminam.

## Fontes

- [Subagents](https://docs.langchain.com/oss/python/deepagents/subagents)
- [Dynamic subagents](https://docs.langchain.com/oss/python/deepagents/dynamic-subagents)
- [Async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents)