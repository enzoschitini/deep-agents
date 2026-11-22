"""Configuração da memória: valores que você pode querer ajustar sem mexer na lógica."""

# Resumo do contexto (SummarizationMiddleware): dispara quando o contexto enviado ao modelo (system prompt +
# tools + conversa, ~4 mil tokens só de base) passa deste número de tokens; as mensagens antigas viram um resumo.
# É por TOKENS e não por nº de mensagens porque uma pesquisa na web enche o contexto de resultados e conta várias
# mensagens por rodada: com um teto de mensagens o resumo disparava no MEIO da pesquisa, custando uma chamada
# extra ao modelo (do tamanho de todo o contexto) e escondendo do agente os resultados que ele acabara de buscar.
# Como a CLI reenvia só o texto da conversa a cada turno (sem os resultados das buscas), este teto só é
# alcançado em conversas muito longas. Limitação: o agente é chamado sem checkpointer, então o resumo não
# persiste entre turnos; passado o teto, ele é refeito a cada pergunta. Se isso incomodar, comece uma sessão
# nova (/pulisci) ou suba o valor.
SUMMARY_TRIGGER_TOKENS = 30_000

# Teto de tokens do histórico antigo enviado ao modelo que resume. None = envia tudo (recomendado).
# Com um número (o padrão do SDK é 4000), o que passar do teto é CORTADO do começo e nunca entra no resumo:
# respostas grandes (como pesquisas na web) empurram para fora as primeiras mensagens, e fatos como o nome
# do usuário se perdem. Se o custo do resumo pesar, suba o teto em vez de usar um valor baixo.
TRIM_TOKENS_TO_SUMMARIZE: int | None = None

# Quantas mensagens mais recentes ficam intactas (sem resumir) depois que o resumo é feito.
KEEP_MESSAGES = 2
