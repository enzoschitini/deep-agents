import sys
from pathlib import Path

# Permite rodar direto (botão Play / `python arquivo.py`): coloca a raiz do repo no sys.path.
_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from typing import Any  # noqa: E402

from deepagents import create_deep_agent  # noqa: E402
from langchain.agents.middleware import ModelCallLimitMiddleware  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from langchain_quickjs import CodeInterpreterMiddleware  # noqa: E402
from deep_agents.config import DYNAMIC_MAX_CONCURRENCY, MODEL_CALL_LIMIT  # noqa: E402
from deep_agents.memory.build_memory import MemoryBuilder  # noqa: E402
from deep_agents.model.llm_gateway import LLMGateway  # noqa: E402
from deep_agents.model.model_config import ModelConfig  # noqa: E402
from deep_agents.prompts.agent_prompts import AgentPrompts  # noqa: E402
from deep_agents.subagents.build_subagents import SubagentBuilder  # noqa: E402
from deep_agents.toolkit.build_toolkit import ToolkitBuilder  # noqa: E402

# Load environment variables from a .env file
load_dotenv()


class AgentBuilder:
    """Monta o agente peça por peça: cada método `build_*` cuida de uma parte.

    - modelo  → LLMGateway (regras por provedor + métricas em gateway.history)
    - prompt  → AgentPrompts (system prompt, regras .md, backend, permissões, perfil do harness)
    - tools   → ferramentas do agente
    - subagents → SubagentBuilder (subagents que o principal chama com a tool `task`, cada um com suas tools)
    - memory  → MemoryBuilder (middleware de resumo do contexto; as sessões ficam por conta da CLI); também o teto de chamadas ao modelo
    `build()` junta tudo em `create_deep_agent`.
    """

    def __init__(
        self,
        config: ModelConfig,
        memory: MemoryBuilder | None = None,
        toolkit: ToolkitBuilder | None = None,
        subagents: SubagentBuilder | None = None,
        dynamic: dict[str, Any] | None = None,
    ) -> None:
        """`memory` e `toolkit` permitem à CLI compartilhar a mesma memória/sessão e o mesmo canal lateral
        entre as reconstruções do agente. `dynamic` liga os subagents dinâmicos: `{"enabled": bool, "max_concurrency": int}`
        (None/desligado = só a tool `task` normal)."""
        self.config = config
        self.dynamic = dynamic or {}
        self.gateway = LLMGateway(config)
        self.prompts = AgentPrompts()
        self.memory = memory or MemoryBuilder()
        self.toolkit = toolkit or ToolkitBuilder()
        self.subagents = subagents or SubagentBuilder()

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
        """Tools habilitadas pelo ToolkitBuilder (as tools publicam no canal lateral `self.toolkit.channel`)."""
        return self.toolkit.build()

    def build_subagents(self) -> list[dict[str, Any]]:
        """Subagents habilitados, cada um com as tools (grupos da toolkit, ex.: tavily) que declarou; as publicações vão ao mesmo canal lateral."""
        return self.subagents.build(self.build_model(), self.toolkit)

    def build_dynamic(self) -> list[Any]:
        """Subagents dinâmicos: o middleware que dá ao principal a tool `eval` (REPL JavaScript), de dentro da qual ele
        despacha os subagents registrados com `task()` em loops/`Promise.all`. Sem `ptc`: o código não enxerga as tools do agente."""
        if not self.dynamic.get("enabled", False):
            return []
        return [CodeInterpreterMiddleware(subagents=True, max_subagent_concurrency=self.dynamic.get("max_concurrency") or DYNAMIC_MAX_CONCURRENCY)]

    def build_memory(self) -> dict[str, Any]:
        """Argumentos de memória do `create_deep_agent`: o middleware que resume o contexto da conversa."""
        summarizer = self.memory.summarization(self.build_model(), self.prompts.backend)
        return {"middleware": [summarizer, ModelCallLimitMiddleware(run_limit=MODEL_CALL_LIMIT, exit_behavior="end")]}

    def build(self) -> tuple[Any, LLMGateway]:
        agent = create_deep_agent(
            model=self.build_model(),
            tools=self.build_tools(),
            subagents=self.build_subagents(),
            **self.build_prompt(),
            **self._with_dynamic(self.build_memory()),
        )
        return agent, self.gateway

    def _with_dynamic(self, memory_args: dict[str, Any]) -> dict[str, Any]:
        """Acrescenta o middleware dos subagents dinâmicos (se ligado) aos do `build_memory`."""
        return {**memory_args, "middleware": [*memory_args["middleware"], *self.build_dynamic()]}
