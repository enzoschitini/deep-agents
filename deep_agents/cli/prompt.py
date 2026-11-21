"""Entrada de texto com sugestões ao digitar "/" (comandos) e "/modello " (modelos)."""

from __future__ import annotations

import sys
from typing import Callable, Iterable

from rich.console import Console

from deep_agents.cli.theme import AGENT_COLOR, USER_COLOR

try:  # prompt_toolkit só funciona bem em terminal interativo
    from prompt_toolkit import Application, PromptSession
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.styles import Style
except ImportError:  # pragma: no cover
    PromptSession = None


class SlashCompleter:
    """Sugere comandos ao digitar "/" e os modelos disponíveis depois de "/modello "."""

    def __init__(
        self,
        commands: Callable[[], list[tuple[str, str]]],
        models: Callable[[], list[str]],
        model_command: str = "/modello",
    ) -> None:
        self._commands = commands
        self._models = models
        self._model_command = model_command

    def suggestions(self, text: str) -> list[tuple[str, str, int]]:
        """Devolve (texto_sugerido, descrição, posição_inicial_de_substituição)."""
        if not text.startswith("/"):
            return []
        head, space, tail = text.partition(" ")
        if not space:
            return [(n, d, 0) for n, d in self._commands() if n.startswith(head.lower())]
        if head.lower() == self._model_command:
            start = len(head) + 1
            return [(m, "", start) for m in self._models() if m.lower().startswith(tail.lower())]
        return []


if PromptSession is not None:

    class _PTCompleter(Completer):
        def __init__(self, inner: SlashCompleter) -> None:
            self.inner = inner

        def get_completions(self, document, complete_event) -> Iterable[Completion]:
            text = document.text_before_cursor
            for suggestion, meta, start in self.inner.suggestions(text):
                yield Completion(suggestion, start_position=start - len(text), display_meta=meta)


class ChatPrompt:
    """Lê a mensagem do usuário. Com terminal interativo mostra o menu de sugestões;
    caso contrário (pipe, teste) cai para o `console.input` simples."""

    def __init__(self, console: Console, completer: SlashCompleter) -> None:
        self.console = console
        self._session = None
        if PromptSession is not None and sys.stdin.isatty() and sys.stdout.isatty():
            self._session = PromptSession(
                completer=_PTCompleter(completer),
                complete_while_typing=True,
                style=Style.from_dict({
                    "prompt": f"bold {USER_COLOR}",
                    "completion-menu.completion": "bg:#1e1b2e #d8b4fe",
                    "completion-menu.completion.current": "bg:#7c3aed #ffffff",
                    "completion-menu.meta.completion": "bg:#1e1b2e #8b8b9b",
                    "completion-menu.meta.completion.current": "bg:#7c3aed #e9d5ff",
                }),
            )

    @property
    def interactive(self) -> bool:
        """True quando há terminal interativo (seletor com setas disponível)."""
        return self._session is not None

    def select(self, options: list[str], current: int = 0, title: str = "") -> int | None:
        """Lista navegável: ↑/↓ movem, Enter confirma, Esc/Ctrl+C cancelam (devolve None)."""
        index = [min(max(current, 0), len(options) - 1)]
        marked = current

        def render():
            lines = []
            if title:
                lines.append(("class:title", f"{title}\n"))
            for i, label in enumerate(options):
                selected = i == index[0]
                lines.append(("class:sel" if selected else "class:opt", f" {'❯' if selected else ' '} {label}"))
                if i == marked:
                    lines.append(("class:cur", "  ● attuale"))
                lines.append(("", "\n"))
            lines.append(("class:hint", " ↑/↓ naviga · invio conferma · esc annulla"))
            return lines

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _up(event):
            index[0] = (index[0] - 1) % len(options)

        @kb.add("down")
        @kb.add("j")
        def _down(event):
            index[0] = (index[0] + 1) % len(options)

        @kb.add("enter")
        def _enter(event):
            event.app.exit(result=index[0])

        @kb.add("escape", eager=True)
        @kb.add("c-c")
        @kb.add("q")
        def _cancel(event):
            event.app.exit(result=None)

        app = Application(
            layout=Layout(Window(FormattedTextControl(render), height=len(options) + (2 if title else 1))),
            key_bindings=kb,
            style=Style.from_dict({
                "title": f"bold {AGENT_COLOR}",
                "sel": f"bold {AGENT_COLOR}",
                "opt": "",
                "cur": "#8b8b9b",
                "hint": "#6b6b7b",
            }),
            erase_when_done=True,
        )
        return app.run()

    def ask(self) -> str:
        if self._session is not None:
            return self._session.prompt(HTML("<prompt>❯</prompt> "))
        return self.console.input(f"[bold {USER_COLOR}]❯[/] ")
