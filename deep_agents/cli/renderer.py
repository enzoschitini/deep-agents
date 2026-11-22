"""Renderer: tudo o que é desenhado no terminal (mensagens, métricas, erros, tabelas)."""

from __future__ import annotations

import os
import re
import traceback
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from deep_agents.cli.theme import AGENT_COLOR, ERROR_COLOR, MUTED, USER_COLOR


_SKILL_PATH = re.compile(r"/skills/([^/\s'\"]+)/SKILL\.md")


def skills_used(report: Any) -> list[str]:
    """Nomes das skills que o agente leu no turno (read_file em .../skills/<nome>/SKILL.md), sem repetição."""
    names: list[str] = []
    for run in report.tool_runs:
        if run.get("name") != "read_file":
            continue
        match = _SKILL_PATH.search(run.get("input") or "")
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names


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


def _cause_chain(error: BaseException) -> list[BaseException]:
    """Exceções encadeadas (`raise ... from`/contexto implícito), da mais próxima à raiz."""
    chain: list[BaseException] = []
    seen = {id(error)}
    current = error.__cause__ or error.__context__
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def _origin(error: BaseException) -> str | None:
    """Último frame do código do projeto (deep_agents) no traceback; senão o último frame qualquer."""
    frames = traceback.extract_tb(error.__traceback__) if error.__traceback__ else []
    if not frames:
        return None
    own = [f for f in frames if "deep_agents" in Path(f.filename).parts]
    frame = (own or frames)[-1]
    try:
        shown = Path(frame.filename).resolve().relative_to(Path.cwd())
    except ValueError:
        shown = Path(frame.filename)
    return f"{shown}:{frame.lineno} in {frame.name}()"


def _hint(error: BaseException) -> str | None:
    """Dica para os erros mais comuns (chave de API, timeout, modelo inexistente, rede)."""
    names = " ".join(type(e).__name__ for e in [error, *_cause_chain(error)])
    text = " ".join(str(e) for e in [error, *_cause_chain(error)]).lower()
    if "AuthenticationError" in names or "api key" in text or "api_key" in text or "401" in text:
        return "Controlla la chiave API del provider (variabile d'ambiente / .env)."
    if "NotFoundError" in names or "model_not_found" in text or "does not exist" in text:
        return "Il modello potrebbe non esistere o non essere accessibile: cambia con /modello."
    if "RateLimitError" in names or "429" in text:
        return "Limite di richieste/quota raggiunto: riprova tra poco o cambia modello."
    if "Timeout" in names or "timed out" in text:
        return "Timeout: riprova, oppure aumenta `timeout` in ModelConfig."
    if "Connection" in names or "connect" in text:
        return "Problema di rete: controlla la connessione/proxy."
    return None


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

    def skills(self, names: list[str]) -> None:
        """Avisa quais skills o agente usou neste turno (nada é desenhado se não houve nenhuma)."""
        if not names:
            return
        self.console.print()
        for name in names:
            self.console.print(Text.assemble(("  ✦ skill in uso: ", f"bold {AGENT_COLOR}"), (name, "bold")))

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
    def error(self, error: BaseException, context: str | None = None) -> None:
        """Erro em destaque: onde aconteceu (context), tipo, mensagem, causas e ponto de origem no código.
        Com DEEP_AGENTS_DEBUG=1 mostra também o traceback completo."""
        body = Text()
        if context:
            body.append("Dove: ", style=f"bold {ERROR_COLOR}")
            body.append(f"{context}\n")
        body.append("Tipo: ", style=f"bold {ERROR_COLOR}")
        body.append(f"{type(error).__module__}.{type(error).__qualname__}\n")
        body.append("Messaggio: ", style=f"bold {ERROR_COLOR}")
        body.append(f"{str(error).strip() or '(nessun messaggio)'}\n")

        for cause in _cause_chain(error):
            body.append("Causa: ", style=f"bold {ERROR_COLOR}")
            body.append(f"{type(cause).__qualname__}: {str(cause).strip() or '(nessun messaggio)'}\n")

        origin = _origin(error)
        if origin:
            body.append("Origine: ", style=f"bold {ERROR_COLOR}")
            body.append(origin, style=MUTED)
            body.append("\n")

        hint = _hint(error)
        if hint:
            body.append("\nSuggerimento: ", style="bold yellow")
            body.append(hint)

        body.rstrip()
        self._panel(body, f"[bold {ERROR_COLOR}]✖ Errore[/]", ERROR_COLOR)
        if os.environ.get("DEEP_AGENTS_DEBUG"):
            self.console.print_exception(show_locals=False)
        else:
            self.console.print(f"  [{MUTED}]traceback completo: DEEP_AGENTS_DEBUG=1[/]")
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
