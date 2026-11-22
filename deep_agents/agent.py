import sys
from pathlib import Path

# Permite rodar direto (botão Play / `python arquivo.py`): coloca a raiz do repo no sys.path.
_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from typing import Any  # noqa: E402

from deepagents import create_deep_agent  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from deep_agents.memory.build_memory import MemoryBuilder  # noqa: E402
from deep_agents.model.llm_gateway import LLMGateway  # noqa: E402
from deep_agents.model.model_config import ModelConfig  # noqa: E402
from deep_agents.prompts.agent_prompts import AgentPrompts  # noqa: E402

# Load environment variables from a .env file
load_dotenv()

# OpenAI's built-in web search — no extra install or API key needed
internet_search = {"type": "web_search"}



class AgentBuilder:
    """Monta o agente peça por peça: cada método `build_*` cuida de uma parte.

    - modelo  → LLMGateway (regras por provedor + métricas em gateway.history)
    - prompt  → AgentPrompts (system prompt, regras .md, backend, permissões, perfil do harness)
    - tools   → ferramentas do agente
    - memory  → MemoryBuilder (middleware de resumo do contexto; as sessões ficam por conta da CLI)
    `build()` junta tudo em `create_deep_agent`.
    """

    def __init__(self, config: ModelConfig, memory: MemoryBuilder | None = None) -> None:
        """`memory` permite à CLI compartilhar a mesma memória/sessão entre as reconstruções do agente."""
        self.config = config
        self.gateway = LLMGateway(config)
        self.prompts = AgentPrompts()
        self.memory = memory or MemoryBuilder()

    def build_model(self) -> Any:
        """Modelo de chat criado pelo gateway (com as regras do provedor aplicadas)."""
        return self.gateway.build()

    def build_prompt(self) -> dict[str, Any]:
        """Argumentos de prompt do `create_deep_agent`; registra o perfil do harness do modelo."""
        self.prompts.register_harness(self.config.spec)   # também a cada troca de modelo (/modello)
        return {
            "system_prompt": self.prompts.system_prompt,
            "memory": self.prompts.memory_files,
            "skills": self.prompts.skills,
            "backend": self.prompts.backend,
            "permissions": self.prompts.permissions,
        }

    def build_tools(self) -> list[Any]:
        return [internet_search]

    def build_memory(self) -> dict[str, Any]:
        """Argumentos de memória do `create_deep_agent`: o middleware que resume o contexto da conversa."""
        summarizer = self.memory.summarization(self.build_model(), self.prompts.backend)
        return {"middleware": [summarizer]}

    def build(self) -> tuple[Any, LLMGateway]:
        agent = create_deep_agent(
            model=self.build_model(),
            tools=self.build_tools(),
            **self.build_prompt(),
            **self.build_memory(),
        )
        return agent, self.gateway
