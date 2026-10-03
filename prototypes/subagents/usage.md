# subagentes — uso

Este protótipo é um plantão de incidentes: o `coordinator` não investiga nada, só
delega. O roster tem três subagentes isolados (`log-analyst`, `impact-analyst`,
`general-purpose`), um grafo compilado (`timeline-builder`) e um fork
(`postmortem-writer`), que herda toda a conversa do pai. O incidente de exemplo é o
INC-2043, em `incidents/`.

## Execução

Normal:

    python -m prototypes.subagents.run_agent

CLI:

    python prototypes/subagents/run_agent.py [flags]
    python prototypes/subagents/run_agent.py --chat [flags]

Flags:

- `--model <provider:model>` — padrão `anthropic:claude-sonnet-4-6`
- `--analyst-model <provider:model>` — modelo só do `log-analyst` e do
  `impact-analyst`, para comparar "escolher modelo por tarefa" sem trocar o resto
- `--roster full|gp-override|gp-off|no-task` — `full`: o `general-purpose` é
  adicionado automaticamente e herda as skills do coordenador; `gp-override`: a nossa
  própria spec com esse nome substitui a padrão; `gp-off`: o profile desliga o
  `general-purpose`, mas a ferramenta `task` continua porque ainda há subagentes;
  `no-task`: sem nenhum subagente síncrono, e aí o `task` desaparece
- `--descriptions specific|vague` — `vague` reproduz o troubleshooting da doc: o
  coordenador deixa de delegar ou chama o subagente errado
- `--interrupt off|on` — `on` pausa para aprovação humana antes de gravar o
  post-mortem (`interrupt_on` no fork)
- `--dynamic off|on|task-only` — `on` liga o `CodeInterpreterMiddleware`;
  `task-only` mantém o interpretador mas força a delegação pelo `task`. Requer
  `deepagents[quickjs]`, que **não** instala neste ambiente (ver o fim deste arquivo)
- `--context default|strict|deep` — valores repassados a todos os subagentes:
  `strict` faz o `impact-analyst` ver as margens de erro, `deep` faz o `log-analyst`
  ler o log inteiro em vez de só o começo
- `--stream updates|events` — `events` usa `stream_events(version="v3")` e desenha um
  painel ao vivo por subagente; `updates` é o transcript simples e é o único que
  trata as pausas de aprovação

## Comandos do chat

- `/roster` — lista o roster configurado e se a ferramenta `task` existe
- `/roster <modo>` — troca o roster: `full`, `gp-override`, `gp-off`, `no-task`
- `/descriptions <estilo>` — troca as descrições dos subagentes: `specific`, `vague`
- `/interrupt <valor>` — aprovação humana na escrita do post-mortem: `off`, `on`
- `/dynamic <valor>` — interpretador de código: `off`, `on`, `task-only`
- `/context <valor>` — contexto da execução: `default`, `strict`, `deep`
- `/stream <valor>` — renderização do turno: `updates`, `events`
- `/journal [agente]` — consultas ao `shared_lookup`, filtradas por `lc_agent_name`
- `/journal clear` — limpa o journal
- `/preamble` — como o fork vê a conversa do pai
- `/help`, `/exit`

## Prompts para experimentar

1. "Assuma o incidente INC-2043: investigue a causa raiz, estime o impacto, monte a
   cronologia e grave o post-mortem." (prompt padrão) — exercita: skill
   `incident-triage`, as quatro delegações, subagente isolado com skills próprias,
   `response_format` do `impact-analyst`, `CompiledSubAgent`, fork, escrita em
   `/reports/`. Esperado: um `◆ delegando → <nome> (<modo>)` por chamada de `task`,
   `◆ ativando incident-triage` na leitura do SKILL.md, o retorno do
   `impact-analyst` em JSON na linha `←`, e os marcadores `[subagent:...]` e
   `[coordinator:final]` em verde na resposta.
2. "Qual foi a causa raiz do INC-2043? Consulte o runbook sobre db.pool.max_size."
   Depois `/journal` e `/journal log-analyst` — exercita: `shared_lookup`
   compartilhado, `lc_agent_name` no metadata da run, skill `log-forensics`.
   Esperado: o journal mostra a mesma ferramenta chamada com nomes de agente
   diferentes; filtrar por `log-analyst` é o equivalente local ao filtro
   `has(metadata, '{"lc_agent_name": "log-analyst"}')` da doc.
3. `/context deep`, depois "Leia o log do INC-2043 e diga o primeiro sinal do
   problema." — exercita: contexto propagado do pai para o subagente,
   `log_analyst_max_lines` lido em `runtime.context`. Esperado: o `log-analyst`
   deixa de avisar sobre linhas omitidas. Com `/context strict`, o `impact-analyst`
   passa a citar as margens de erro.
4. `/descriptions vague`, depois o prompt 1 de novo — exercita: "subagent not being
   called" e "wrong subagent being selected". Esperado: nenhuma ou poucas chamadas de
   `task`, o coordenador tentando resolver sozinho, e a resposta sem os marcadores
   `[subagent:...]`. Volte com `/descriptions specific` para comparar.
5. `/roster no-task`, depois "Quem está disponível para delegar?" e `/roster` —
   exercita: `GeneralPurposeSubagentProfile(enabled=False)` sem nenhum subagente
   síncrono. Esperado: `/roster` imprime "sem ferramenta task: nada para delegar", e o
   agente responde sem delegar. Com `/roster gp-off`, o `task` reaparece.
6. `/stream events`, depois o prompt 1 — exercita
   `stream_events(version="v3")` e a projeção `subagents`. Esperado: um painel
   `┌ <nome> iniciou ... └ <nome> status: ...` por subagente, com o trabalho interno
   dele visível, que é o que o pai justamente não recebe. Alguns painéis saem vazios
   entre o `┌` e o `└`: as projeções do handle só podem ser consumidas antes do ciclo
   seguinte do stream, e quando o subagente já terminou antes disso sobra só o
   `status`. O `status: completed` continua correto.
7. `/interrupt on`, depois "Grave o post-mortem do INC-2043." — exercita
   `interrupt_on` em um subagente. Esperado: a pausa `PAUSADO` com a pergunta
   `aprovar? [s/N]` antes do `write_postmortem`.
8. "Qual a capital do Japão?" (controle) — não deve acionar nenhum mecanismo.
   Esperado: resposta curta e direta, sem chamadas de `task`, sem leitura de skill e
   sem marcadores `[subagent:...]`.

## Subagentes dinâmicos

A seção *Dynamic subagents* da doc está implementada em `agent.py`
(`_interpreter_middleware`), mas não roda nesta máquina: `langchain-quickjs` depende
de `bsdiff4`, que não tem wheel para Python 3.14 e precisa do compilador MSVC para
compilar. Com `--dynamic on` o protótipo avisa isso e segue delegando pelo `task`. O
mecanismo passa a funcionar sozinho no dia em que o pacote instalar — aí vale pedir um
"workflow" no prompt, que é o gatilho que a doc indica para o fan-out a partir do
código.
