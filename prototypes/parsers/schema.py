from typing import Literal
from pydantic import BaseModel, Field

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
