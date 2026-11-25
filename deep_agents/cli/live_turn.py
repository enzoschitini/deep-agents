"""LiveTurn: desenha ao vivo UM turno do agente a partir do fluxo de `StreamEvent`.

Só o `Renderer` o instancia (`Renderer.live_turn`). Fluxo: enquanto o agente pensa/age há um status com o label
do último START; cada ação PRIMARY concluída vira uma linha persistente (indentada pela árvore pai/filho); a
resposta do principal aparece em streaming num painel (`rich.live.Live` + Markdown); o texto intermediário
(`final=False`) vira texto esmaecido; no RUN END o painel fecha SEM reimprimir a resposta e saem fontes e métricas.
Erros (RUN ERROR) não são desenhados aqui: quem chama usa `view.error(e, contexto)`."""

from __future__ import annotations

from typing import Any

from rich.live import Live
from rich.markup import escape
from rich.text import Text

from deep_agents.cli.theme import AGENT_COLOR, ERROR_COLOR, MUTED
from deep_agents.streaming.events import EventKind, Phase, StreamEvent, Visibility

# Verbosidade (/dettagli): até que visibilidade os eventos aparecem.
VERBOSITY_LEVELS: dict[str, Visibility] = {
    "off": Visibility.PRIMARY,
    "on": Visibility.SECONDARY,
    "debug": Visibility.DEBUG,
}

_TREE_KINDS = {EventKind.SUBAGENT, EventKind.SUBAGENT_DYNAMIC}   # abrem um ramo: linha já no START
_ACTION_KINDS = {
    EventKind.TOOL, EventKind.SUBAGENT, EventKind.SUBAGENT_DYNAMIC, EventKind.SKILL, EventKind.TODOS, EventKind.ASYNC_TASK,
}
_TASK_CHARS = 110


def _clip(text: Any, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class LiveTurn:
    """Context manager: `with view.live_turn(verbosity) as live: for ev in handle: live.handle(ev)`."""

    def __init__(self, view: Any, verbosity: str = "off") -> None:
        self.view = view
        self.console = view.console
        self.limit = VERBOSITY_LEVELS.get(verbosity, Visibility.PRIMARY)
        self.metrics_printed = False         # True se o RUN END trouxe a linha de métricas e ela já foi desenhada
        self._status: Any = None
        self._live: Live | None = None
        self._text = ""                      # texto da mensagem em curso (principal)
        self._levels: dict[str, int] = {}    # id do item -> nível de indentação
        self._sources: list[dict] = []
        self._final_shown = False            # a resposta final já foi desenhada pelo painel

    # -- context manager
    def __enter__(self) -> "LiveTurn":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Encerra status e painel (também em Ctrl+C/erro), deixando o que já foi escrito no terminal."""
        self._stop_status()
        self._stop_live()

    # -- entrada
    def handle(self, ev: StreamEvent) -> None:
        if ev.kind == EventKind.RUN:
            self._on_run(ev)
        elif ev.kind == EventKind.RESPONSE:
            self._on_response(ev)
        elif ev.kind == EventKind.SOURCES:
            self._sources = list(ev.data.get("sources") or [])
        elif ev.visibility <= self.limit or ev.phase == Phase.ERROR:
            self._on_action(ev)

    # -- RUN
    def _on_run(self, ev: StreamEvent) -> None:
        if ev.phase == Phase.START:
            self._set_status()
        elif ev.phase == Phase.END:
            self._finish(ev)
        else:   # ERROR / CANCELLED: nada a desenhar (o chamador mostra o erro ou o aviso)
            self.close()

    def _finish(self, ev: StreamEvent) -> None:
        answer = str(ev.data.get("answer") or "")
        self._stop_status()
        if self._live is not None:   # a resposta verdadeira (answer) prevalece sobre os deltas provisórios
            self._live.update(self.view.agent_panel(answer or self._text))
            self._stop_live()
            self._final_shown = True
        elif answer and not self._final_shown:   # resposta sem deltas (ex.: fim por limite de chamadas)
            self.view.agent_message(answer)
        if self._sources:
            self.view.sources(self._sources)
        metrics = ev.data.get("metrics")
        if isinstance(metrics, str) and metrics:
            self.view.metrics_line(metrics)
            self.metrics_printed = True

    # -- RESPONSE
    def _on_response(self, ev: StreamEvent) -> None:
        if ev.agent != "main":
            return   # tokens de subagents (só DEBUG) não entram na resposta
        if ev.phase == Phase.DELTA:
            self._text += str(ev.data.get("text") or "")
            if self._live is None:
                self._stop_status()
                self.console.print()
                self._live = Live(
                    self.view.agent_panel(self._text), console=self.console, refresh_per_second=8,
                    vertical_overflow="visible",
                )
                self._live.start()
            else:
                self._live.update(self.view.agent_panel(self._text))
        elif ev.phase == Phase.END:
            text = str(ev.data.get("text") or self._text)
            if ev.data.get("final", True):
                if self._live is not None:
                    self._live.update(self.view.agent_panel(text))   # fecha no RUN END (answer pode corrigir)
                self._text = text
            else:   # "pensiero": texto intermediário antes de chamar tools
                if self._live is not None:
                    self._live.update(Text(text, style="dim"))
                    self._stop_live()
                elif text.strip():
                    self.console.print(Text(text, style="dim"))
                self._text = ""
                self._set_status()

    # -- ações
    def _on_action(self, ev: StreamEvent) -> None:
        level = self._level(ev)
        if ev.phase == Phase.START:
            if ev.kind in _TREE_KINDS and ev.visibility <= Visibility.PRIMARY:
                self._print(self._start_line(ev), level)
            self._set_status(ev.label or None)
        elif ev.phase in {Phase.END, Phase.ERROR, Phase.INFO}:
            line = self._action_line(ev) if ev.kind in _ACTION_KINDS else self._generic_line(ev)
            self._print(line, level)
            if self._live is None:
                self._set_status()
        elif ev.kind == EventKind.REASONING and self._live is None:
            self._set_status("Ragiono…")

    def _level(self, ev: StreamEvent) -> int:
        """Indentação: um nível abaixo do pai (quando conhecido); senão a profundidade do namespace."""
        if ev.id in self._levels:
            return self._levels[ev.id]
        level = self._levels[ev.parent_id] + 1 if ev.parent_id in self._levels else ev.depth
        self._levels[ev.id] = level
        return level

    def _print(self, line: Text, level: int) -> None:
        self.console.print(Text("  " + "    " * level).append_text(line))

    # -- linhas
    @staticmethod
    def _duration(ev: StreamEvent) -> str:
        return f"  ({ev.duration_s:.1f}s)" if ev.duration_s is not None else ""

    @staticmethod
    def _task(ev: StreamEvent) -> str:
        task = _clip((ev.args or {}).get("description") or ev.data.get("description") or ev.data.get("label"), _TASK_CHARS)
        return f"  «{task}»" if task else ""

    def _start_line(self, ev: StreamEvent) -> Text:
        name = ev.name or "?"
        if ev.kind == EventKind.SUBAGENT_DYNAMIC:
            return Text.assemble(
                ("▶ subagent dinamico: ", f"bold {AGENT_COLOR}"), (name, "bold"), (self._task(ev), MUTED),
            )
        return Text.assemble(("◈ subagent: ", f"bold {AGENT_COLOR}"), (name, "bold"), (self._task(ev), MUTED))

    def _action_line(self, ev: StreamEvent) -> Text:
        name = ev.name or "?"
        failed = ev.phase == Phase.ERROR
        err = Text(f"  ✖ {_clip(ev.error, 160)}", style=f"bold {ERROR_COLOR}") if failed and ev.error else Text()
        if ev.kind == EventKind.SUBAGENT:
            if failed:
                head = Text.assemble(("✖ subagent: ", f"bold {ERROR_COLOR}"), (name, "bold"))
            else:
                head = Text.assemble(("✔ subagent: ", f"bold {AGENT_COLOR}"), (name, "bold"))
            return head.append(self._duration(ev), style=MUTED).append_text(err)
        if ev.kind == EventKind.SUBAGENT_DYNAMIC:
            if failed:
                head = Text.assemble(("✖ subagent dinamico in errore: ", f"bold {ERROR_COLOR}"), (name, "bold"))
            else:
                head = Text.assemble(("✔ subagent dinamico completato: ", f"bold {AGENT_COLOR}"), (name, "bold"))
            return head.append(self._duration(ev), style=MUTED).append_text(err)
        if ev.kind == EventKind.SKILL:
            skill = ev.data.get("skill") or name
            return Text.assemble(("✦ skill in uso: ", f"bold {AGENT_COLOR}"), (str(skill), "bold")).append_text(err)
        if ev.kind == EventKind.TODOS:
            progress = f" ({ev.data['done']}/{ev.data['total']})" if "done" in ev.data and "total" in ev.data else ""
            return Text.assemble(("☑ piano aggiornato", f"bold {AGENT_COLOR}"), (progress, MUTED)).append_text(err)
        if ev.kind == EventKind.ASYNC_TASK:
            action = ev.data.get("action") or ""
            head = Text.assemble(("⇄ subagent asincrono: ", f"bold {AGENT_COLOR}"), (f"{name} {action}".strip(), "bold"))
            return head.append(self._duration(ev), style=MUTED).append_text(err)
        # TOOL
        head = Text.assemble(
            ("✖ strumento: " if failed else "⚙ strumento in uso: ", f"bold {ERROR_COLOR if failed else AGENT_COLOR}"),
            (name, "bold"),
        )
        query = (ev.args or {}).get("query")
        if query:
            head.append(f"  «{_clip(query, 90)}»", style=MUTED)
        return head.append(self._duration(ev), style=MUTED).append_text(err)

    def _generic_line(self, ev: StreamEvent) -> Text:
        """Linha esmaecida dos eventos SECONDARY/DEBUG (modo /dettagli on|debug)."""
        label = ev.label or ev.name or ev.kind.value
        style = f"bold {ERROR_COLOR}" if ev.phase == Phase.ERROR else MUTED
        line = Text(f"· {_clip(label, 120)}", style=style).append(self._duration(ev), style=MUTED)
        if ev.phase == Phase.ERROR and ev.error:
            line.append(f"  ✖ {_clip(ev.error, 160)}", style=style)
        return line

    # -- status / live
    def _set_status(self, label: str | None = None) -> None:
        if self._live is not None:
            return
        message = f"[{AGENT_COLOR}]{escape(_clip(label, 100)) if label else f'{self.view.agent_name} sta pensando…'}[/]"
        if self._status is None:
            self._status = self.view.status(None)
            self._status.update(message)
            self._status.start()
        else:
            self._status.update(message)

    def _stop_status(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

    def _stop_live(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
