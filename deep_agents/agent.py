import sys
from pathlib import Path

# Permite rodar direto (botão Play / `python arquivo.py`): coloca a raiz do repo no sys.path.
_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from typing import Any  # noqa: E402

from deepagents import create_deep_agent  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from deep_agents.model.llm_gateway import LLMGateway  # noqa: E402
from deep_agents.model.model_config import ModelConfig  # noqa: E402
from deep_agents.prompts.agent_prompts import AgentPrompts  # noqa: E402

# Load environment variables from a .env file
load_dotenv()

# OpenAI's built-in web search — no extra install or API key needed
internet_search = {"type": "web_search"}

prompts = AgentPrompts()   # system prompt, regras (.md), backend, permissões e perfil do harness

def build_agent(config: ModelConfig) -> tuple[Any, LLMGateway]:
    """Create the agent for the given model.

    The gateway applies per-provider rules (renamed/dropped params) and collects
    per-call metrics (tokens, latency, tool runs) in gateway.history.
    """
    gateway = LLMGateway(config)
    prompts = AgentPrompts()   # system prompt, regras (.md), backend, permissões e perfil do harness
    
    prompts.register_harness(config.spec)   # perfil do harness para este modelo (também no /modello)
    agent = create_deep_agent(
        model=gateway.build(),
        tools=[internet_search],
        system_prompt=prompts.system_prompt,
        memory=prompts.memory_files,
        backend=prompts.backend,
        permissions=prompts.permissions,
    )
    return agent, gateway
