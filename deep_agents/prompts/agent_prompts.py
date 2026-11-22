"""AgentPrompts: fachada única dos recursos de prompt do agente.

Esconde do agent.py onde ficam os arquivos e como são ligados ao Deep Agents:
  - system_prompt  → texto de system.py
  - memory_files   → caminhos virtuais dos .md de rules/ (parâmetro memory=)
  - backend        → monta a pasta prompts/ em /prompts/ (somente leitura)
  - permissions    → nega escrita do agente em /prompts/**
  - register_harness → registra o HarnessProfile do modelo
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.middleware.filesystem import FilesystemPermission

from deep_agents.prompts.harness_profile import HarnessProfiler
from deep_agents.prompts.system import SYSTEM_PROMPT

_PROMPTS_DIR = Path(__file__).resolve().parent


class AgentPrompts:
    MOUNT = "/prompts/"        # caminho virtual onde a pasta prompts/ aparece para o agente
    RULES_DIR = "rules"        # subpasta com os .md (ordem alfabética: 01_, 02_…)

    def __init__(self, root: Path = _PROMPTS_DIR) -> None:
        self.root = root

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    @property
    def memory_files(self) -> list[str]:
        """Caminhos virtuais dos arquivos de regras, na ordem em que são carregados."""
        rules = sorted((self.root / self.RULES_DIR).glob("*.md"))
        return [f"{self.MOUNT}{self.RULES_DIR}/{p.name}" for p in rules]

    @property
    def backend(self) -> CompositeBackend:
        return CompositeBackend(
            default=StateBackend(),
            routes={self.MOUNT: FilesystemBackend(root_dir=self.root, virtual_mode=True)},
        )

    @property
    def permissions(self) -> list[FilesystemPermission]:
        return [FilesystemPermission(operations=["write"], paths=[f"{self.MOUNT}**"], mode="deny")]

    @staticmethod
    def register_harness(spec: str) -> None:
        """Registra o perfil do harness para o modelo (rodar de novo a cada troca de modelo)."""
        HarnessProfiler.register(spec)
