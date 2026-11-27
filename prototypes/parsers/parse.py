"""
Mini agente com LangChain (`create_agent`) que recebe um texto (ex.: comentário
de cliente) e devolve um JSON validado por um schema Pydantic.

Com agentes não é preciso um "Output Parser" como nas chains clássicas.
O equivalente é o parâmetro `response_format` do `create_agent`:
o resultado validado aparece em result["structured_response"].

Requisitos:
    pip install -U "langchain[openai]" python-dotenv   # ou langchain[anthropic], etc.

Uso:
    # OPENAI_API_KEY no .env da raiz; o modelo é definido em Parser.__init__
    python prototypes/parsers/parse_comments.py "O app é ótimo, mas a entrega atrasou 5 dias."
"""

from __future__ import annotations

from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy

from deep_agents.model.llm_gateway import LLMGateway  # noqa: E402
from deep_agents.model.model_config import ModelConfig  # noqa: E402

from prototypes.parsers.schema import AnaliseComentario
from prototypes.parsers.config import (
    SYSTEM_PROMPT,
    PROVIDER,
    LLM_MODEL,
    MAX_TOKENS
)

load_dotenv()

class Parser:
    def __init__(self):
        # Default
        self.llm_model_config = ModelConfig(
            provider=PROVIDER,
            model_id=LLM_MODEL,
            max_tokens=MAX_TOKENS,
        )

    def create_agent(
        self,
        llm_model_config: ModelConfig | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        response_format: ToolStrategy = ToolStrategy(AnaliseComentario),
    ):
        gateway = LLMGateway(llm_model_config or self.llm_model_config)
        return create_agent(
            model=gateway.build(),
            system_prompt=system_prompt,
            response_format=response_format,
        )

    def parse(self, text: str, agent=None) -> AnaliseComentario:
        agent = agent or self.create_agent()
        resultado = agent.invoke(
            {"messages": [{"role": "user", "content": f"Analise este comentário:\n\n{text}"}]}
        )
        analise = resultado.get("structured_response")
        if analise is None:
            raise RuntimeError("O modelo não devolveu a resposta estruturada (talvez tenha recusado).")
        return AnaliseComentario.model_validate(analise)
