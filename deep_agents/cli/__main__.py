import sys
from pathlib import Path

# Permite rodar direto (botão Play / `python arquivo.py`): coloca a raiz do repo no sys.path.
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from deep_agents.agent import AgentBuilder  # noqa: E402
from rich.console import Console  # noqa: E402

from deep_agents.cli import ChatCLI  # noqa: E402
from deep_agents.cli.renderer import Renderer  # noqa: E402
from deep_agents.memory.build_memory import MemoryBuilder  # noqa: E402
from deep_agents.model.model_config import ModelConfig  # noqa: E402
from deep_agents.subagents.build_subagents import SubagentBuilder  # noqa: E402
from deep_agents.toolkit.build_toolkit import ToolkitBuilder  # noqa: E402
from deep_agents.toolkit.side_channel import SideChannel  # noqa: E402

# Modelo inicial da CLI, no formato "provider:modelo". Durante o chat, digite "/" para ver os
# comandos e "/modello " para escolher outro entre as sugestões.
#   openai:gpt-5.4 · openai:gpt-5-mini · anthropic:claude-sonnet-5-5 · google_genai:...
MODEL_SPEC = "openai:gpt-6.1-sol"

MODEL = ModelConfig.from_spec(
    MODEL_SPEC,
    temperature=None,   # None = padrão do modelo (ou 0.0–2.0). Na CLI: /temperatura
    thinking=None,      # None = padrão | "off" | "low" | "medium" | "high". Na CLI: /thinking
    timeout=120,
    max_retries=2,
    # max_tokens=..., extra={...}  # controles opcionais
)

# Toolkit: {grupo: {"enabled": bool, "tools": [nomes] | None (= todas do grupo)}}
TOOLKIT = {
    "tavily": {"enabled": True, "tools": None},
}

# Subagents que o agente principal pode chamar (tool `task`): {subagent: {"enabled": bool}}
SUBAGENTS = {
    "pesquisador": {"enabled": True},
    "redator": {"enabled": True},
}

# Subagents dinâmicos: o principal ganha a tool `eval` (REPL JavaScript) e despacha os subagents acima com `task()`
# em loops/Promise.all (lotes, votação, torneio). Só é usado quando o pedido contém "workflow" (ver rules/09_workflow.md).
# "max_concurrency": None = padrão de `config.DYNAMIC_MAX_CONCURRENCY`.
DYNAMIC_SUBAGENTS = {"enabled": True, "max_concurrency": None}


def chat_loop(model: ModelConfig = MODEL) -> None:
    memory = MemoryBuilder()  # sessão nova e vazia a cada execução; compartilhada com o agente (resumo de contexto) entre as reconstruções

    channel = SideChannel(session_provider=lambda: memory.session_id)  # canal lateral das tools (fontes etc.)
    toolkit = ToolkitBuilder(TOOLKIT, channel=channel)  # criado uma vez: sobrevive às reconstruções do agente

    subagents = SubagentBuilder(SUBAGENTS)

    def create_agent(config: ModelConfig):
        """Fábrica usada no início e a cada troca de modelo/temperatura/thinking (/modello…)."""
        return AgentBuilder(config, memory=memory, toolkit=toolkit, subagents=subagents, dynamic=DYNAMIC_SUBAGENTS).build()

    try:
        agent, gateway = create_agent(model)
    except Exception as e:
        Renderer(Console(), "startup").error(e, f"avvio: creazione dell'agente con {model.spec}")
        sys.exit(1)
    ChatCLI(agent, gateway, agent_factory=create_agent, memory=memory, toolkit=toolkit).run()


# python -m deep_agents.cli
if __name__ == "__main__":
    chat_loop()
