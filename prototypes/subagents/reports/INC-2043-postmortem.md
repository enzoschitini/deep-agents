# Post-Mortem — INC-2043: Checkout fora do ar

**Data do incidente:** 12/03  
**Horário:** 14:14 – 15:09 (horário de Brasília)  
**Duração total:** 55 minutos  
**Serviço afetado:** `checkout-api` (produção, região sa-east-1)  
**Plantonista:** sre-duty-01  
**Status:** Resolvido — post-mortem concluído  

---

## Resumo Executivo

Um deploy da versão `v4.18.2` da `checkout-api` introduziu um valor incorreto de configuração — `db.pool.max_size=5` em vez do valor esperado de **50** — reduzindo em 90% o pool de conexões ao banco `orders-db`. O esgotamento imediato do pool gerou cascade de timeouts e respostas HTTP 503 para os clientes durante **55 minutos**. O serviço foi restaurado via rollback para a versão anterior. O impacto estimado foi de **12.480 usuários afetados** e **R$ 588.436** em receita em risco.

---

## Cronologia

| Horário | Evento |
|---------|--------|
| **14:14** | Deploy `v4.18.2` realizado com configuração incorreta: `db.pool.max_size=5` (deveria ser 50). **Início do incidente.** |
| **14:15** | `WARN`: pool `orders-db` atinge capacidade máxima (5/5); fila de requisições começa a crescer. Primeiros erros 503 surgem às 14:15:19. |
| **14:16 – 14:20** | Erros 503 se multiplicam; checkout completamente indisponível para usuários finais. Toda tentativa de conexão ao banco entra em timeout. |
| **14:21** | ⚠️ Alerta automático disparado: taxa de erro > 5% detectada pelo monitoramento. Equipe de plantão notificada. **Atraso de detecção: 7 minutos.** |
| **14:22 – 14:25** | Equipe inicia triagem; análise de logs aponta esgotamento do pool de conexões do `orders-db`. |
| **14:26** | Configuração incorreta `db.pool.max_size=5` confirmada como causa raiz. Correlação com deploy `v4.18.2` estabelecida. |
| **14:27 – 14:28** | Decisão de rollback aprovada. Início do processo de rollback. |
| **14:29 – 14:59** | Rollback em execução; monitoramento ativo. Serviço permanece indisponível durante o processo. |
| **15:00 – 15:05** | Sinais iniciais de recuperação do pool de conexões; fila de requisições começa a drenar. |
| **15:09** | ✅ Rollback de `v4.18.2` concluído. Pool `orders-db` retorna a `max_size=50`. Serviço normalizado. **Fim do incidente.** |

---

## Causa Raiz

O deploy da `checkout-api v4.18.2` introduziu o valor `db.pool.max_size=5` na configuração de produção, substituindo o valor correto de **50**. Essa mudança reduziu o pool de conexões ao `orders-db` em **90%**, saturando-o imediatamente e causando cascade de timeouts em todas as requisições de checkout.

### Evidências nos logs

```
14:14:02 INFO  checkout-api configuracao carregada: db.pool.max_size=5 (anterior: 50)
14:15:10 WARN  orders-db pool de conexoes em 5/5, 2 requisicoes na fila
14:15:19 ERROR checkout-api timeout ao obter conexao do pool apos 3000ms (order_id=88214)
```

> **Nota:** O `payments-gateway` permaneceu saudável durante todo o período (pool separado, isolado da falha). Os erros HTTP 503 e a saturação do `orders-db` são sintomas, não a causa raiz.

---

## Impacto

| Métrica | Valor |
|---------|-------|
| **Severidade** | Alta |
| **Duração** | 55 minutos (14:14 – 15:09) |
| **Atraso de detecção** | 7 minutos |
| **Usuários afetados** | 12.480 usuários únicos |
| **Pedidos perdidos (estimado)** | 3.140 pedidos |
| **Ticket médio** | R$ 187,40 |
| **Receita em risco** | R$ 588.436 |
| **Grau de confiança** | 82% |
| **Taxa de erro de pico** | 6,4% |

**Fatores agravantes:**
- Incidente ocorreu em janela de alto tráfego (14h–15h, horário comercial de Brasília).
- O atraso de 7 minutos na detecção ampliou a janela de impacto evitável.
- Ausência de SLA documentado para `checkout-api` no runbook interno.

---

## O que foi bem

- O `payments-gateway` permaneceu isolado e saudável durante todo o incidente.
- O rollback foi identificado como solução correta e executado com determinação.
- O sistema de alerta automático funcionou, embora com atraso.

---

## O que pode melhorar

- O alerta só disparou com 7 minutos de atraso (threshold de 5% de erro), permitindo impacto desnecessário.
- Não havia validação automática de parâmetros críticos de configuração no pipeline de deploy.
- O runbook não documenta SLA de `checkout-api` nem procedimento específico para saturação de pool.

---

## Ações Corretivas

| Ação | Responsável | Prazo |
|------|-------------|-------|
| Adicionar validação de `db.pool.max_size` no pipeline de CI/CD (valor mínimo aceitável em produção: 20) | Time de Plataforma | 1 semana |
| Reduzir threshold do alerta de taxa de erro de 5% para 1% para `checkout-api` | SRE | 3 dias |
| Documentar SLA da `checkout-api` e adicionar runbook específico para esgotamento de pool de conexões | Time de Produto + SRE | 2 semanas |
| Revisar todas as mudanças de configuração de `db.pool.*` para outros serviços críticos | Time de Plataforma | 2 semanas |
| Implementar smoke test pós-deploy que valide conectividade ao `orders-db` antes de promover o rollout | Time de Plataforma | 2 semanas |

---

## Lições Aprendidas

1. **Configuração é código** — mudanças em parâmetros críticos como tamanho de pool devem passar por revisão e validação automatizada, não apenas revisão manual.
2. **Detecção precoce reduz impacto** — 7 minutos de atraso custaram potencialmente centenas de pedidos; alertas mais sensíveis são justificados para serviços de checkout.
3. **Rollback deve ser rápido** — o processo levou ~41 minutos desde a decisão até a normalização; há espaço para otimizar o pipeline de rollback.

---

*Post-mortem elaborado com base em logs (`/incidents/logs/INC-2043.log`), métricas (`/incidents/metrics/INC-2043.csv`) e runbook interno (`/incidents/runbook.md`).*  
*Gerado em: 12/03 — Revisado por: sre-duty-01*

[subagent:postmortem-writer]
