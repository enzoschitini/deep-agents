import sys
from pathlib import Path

# Permite rodar direto (botão Play / `python arquivo.py`): coloca a raiz do repo no sys.path.
_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from typing import Any  # noqa: E402

from deepagents import create_deep_agent  # noqa: E402
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend  # noqa: E402
from deepagents.middleware.filesystem import FilesystemPermission  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from deep_agents.model.llm_gateway import LLMGateway  # noqa: E402
from deep_agents.model.model_config import ModelConfig  # noqa: E402
from deep_agents.system_prompt.sys_prompt import SYSTEM_PROMPT  # noqa: E402

# Load environment variables from a .env file
load_dotenv()

# OpenAI's built-in web search — no extra install or API key needed
internet_search = {"type": "web_search"}

# Pasta com o AGENT.md, montada no caminho virtual /system_prompt/ (somente leitura para o agente).
_PROMPT_DIR = Path(__file__).resolve().parent / "system_prompt"
_MEMORY_FILES = ["/system_prompt/AGENT.md"]

def build_agent(config: ModelConfig) -> tuple[Any, LLMGateway]:
    """Create the agent for the given model.

    The gateway applies per-provider rules (renamed/dropped params) and collects
    per-call metrics (tokens, latency, tool runs) in gateway.history.
    """
    gateway = LLMGateway(config)
    agent = create_deep_agent(
        model=gateway.build(),
        tools=[internet_search],
        system_prompt=SYSTEM_PROMPT,
        memory=_MEMORY_FILES,
        backend=CompositeBackend(
            default=StateBackend(),
            routes={"/system_prompt/": FilesystemBackend(root_dir=_PROMPT_DIR, virtual_mode=True)},
        ),
        permissions=[FilesystemPermission(operations=["write"], paths=["/system_prompt/**"], mode="deny")],
    )
    return agent, gateway
