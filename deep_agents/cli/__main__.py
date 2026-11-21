import sys
from pathlib import Path

# Permite rodar direto (botão Play / `python arquivo.py`): coloca a raiz do repo no sys.path.
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from deep_agents.agent import build_agent  # noqa: E402
from deep_agents.cli import ChatCLI  # noqa: E402
from deep_agents.model.model_config import ModelConfig  # noqa: E402

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


def chat_loop(model: ModelConfig = MODEL) -> None:
    agent, gateway = build_agent(model)
    ChatCLI(agent, gateway, agent_factory=build_agent).run()


# python -m deep_agents.cli
if __name__ == "__main__":
    chat_loop()
