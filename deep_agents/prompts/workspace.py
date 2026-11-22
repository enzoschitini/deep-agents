"""WorkspaceAccess: acesso do agente ao disco real, confinado à pasta do pacote `deep_agents/`.

Duas camadas de proteção (a doc recomenda as duas):
  1. backend   → `FilesystemBackend(virtual_mode=True)` montado em `/workspace/`: o agente só enxerga a
                 pasta do pacote; `..`, `~` e caminhos absolutos fora dela são bloqueados.
  2. permissões → `FilesystemPermission` (primeira regra que casa vale; sem match a operação é PERMITIDA,
                 por isso o `deny /**` final). Valem só para as tools de arquivo (ls, read_file, glob,
                 grep, write_file, edit_file, delete); não há tool de shell (`execute`) no agente.

Atenção: o glob do deepagents NÃO casa dotfiles com `**` (`/**` não cobre `/workspace/.env`), então os
dotfiles têm regras explícitas, antes de tudo.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission

_PACKAGE_DIR = Path(__file__).resolve().parents[1]   # .../deep_agents/

_RW = ["read", "write"]


class WorkspaceAccess:
    MOUNT = "/workspace/"                # caminho virtual da pasta do pacote
    # Caminhos internos do deepagents (resultados grandes, histórico) vivem no StateBackend e o agente
    # precisa lê-los; ficam fora do workspace mas liberados para leitura.
    INTERNAL_READ = ("/large_tool_results/**", "/conversation_history/**")
    # `/workspace/**` não casa a própria pasta (`/workspace`) nem a raiz: sem estas duas o `ls` de orientação
    # é negado e o agente conclui que não tem permissão. Os resultados do ls/glob/grep seguem filtrados
    # pelas regras, então listar `/` só mostra o que é permitido.
    LISTING_ONLY = ("/", MOUNT.rstrip("/"))
    # Segredos: negados em qualquer lugar, leitura e escrita. `.*` cobre .env, .git, .venv…
    SECRET_PATHS = ("/**/.*", "/**/.*/**", "/**/*.key", "/**/*.pem")
    # Somente leitura dentro do workspace: o código do próprio agente e o histórico das conversas.
    READ_ONLY_PATHS = ("/**/*.py", f"{MOUNT}memory/**")

    def __init__(self, root: Path = _PACKAGE_DIR) -> None:
        self.root = root

    @property
    def backend(self) -> FilesystemBackend:
        """Disco real sob `root`, com `virtual_mode=True` (sem isso `root_dir` não protege nada)."""
        return FilesystemBackend(root_dir=self.root, virtual_mode=True)

    def permissions(self, read_only_mounts: Sequence[str] = ()) -> list[FilesystemPermission]:
        """Regras na ordem de avaliação. `read_only_mounts` são montagens (ex.: `/prompts/`) só de leitura."""
        mounts = [f"{m.rstrip('/')}/**" for m in read_only_mounts]
        return [
            FilesystemPermission(operations=_RW, paths=list(self.SECRET_PATHS), mode="deny"),
            FilesystemPermission(operations=["write"], paths=[*mounts, *self.READ_ONLY_PATHS], mode="deny"),
            FilesystemPermission(operations=["read"], paths=[*mounts, *self.INTERNAL_READ, *self.LISTING_ONLY], mode="allow"),
            FilesystemPermission(operations=_RW, paths=[f"{self.MOUNT}**"], mode="allow"),
            FilesystemPermission(operations=_RW, paths=["/**"], mode="deny"),
        ]
