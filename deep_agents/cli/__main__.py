import sys
from pathlib import Path

# Permite rodar direto (botão Play / `python arquivo.py`): coloca a raiz do repo no sys.path.
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from rich.console import Console  # noqa: E402

from deep_agents.bootstrap import MODEL, build_backend  # noqa: E402
from deep_agents.cli import ChatCLI  # noqa: E402
from deep_agents.cli.renderer import Renderer  # noqa: E402
from deep_agents.model.model_config import ModelConfig  # noqa: E402
from deep_agents.streaming import StreamOptions  # noqa: E402

try:   # `STREAMING` vem de bootstrap.py (pacote E); até lá, opções padrão
    from deep_agents.bootstrap import STREAMING  # noqa: E402
except ImportError:
    STREAMING = StreamOptions()

# Modelo, toolkit, subagents e subagents dinâmicos são configurados em `deep_agents/bootstrap.py`
# (compartilhado com o servidor web: `python -m deep_agents.server`).


def chat_loop(model: ModelConfig = MODEL) -> None:
    try:
        backend = build_backend(model)
    except Exception as e:
        Renderer(Console(), "startup").error(e, f"avvio: creazione dell'agente con {model.spec}")
        sys.exit(1)
    ChatCLI(
        backend.agent, backend.gateway, agent_factory=backend.create_agent, memory=backend.memory, toolkit=backend.toolkit,
        stream_options=STREAMING, tracer=backend.tracer,
    ).run()


# python -m deep_agents.cli
if __name__ == "__main__":
    chat_loop()
