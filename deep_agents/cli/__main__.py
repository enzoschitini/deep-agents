import sys
from pathlib import Path

# Permite rodar direto (botão Play / `python arquivo.py`): coloca a raiz do repo no sys.path.
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from deep_agents.agent import agent, gateway  # noqa: E402
from deep_agents.cli import ChatCLI  # noqa: E402


def chat_loop() -> None:
    ChatCLI(agent, gateway).run()


# python -m deep_agents.cli
if __name__ == "__main__":
    chat_loop()
