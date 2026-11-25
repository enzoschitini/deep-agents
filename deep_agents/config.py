"""Configuração do agente: valores que você pode querer ajustar sem mexer na lógica."""

# Teto de chamadas ao modelo por resposta (ModelCallLimitMiddleware). Evita ciclos de busca/ferramenta
# sem fim: ao atingir o teto, a execução termina com um aviso em vez de continuar.
# Atenção: cada rodada de tools (várias podem rodar em paralelo) + a resposta final contam como chamadas;
# um valor muito baixo corta pesquisas legítimas no meio.
MODEL_CALL_LIMIT = 10

# Teto de chamadas ao modelo de CADA tarefa delegada a um subagent (o MODEL_CALL_LIMIT acima só vale para o
# agente principal). Um pesquisador típico faz 1 rodada de buscas + a resposta; o resto é folga para refinar.
SUBAGENT_CALL_LIMIT = 6

# Subagents dinâmicos: quantos `task()` despachados de dentro do `eval` rodam ao mesmo tempo (o resto espera na fila).
# Cada subagent faz buscas pagas e chamadas ao modelo; um valor alto acelera, mas multiplica o custo e arrisca rate limit.
DYNAMIC_MAX_CONCURRENCY = 6
