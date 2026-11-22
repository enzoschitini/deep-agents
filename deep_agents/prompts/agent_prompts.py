"""AgentPrompts: fachada única dos recursos de prompt do agente.

Esconde do agent.py onde ficam os arquivos e como são ligados ao Deep Agents:
  - system_prompt  → texto de system.py
  - memory_files   → caminhos virtuais dos .md de rules/ (parâmetro memory=)
  - skills         → pasta skills/ (parâmetro skills=; o agente lê o SKILL.md sob demanda)
  - backend        → monta prompts/ em /prompts/ e a pasta do pacote em /workspace/ (WorkspaceAccess)
  - permissions    → /prompts/ só leitura, /workspace/ leitura+escrita, o resto negado (ver workspace.py)
  - register_harness → registra o HarnessProfile do modelo
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.middleware.filesystem import FilesystemPermission

from deep_agents.prompts.harness_profile import HarnessProfiler
from deep_agents.prompts.system import SYSTEM_PROMPT
from deep_agents.prompts.workspace import WorkspaceAccess

_PROMPTS_DIR = Path(__file__).resolve().parent


class AgentPrompts:
    MOUNT = "/prompts/"        # caminho virtual onde a pasta prompts/ aparece para o agente
    RULES_DIR = "rules"        # subpasta com os .md (ordem alfabética: 01_, 02_…)
    SKILLS_DIR = "skills"      # subpasta com uma pasta por skill (<nome>/SKILL.md)

    def __init__(self, root: Path = _PROMPTS_DIR, workspace: WorkspaceAccess | None = None) -> None:
        self.root = root
        self.workspace = workspace or WorkspaceAccess()

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    @property
    def memory_files(self) -> list[str]:
        """Caminhos virtuais dos arquivos de regras, na ordem em que são carregados."""
        rules = sorted((self.root / self.RULES_DIR).glob("*.md"))
        return [f"{self.MOUNT}{self.RULES_DIR}/{p.name}" for p in rules]

    @property
    def skills(self) -> list[str]:
        """Pastas-fonte de skills (cada subpasta com um SKILL.md), no caminho virtual."""
        return [f"{self.MOUNT}{self.SKILLS_DIR}/"]

    @property
    def backend(self) -> CompositeBackend:
        return CompositeBackend(
            default=StateBackend(),
            routes={
                self.MOUNT: FilesystemBackend(root_dir=self.root, virtual_mode=True),
                self.workspace.MOUNT: self.workspace.backend,
            },
        )

    @property
    def permissions(self) -> list[FilesystemPermission]:
        """/prompts/ só leitura; /workspace/ (pasta do pacote) leitura e escrita; o resto negado."""
        return self.workspace.permissions(read_only_mounts=[self.MOUNT])

    @staticmethod
    def register_harness(spec: str) -> None:
        """Registra o perfil do harness para o modelo (rodar de novo a cada troca de modelo)."""
        HarnessProfiler.register(spec)
