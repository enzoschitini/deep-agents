"""Contrato dos grupos de tools: um arquivo em `toolkit/tools/` = um tema = uma subclasse de `ToolGroup`."""
from typing import Callable

from deep_agents.toolkit.side_channel import SideChannel


class ToolGroup:
    """Base de um grupo de tools. Cada tool devolve ao modelo (canal direto) e publica em `self.channel` (lateral)."""

    name: str = ""  # nome do grupo, usado na config e nas publicações

    def __init__(self, channel: SideChannel) -> None:
        self.channel = channel

    def tools(self) -> dict[str, Callable]:
        """nome da tool → função (com docstring e type hints: o Deep Agents infere o schema deles)."""
        raise NotImplementedError

    def publish(self, tool: str, kind: str, payload) -> None:
        self.channel.publish(self.name, tool, kind, payload)
