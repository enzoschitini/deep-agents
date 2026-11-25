"""Monta os subagents do agente: escolhe os habilitados e monta para cada um as tools (grupos da toolkit) que ele declarou."""
from typing import Any

from deep_agents.subagents.base import SubagentDef
from deep_agents.subagents.agents.researcher import ResearcherSubagent
from deep_agents.subagents.agents.writer import WriterSubagent
from deep_agents.toolkit.build_toolkit import ToolkitBuilder

# Subagents disponíveis (nome → classe). Um novo (ex.: agents/verificador.py) entra aqui.
DEFAULT_SUBAGENTS: dict[str, type[SubagentDef]] = {
    ResearcherSubagent.name: ResearcherSubagent,
    WriterSubagent.name: WriterSubagent,
}

# Config padrão: {subagent: {"enabled": bool}}
DEFAULT_CONFIG: dict[str, dict] = {ResearcherSubagent.name: {"enabled": True}, WriterSubagent.name: {"enabled": True}}


class SubagentBuilder:
    def __init__(
        self,
        config: dict[str, dict] | None = None,
        subagents: dict[str, type[SubagentDef]] | None = None,
    ) -> None:
        self.config = DEFAULT_CONFIG if config is None else config
        self.subagents = DEFAULT_SUBAGENTS if subagents is None else subagents

    def names(self) -> set[str]:
        """Nomes dos subagents habilitados."""
        return set(self._enabled())

    def build(self, model: Any, toolkit: ToolkitBuilder) -> list[dict[str, Any]]:
        """Specs prontos para o `subagents=` do agente. `model` é o do gateway. Cada subagent monta as tools que
        declarou (`SubagentDef.toolkit`) com os grupos e o canal lateral do `toolkit` recebido, então as fontes
        das buscas dele aparecem no painel `Fonti`. Subagent, grupo ou tool desconhecidos são erro."""
        specs = []
        for name in self._enabled():
            definition = self.subagents[name]()
            tools = ToolkitBuilder(definition.toolkit, channel=toolkit.channel, groups=toolkit.groups).build()
            specs.append(definition.spec(model, tools))
        return specs

    def _enabled(self) -> list[str]:
        enabled = []
        for name, options in self.config.items():
            if name not in self.subagents:
                raise ValueError(f"Subagent desconhecido: {name!r} (disponíveis: {sorted(self.subagents)})")
            if options.get("enabled", True):
                enabled.append(name)
        return enabled
