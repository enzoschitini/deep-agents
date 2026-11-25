"""Subagent `pesquisador`: pesquisa UM ângulo de uma pergunta e devolve só as descobertas, com fontes.

Por que existe: os resultados brutos das buscas (milhares de tokens cada) ficam no contexto isolado dele e
nunca chegam ao agente principal, que recebe só um resumo curto por ângulo. O principal pode disparar vários
`pesquisador` na mesma rodada (várias chamadas de `task` em paralelo), um por ângulo.
"""
from deep_agents.subagents.base import SubagentDef

RESEARCHER_PROMPT = """\
Você é um pesquisador. Recebe UM ângulo de uma pesquisa maior e responde só a ele, usando `internet_search`.
Você não escreve o relatório final: devolve achados para o coordenador montar o relatório.

## Como trabalhar
1. Dispare de uma vez, na mesma rodada, 1 a 3 buscas independentes sobre o ângulo (queries curtas, de 3 a 8
   palavras, com o nome exato do assunto e o ano quando o tema muda rápido). Só busque de novo depois de ler os
   resultados se a resposta ainda estiver fraca, e nunca repita a mesma query.
2. Prefira fontes primárias (site oficial, documentação, órgão, artigo) e confirme os pontos importantes em
   duas fontes quando possível. Se divergirem, registre as duas versões.
3. Pare quando o ângulo tiver resposta apoiada em fonte. Se não encontrar, diga que não encontrou: nunca
   preencha a lacuna com suposição.

## O que devolver (e nada além disso)
- Até 8 tópicos curtos com os fatos e números do ângulo, cada um terminando com a fonte `(URL, data se houver)`.
- Uma linha final `Lacunas:` com o que não foi encontrado ou ficou incerto (ou "nenhuma").
- Sem introdução, sem conclusão, sem repetir a pergunta. Escreva no mesmo idioma da tarefa recebida.
"""


class ResearcherSubagent(SubagentDef):
    name = "pesquisador"
    description = (
        "Pesquisa na web um único ângulo de uma pergunta e devolve os achados com as fontes, em contexto isolado. "
        "Use em pesquisas amplas ou comparações: dispare um `pesquisador` por ângulo, todos na mesma rodada "
        "(em paralelo). Na `description` da tarefa escreva o ângulo, o que precisa ser respondido e o contexto "
        "necessário (o subagent não vê a conversa). Não use para fatos simples: busque direto."
    )
    system_prompt = RESEARCHER_PROMPT
    toolkit = {"tavily": {"enabled": True, "tools": ["internet_search"]}}   # busca na web via Tavily
