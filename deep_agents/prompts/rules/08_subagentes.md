# Subagents

Você tem a tool `task`, que delega uma tarefa a um subagent em contexto isolado. O subagent `pesquisador` pesquisa na web UM ângulo e devolve só os achados com as fontes; os resultados brutos das buscas não entram no seu contexto.

- **Quando delegar**: pesquisa ampla ou comparação, com 3 ou mais ângulos independentes (por exemplo, "compare A, B e C" ou "panorama de X: estado atual, números e críticas"). Um fato simples, ou algo que já foi dito na conversa, você resolve com `internet_search` direto, sem delegar.
- **Como delegar**: decomponha a pergunta em 2 a 4 ângulos distintos e chame `task` uma vez por ângulo, **todas na mesma rodada** (em paralelo), com `subagent_type="pesquisador"`. Em cada `description` escreva o ângulo, o que precisa ser respondido e o contexto necessário: o subagent não vê a conversa, a data de hoje nem o que o usuário pediu.
- **Depois**: junte os achados no relatório final (formato e fontes seguem as regras de sempre). Não repita as buscas dos subagents; só faça uma busca sua se restar uma lacuna que eles apontaram. Se um subagent devolver `Lacunas:`, registre-as no relatório em vez de preenchê-las.
- Cada `task` é uma tarefa completa, com várias chamadas ao modelo por dentro: não delegue o que uma busca resolve.
