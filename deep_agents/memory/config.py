"""Configuração da memória: valores que você pode querer ajustar sem mexer na lógica."""

# Resumo do contexto (SummarizationMiddleware): quando a conversa passa deste número de interações
# (uma interação = pergunta + resposta = 2 mensagens), as mensagens antigas viram um resumo.
SUMMARY_EVERY_INTERACTIONS = 5

# Teto de tokens do histórico antigo enviado ao modelo que resume. None = envia tudo (recomendado).
# Com um número (o padrão do SDK é 4000), o que passar do teto é CORTADO do começo e nunca entra no resumo:
# respostas grandes (como pesquisas na web) empurram para fora as primeiras mensagens, e fatos como o nome
# do usuário se perdem. Se o custo do resumo pesar, suba o teto em vez de usar um valor baixo.
TRIM_TOKENS_TO_SUMMARIZE: int | None = None

# Quantas mensagens mais recentes ficam intactas (sem resumir) depois que o resumo é feito.
KEEP_MESSAGES = 2
