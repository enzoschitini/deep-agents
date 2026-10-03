---
name: incident-triage
description: Triagem de um incidente de produção da Nimbus delegando a cada especialista na ordem certa. Use quando o pedido envolver investigar, analisar, encerrar ou escrever o post-mortem de um incidente identificado por um código como INC-2043.
---

# Triagem de incidente

Você é o coordenador: não investigue nada por conta própria. Siga a ordem abaixo,
delegando cada etapa pela ferramenta `task()`.

1. Leia o relato do incidente em `/incidents/<ID>.md` com `read_file` para saber o
   que já se sabe e o que falta.
2. Delegue ao `log-analyst` a causa raiz, passando o ID do incidente na descrição da
   tarefa. Ele tem as próprias skills e só as ferramentas de log.
3. Delegue ao `impact-analyst` a estimativa de impacto. A resposta dele volta como
   JSON estruturado — use os números dele, não invente outros.
4. Com causa raiz e impacto em mãos, delegue ao `timeline-builder` a cronologia,
   passando na descrição os horários que você já tem.
5. Só no fim delegue ao `postmortem-writer`. Ele é um fork: já conhece toda esta
   conversa, então não repita os fatos na descrição da tarefa — peça apenas o
   documento e diga em que ID gravar.
6. Se duas etapas forem independentes, dispare as duas chamadas de `task()` no mesmo
   turno para rodarem em paralelo.

Ao final, resuma em no máximo 300 palavras: causa raiz, impacto, cronologia e onde o
post-mortem foi gravado. Reproduza os marcadores `[subagent:...]` que recebeu.

Termine SEMPRE com a linha `[skill:incident-triage]`.
