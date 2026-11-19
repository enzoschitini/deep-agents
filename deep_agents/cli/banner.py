"""Banner ASCII-art colorido, adaptável à largura do terminal."""

from __future__ import annotations

from rich.align import Align
from rich.console import Console
from rich.text import Text

from deep_agents.cli.theme import AGENT_COLOR, GRADIENT, MUTED

# Alfabeto ASCII-art (fonte "ANSI Shadow"): cada letra tem 6 linhas.
_FONT = {
    "D": ["██████╗ ", "██╔══██╗", "██║  ██║", "██║  ██║", "██████╔╝", "╚═════╝ "],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "P": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔═══╝ ", "██║     ", "╚═╝     "],
    "A": [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "G": [" ██████╗ ", "██╔════╝ ", "██║  ███╗", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "N": ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "S": ["███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"],
    "C": [" ██████╗", "██╔════╝", "██║     ", "██║     ", "╚██████╗", " ╚═════╝"],
    "L": ["██╗     ", "██║     ", "██║     ", "██║     ", "███████╗", "╚══════╝"],
    "I": ["██╗", "██║", "██║", "██║", "██║", "╚═╝"],
    " ": ["    "] * 6,
}

# Disposições do título, da mais larga para a mais estreita: a primeira que cabe no terminal.
_LAYOUTS = [["DEEP AGENTS CLI"], ["DEEP", "AGENTS CLI"], ["DEEP", "AGENTS", "CLI"]]


def _big(word: str) -> list[str]:
    """Desenha uma palavra em letras grandes (6 linhas)."""
    return ["".join(_FONT[ch][row] for ch in word) for row in range(6)]


class Banner:
    """Desenha o título grande, a versão, o agente em execução e a dica de uso."""

    def __init__(self, name: str, version: str, agent_name: str) -> None:
        self.name = name
        self.version = version
        self.agent_name = agent_name

    def render(self, console: Console) -> None:
        console.print()
        console.print(Align.center(self._title(console.width)))
        console.print()
        console.print(Align.center(self._info()))
        console.print(Align.center(self._hint()))
        console.print()

    def _title(self, width: int) -> Text:
        for layout in _LAYOUTS:
            rows = [line for word in layout for line in _big(word)]
            if max(len(r) for r in rows) <= width - 2:
                return self._gradient(rows)
        # Nem a versão mais estreita cabe: título simples.
        return Text(self.name.upper(), style=f"bold {GRADIENT[2]}")

    @staticmethod
    def _gradient(rows: list[str]) -> Text:
        width = max(len(r) for r in rows)
        art = Text(no_wrap=True)
        for i, line in enumerate(rows):
            for col, ch in enumerate(line):
                color = GRADIENT[min(col * len(GRADIENT) // width, len(GRADIENT) - 1)]
                art.append(ch, style=f"bold {color}")
            if i < len(rows) - 1:
                art.append("\n")
        return art

    def _info(self) -> Text:
        info = Text(justify="center")
        info.append(self.name, style="bold white")
        info.append(f"  v{self.version}", style=MUTED)
        info.append("   •   ", style=MUTED)
        info.append("agente: ", style=MUTED)
        info.append(self.agent_name, style=f"bold {AGENT_COLOR}")
        return info

    @staticmethod
    def _hint() -> Text:
        return Text(
            "scrivi il tuo messaggio  •  /aiuto per i comandi  •  /esci per uscire",
            style=MUTED,
            justify="center",
        )
