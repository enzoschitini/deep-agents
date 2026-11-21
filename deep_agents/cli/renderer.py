"""Renderer: tudo o que é desenhado no terminal (mensagens, métricas, erros, tabelas)."""

from __future__ import annotations

from typing import Any

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from deep_agents.cli.theme import AGENT_COLOR, ERROR_COLOR, MUTED, USER_COLOR


def format_metrics(report: Any) -> str:
    """Uma linha compacta: sempre token in/out + tempo; extras só quando relevantes."""
    parts = [
        f"token in: {report.input_tokens}",
        f"out: {report.output_tokens}",
        f"tempo: {report.wall_time_s or 0:.1f}s",
    ]
    if report.n_calls > 1:
        parts.append(f"chiamate LLM: {report.n_calls}")
    if report.reasoning_tokens:
        parts.append(f"reasoning: {report.reasoning_tokens}")
    if report.cache_read_tokens:
        parts.append(f"cache: {report.cache_read_tokens}")
    if report.tool_runs:
        parts.append(f"strumenti: {len(report.tool_runs)}")
    if report.cost_usd is not None:
        parts.append(f"costo: ${report.cost_usd:.4f}")
    if report.n_errors:
        parts.append(f"errori: {report.n_errors}")
    return "[" + " | ".join(parts) + "]"


class Renderer:
    """Desenha os elementos da conversa. Não conhece agente nem histórico."""

    def __init__(self, console: Console, agent_name: str) -> None:
        self.console = console
        self.agent_name = agent_name

    # -- conversa
    def separator(self) -> None:
        self.console.print(Rule(style=MUTED))

    def user_message(self, text: str) -> None:
        """Mostra un messaggio dell'utente (utile per rivedere la cronologia)."""
        self._panel(Text(text), f"[bold {USER_COLOR}]Tu[/]", USER_COLOR)

    def agent_message(self, text: str) -> None:
        self.console.print()
        self._panel(Markdown(text), f"[bold {AGENT_COLOR}]◆ {self.agent_name}[/]", AGENT_COLOR, padding=(1, 2))

    def metrics(self, report: Any) -> None:
        self.console.print(Text(f"  {format_metrics(report)}", style=MUTED))
        self.console.print()

    def status(self, message: str | None = None):
        """Spinner de espera (context manager)."""
        return self.console.status(
            f"[{AGENT_COLOR}]{message or f'{self.agent_name} sta pensando…'}[/]",
            spinner="dots",
            spinner_style=AGENT_COLOR,
        )

    # -- avisos
    def error(self, error: Exception) -> None:
        self._panel(Text(str(error)), "errore", ERROR_COLOR)
        self.console.print()

    def notice(self, message: str) -> None:
        self.console.print(f"[{MUTED}]{message}[/]\n")

    def unknown_command(self, text: str) -> None:
        self.console.print(f"[{ERROR_COLOR}]Comando sconosciuto:[/] {text}  [{MUTED}](usa /aiuto)[/]\n")

    def goodbye(self) -> None:
        self.console.print(f"\n[{MUTED}]A presto! 👋[/]\n")

    # -- tabelas
    def commands_table(self, rows: list[tuple[str, str]]) -> None:
        table = Table(box=None, show_header=False, padding=(0, 2))
        table.add_column(style=f"bold {USER_COLOR}")
        table.add_column(style=MUTED)
        for name, description in rows:
            table.add_row(name, description)
        self._panel(table, "Comandi", MUTED)

    def totals_table(self, totals: dict[str, Any]) -> None:
        table = Table(box=None, show_header=False, padding=(0, 2))
        table.add_column(style=MUTED)
        table.add_column(style="bold")
        for key, value in totals.items():
            table.add_row(str(key), f"{value:.4f}" if isinstance(value, float) else str(value))
        self._panel(table, "Sessione", MUTED)

    def model_menu(self, models: list, current_spec: str) -> None:
        table = Table(box=None, show_header=False, padding=(0, 2))
        table.add_column(style=f"bold {USER_COLOR}", justify="right")
        table.add_column()
        table.add_column(style=AGENT_COLOR)
        for i, m in enumerate(models, start=1):
            is_current = m.spec == current_spec
            table.add_row(str(i), m.spec, "● attuale" if is_current else "")
        self._panel(table, "Scegli il modello", AGENT_COLOR)

    def model_prompt(self) -> str:
        return self.console.input(f"[{MUTED}]numero o provider:modello (invio per annullare)[/] [bold {USER_COLOR}]❯[/] ")

    # -- interno
    def _panel(self, content: Any, title: str, color: str, *, padding: tuple[int, int] = (0, 1)) -> None:
        self.console.print(
            Panel(content, title=title, title_align="left", border_style=color, box=box.ROUNDED, padding=padding)
        )
