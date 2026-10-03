---
name: log-forensics
description: Método de forense em logs de incidente da Nimbus para achar a causa raiz e separá-la dos sintomas. Use ao investigar um log de incidente, procurar a primeira linha em que o problema aparece ou descartar serviços saudáveis.
---

# Forense de logs

Esta skill é exclusiva do subagente `log-analyst` — o coordenador não a vê, porque
subagentes customizados não herdam as skills do agente principal.

1. Leia o log com `read_incident_log`, passando o ID do incidente. Se a saída avisar
   que linhas foram omitidas, diga isso na sua resposta: o limite vem do contexto da
   execução (`log_analyst_max_lines`), não do arquivo.
2. Procure a última linha `INFO` antes do primeiro `ERROR` ou `WARN`. Mudanças de
   configuração e rollouts costumam estar aí, e são causa, não sintoma.
3. Separe causa de sintoma: fila de conexões crescendo e HTTP 503 em série são
   sintomas. Um valor de configuração que mudou é causa.
4. Descarte explicitamente os serviços que seguiram saudáveis — procure linhas de
   `healthcheck ok`.
5. Use `shared_lookup` para conferir no runbook o valor esperado de qualquer
   parâmetro suspeito antes de afirmar que ele está errado.

Responda no formato pedido no seu prompt: causa raiz em uma frase, até três linhas de
log como evidência, e o horário do primeiro sinal. Nunca devolva o log inteiro.

Termine SEMPRE com a linha `[skill:log-forensics]`.
