"""
Mini agente com Deep Agents que recebe um texto (ex.: comentário de cliente)
e devolve SEMPRE um JSON validado por um schema Pydantic.

No Deep Agents não existe um "Output Parser" como no LangChain clássico.
O equivalente é o parâmetro `response_format` do `create_deep_agent`:
o resultado validado aparece em result["structured_response"].

Requisitos:
    pip install -U deepagents "langchain[openai]"   # ou langchain[anthropic], etc.

Uso:
    export OPENAI_API_KEY="sk-..."
    export MODELO="openai:gpt-6.1-sol"   # opcional, formato provider:modelo
    python agente_sentimento.py "O app é ótimo, mas a entrega atrasou 5 dias."
"""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv
from typing import Literal

from deepagents import create_deep_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field

load_dotenv()  # lê .env se existir

# ---------------------------------------------------------------------------
# 1. Schema da saída (é ele que define o JSON)
# ---------------------------------------------------------------------------

Polaridade = Literal["positivo", "negativo", "neutro"]


class PontoLevantado(BaseModel):
    """Um ponto específico que a pessoa mencionou no texto."""

    ponto: str = Field(description="O ponto em poucas palavras, ex.: 'entrega atrasada'")
    aspecto: str = Field(
        description="Categoria do ponto, ex.: preço, entrega, atendimento, qualidade, usabilidade"
    )
    sentimento: Polaridade = Field(description="Sentimento da pessoa sobre ESTE ponto")
    trecho: str = Field(description="Trecho do texto original que sustenta o ponto")


class AnaliseComentario(BaseModel):
    """Análise estruturada de um comentário ou texto de opinião."""

    sentimento_geral: Literal["positivo", "negativo", "neutro", "misto"] = Field(
        description="Sentimento predominante do texto inteiro"
    )
    score_sentimento: float = Field(
        ge=-1, le=1, description="De -1 (muito negativo) a 1 (muito positivo)"
    )
    confianca: float = Field(ge=0, le=1, description="Confiança da classificação, de 0 a 1")
    emocoes: list[str] = Field(
        description="Emoções percebidas, ex.: alegria, frustração, raiva, surpresa"
    )
    intencao: Literal["elogio", "reclamacao", "duvida", "sugestao", "relato", "outro"] = Field(
        description="O que a pessoa quer com o comentário"
    )
    pontos_levantados: list[PontoLevantado] = Field(
        description="Todos os pontos que a pessoa levantou, um por item"
    )
    urgencia: Literal["baixa", "media", "alta"] = Field(
        description="Quão urgente é responder ou agir"
    )
    risco_churn: bool = Field(
        description="True se a pessoa ameaça cancelar, trocar de empresa ou não comprar de novo"
    )
    precisa_resposta: bool = Field(description="True se o comentário pede uma resposta da empresa")
    idioma: str = Field(description="Código do idioma do texto, ex.: pt, en, es, it")
    resumo: str = Field(description="Resumo do comentário em uma frase")
    sugestao_resposta: str | None = Field(
        default=None,
        description="Sugestão curta de resposta à pessoa, ou null se não precisar de resposta",
    )


# ---------------------------------------------------------------------------
# 2. Agente
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
Você é um analista de feedback de clientes.
Recebe um texto (comentário, review, mensagem) e o analisa.
Regras:
- Não invente informação que não está no texto.
- Liste cada ponto levantado separadamente, com o trecho que o comprova.
- Use "misto" quando houver pontos positivos e negativos relevantes.
- Responda os campos de texto no mesmo idioma do comentário.
Não use ferramentas de arquivos nem subagentes: só analise e devolva a resposta estruturada.
"""


def criar_agente(model=None):
    """Cria o deep agent. `model` pode ser string 'provider:modelo' ou um chat model."""
    return create_deep_agent(
        model=model or os.getenv("MODELO", "openai:gpt-6.1-sol"),
        system_prompt=SYSTEM_PROMPT,
        # ToolStrategy funciona com qualquer modelo que suporte tool calling e,
        # se o modelo errar o schema, devolve o erro de validação e ele tenta de novo.
        # Alternativa: response_format=AnaliseComentario (escolhe a estratégia sozinho)
        response_format=ToolStrategy(AnaliseComentario),
    )


def analisar(texto: str, agente=None) -> dict:
    """Analisa o texto e devolve um dict pronto para virar JSON."""
    agente = agente or criar_agente()
    resultado = agente.invoke(
        {"messages": [{"role": "user", "content": f"Analise este comentário:\n\n{texto}"}]}
    )
    analise = resultado.get("structured_response")
    if analise is None:
        raise RuntimeError("O modelo não devolveu a resposta estruturada (talvez tenha recusado).")
    return analise.model_dump()


if __name__ == "__main__":
    texto = " ".join(sys.argv[1:]) or (
        "Comprei o fone na Black Friday. O som é incrível e a bateria dura o dia todo, "
        "mas a entrega atrasou uma semana e o suporte nunca respondeu meu e-mail. "
        "Se acontecer de novo, não compro mais com vocês."
    )
    print(json.dumps(analisar(texto), ensure_ascii=False, indent=2))