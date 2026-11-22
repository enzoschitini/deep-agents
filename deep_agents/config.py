"""Configuração do agente: valores que você pode querer ajustar sem mexer na lógica."""

# Teto de chamadas ao modelo por resposta (ModelCallLimitMiddleware). Evita ciclos de busca/ferramenta
# sem fim: ao atingir o teto, a execução termina com um aviso em vez de continuar.
# Atenção: cada rodada de tools (várias podem rodar em paralelo) + a resposta final contam como chamadas;
# um valor muito baixo corta pesquisas legítimas no meio.
MODEL_CALL_LIMIT = 10
