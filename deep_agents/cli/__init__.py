"""CLI do Deep Agents.

Módulos (uma responsabilidade cada):
- theme.py     nome/versão e paleta de cores
- banner.py    banner ASCII-art
- renderer.py  tudo que é desenhado no terminal
- commands.py  registro e despacho dos comandos
- app.py       ChatCLI: loop, histórico e chamadas ao agente
- __main__.py  ponto de entrada (`python -m deep_agents.cli`)
"""

from deep_agents.cli.app import ChatCLI

__all__ = ["ChatCLI"]
