# Runbook de serviços — Nimbus

Uma linha por serviço ou termo, para consulta pontual pelo `shared_lookup`.

- checkout-api — API de finalização de compra. SLA 99.9%. Dono: time Payments. Rollback via `deployer rollback <versao>`.
- orders-db — PostgreSQL de pedidos. Pool de conexões dimensionado para 50 por pod; abaixo de 20 o checkout satura em minutos.
- payments-gateway — integração com adquirentes. SLA 99.95%. Dono: time Payments. Não compartilha pool com o orders-db.
- db.pool.max_size — tamanho máximo do pool de conexões por pod. Valor padrão em produção: 50. Alterações exigem revisão do time de plataforma.
- deployer — serviço de rollout. Estratégia rolling, 4 pods por vez, sem canário para o checkout-api.
- monitoring — alerta de taxa de erro com limiar de 5% em janela de 1 minuto; é a causa conhecida de atrasos de detecção.
- atraso de deteccao — tempo entre o primeiro erro de cliente e o disparo do alerta. Meta interna: menos de 2 minutos.
- severidade — critica acima de 10 mil usuarios afetados, alta entre 2 mil e 10 mil, media entre 200 e 2 mil, baixa abaixo disso.
- post-mortem — obrigatório para incidentes de severidade alta ou crítica, em até 5 dias úteis. Modelo em /reports/.
