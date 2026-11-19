"""Registro de comandos (/aiuto, /esci, ...): nomes, aliases e despacho."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Command:
    name: str                              # ex.: "/aiuto"
    description: str
    handler: Callable[[], None]
    aliases: tuple[str, ...] = field(default_factory=tuple)


class CommandRegistry:
    """Guarda os comandos e resolve o texto digitado para o comando certo."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._lookup: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        self._commands[command.name] = command
        for key in (command.name, *command.aliases):
            self._lookup[key.lower()] = command

    def is_command(self, text: str) -> bool:
        """True se o texto começa com "/" ou é um alias exato (ex.: "exit")."""
        key = text.lower()
        return key.startswith("/") or key in self._lookup

    def dispatch(self, text: str) -> bool:
        """Executa o comando; devolve False se o texto não corresponde a nenhum."""
        command = self._lookup.get(text.lower())
        if command is None:
            return False
        command.handler()
        return True

    def listing(self) -> list[tuple[str, str]]:
        return [(c.name, c.description) for c in self._commands.values()]
