"""Monta a toolkit do agente: escolhe as tools visíveis e entrega o canal lateral aos grupos."""
from typing import Callable

from deep_agents.toolkit.side_channel import SideChannel
from deep_agents.toolkit.tools.base import ToolGroup
from deep_agents.toolkit.tools.tavily import TavilyTools

# Grupos disponíveis. Um grupo novo (ex.: table.py) entra aqui.
DEFAULT_GROUPS: dict[str, type[ToolGroup]] = {"tavily": TavilyTools}

# Config padrão: {grupo: {"enabled": bool, "tools": [nomes] | None (= todas do grupo)}}
DEFAULT_CONFIG: dict[str, dict] = {"tavily": {"enabled": True, "tools": None}}


class ToolkitBuilder:
    def __init__(
        self,
        config: dict[str, dict] | None = None,
        channel: SideChannel | None = None,
        groups: dict[str, type[ToolGroup]] | None = None,
    ) -> None:
        self.config = DEFAULT_CONFIG if config is None else config
        self.channel = channel or SideChannel()
        self.groups = DEFAULT_GROUPS if groups is None else groups

    def tool_names(self) -> set[str]:
        """Nomes das tools habilitadas (a CLI usa para mostrar só o feedback das tools da toolkit)."""
        return {t.__name__ for t in self.build()}

    def build(self) -> list[Callable]:
        """Tools habilitadas, prontas para o `tools=` do agente. Nome inexistente na config é erro."""
        tools: list[Callable] = []
        for group_name, options in self.config.items():
            if group_name not in self.groups:
                raise ValueError(f"Grupo de tools desconhecido: {group_name!r} (disponíveis: {sorted(self.groups)})")
            if not options.get("enabled", True):
                continue
            available = self.groups[group_name](self.channel).tools()
            wanted = options.get("tools")
            if wanted is not None:
                unknown = [n for n in wanted if n not in available]
                if unknown:
                    raise ValueError(f"Tools desconhecidas em {group_name!r}: {unknown} (disponíveis: {sorted(available)})")
                available = {n: available[n] for n in wanted}
            tools.extend(available.values())
        return tools
