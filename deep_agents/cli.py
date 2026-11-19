import sys
from pathlib import Path

# Permite rodar direto (botão Play / `python arquivo.py`): coloca a raiz do repo no sys.path.
_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from typing import Any, Callable  # noqa: E402

from rich import box  # noqa: E402
from rich.align import Align  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markdown import Markdown  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.rule import Rule  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402

from deep_agents.agent import agent, gateway  # noqa: E402
from deep_agents.model.metrics import RunReport  # noqa: E402
from deep_agents.utils.json_manager import extract_response_text, manage_result_json  # noqa: E402

APP_NAME = "Deep Agents CLI"
APP_VERSION = "0.1.0"

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


def _big(word: str) -> list[str]:
    """Desenha uma palavra em letras grandes (6 linhas)."""
    return ["".join(_FONT[ch][row] for ch in word) for row in range(6)]


# Disposições do título, da mais larga para a mais estreita: a primeira que cabe no terminal.
_BANNER_LAYOUTS = [["DEEP AGENTS CLI"], ["DEEP", "AGENTS CLI"], ["DEEP", "AGENTS", "CLI"]]

# Degradê do banner (ciano -> azul -> violeta -> magenta), aplicado por coluna.
_GRADIENT = ["#00e5ff", "#00b8ff", "#3d8bff", "#7a6cff", "#a855f7", "#d946ef"]

# Cores semânticas da interface.
USER_COLOR = "#38bdf8"
AGENT_COLOR = "#c084fc"
MUTED = "grey50"
ERROR_COLOR = "#f87171"


class ChatCLI:
    """Controla toda a experiência de terminal: banner, entrada, mensagens, comandos e métricas.

    A classe só conhece o agente/gateway que recebe no construtor — para trocar o
    agente em execução basta instanciar outro `ChatCLI`.

    Comandi: /aiuto, /pulisci, /metriche, /esci (alias in inglese: /help, /clear, /metrics, /exit).
    O JSON completo do último turno é salvo em agent_result.json.
    """

    def __init__(
        self,
        agent: Any,
        gateway: Any,
        *,
        name: str = APP_NAME,
        version: str = APP_VERSION,
        agent_name: str | None = None,
        console: Console | None = None,
    ) -> None:
        self.agent = agent
        self.gateway = gateway
        self.name = name
        self.version = version
        self.agent_name = agent_name or getattr(gateway.config, "model_id", "agent")
        self.console = console or Console()
        self.messages: list = []
        self._running = False
        self._commands: dict[str, tuple[str, Callable[[], None]]] = {
            "/aiuto": ("mostra questo aiuto", self._cmd_help),
            "/pulisci": ("cancella la conversazione e lo schermo", self._cmd_clear),
            "/metriche": ("totali accumulati della sessione", self._cmd_metrics),
            "/esci": ("termina la chat (anche: /exit, /quit)", self._cmd_exit),
        }
        self._aliases = {
            "/help": "/aiuto", "/clear": "/pulisci", "/metrics": "/metriche",
            "/exit": "/esci", "/quit": "/esci", "exit": "/esci", "quit": "/esci",
        }

    # ------------------------------------------------------------------ ciclo
    def run(self) -> None:
        """Loop principal do chat."""
        self._running = True
        self.render_banner()
        while self._running:
            user_input = self._read_input()
            if user_input is None:
                break
            if not user_input:
                continue
            if self._handle_command(user_input):
                continue
            self._send(user_input)
        self.console.print(f"\n[{MUTED}]A presto! 👋[/]\n")

    def _send(self, user_input: str) -> None:
        self.messages.append({"role": "user", "content": user_input})
        try:
            with self.console.status(
                f"[{AGENT_COLOR}]{self.agent_name} sta pensando…[/]",
                spinner="dots",
                spinner_style=AGENT_COLOR,
            ):
                result, report = self.gateway.run_agent(self.agent, {"messages": self.messages})
        except KeyboardInterrupt:
            self.messages.pop()
            self.console.print(f"\n[{MUTED}]Risposta interrotta.[/]\n")
            return
        except Exception as e:
            self.messages.pop()  # mantém o histórico consistente
            self.render_error(e)
            return

        # As mensagens retornadas já contêm todo o histórico + a nova resposta
        self.messages = result["messages"]
        manage_result_json(result)
        self.render_agent_message(extract_response_text(result))
        self.render_metrics(report)

    # ---------------------------------------------------------------- entrada
    def _read_input(self) -> str | None:
        try:
            self.console.print(Rule(style=MUTED))
            text = self.console.input(f"[bold {USER_COLOR}]❯[/] ").strip()
            return text
        except (EOFError, KeyboardInterrupt):
            return None

    def _handle_command(self, text: str) -> bool:
        key = text.lower()
        key = self._aliases.get(key, key)
        if not key.startswith("/"):
            return False
        entry = self._commands.get(key)
        if entry is None:
            self.console.print(
                f"[{ERROR_COLOR}]Comando sconosciuto:[/] {text}  [{MUTED}](usa /aiuto)[/]\n"
            )
            return True
        entry[1]()
        return True

    # ---------------------------------------------------------------- comandos
    def _cmd_help(self) -> None:
        table = Table(box=None, show_header=False, padding=(0, 2))
        table.add_column(style=f"bold {USER_COLOR}")
        table.add_column(style=MUTED)
        for cmd, (desc, _) in self._commands.items():
            table.add_row(cmd, desc)
        self.console.print(Panel(table, title="Comandi", title_align="left", border_style=MUTED, box=box.ROUNDED))

    def _cmd_clear(self) -> None:
        self.messages = []
        self.console.clear()
        self.render_banner()
        self.console.print(f"[{MUTED}]Cronologia cancellata.[/]\n")

    def _cmd_metrics(self) -> None:
        totals = self.gateway.totals()
        table = Table(box=None, show_header=False, padding=(0, 2))
        table.add_column(style=MUTED)
        table.add_column(style="bold")
        for key, value in totals.items():
            if isinstance(value, float):
                value = f"{value:.4f}"
            table.add_row(str(key), str(value))
        self.console.print(Panel(table, title="Sessione", title_align="left", border_style=MUTED, box=box.ROUNDED))

    def _cmd_exit(self) -> None:
        self._running = False

    # --------------------------------------------------------------- renderização
    def render_banner(self) -> None:
        rows: list[str] = []
        for layout in _BANNER_LAYOUTS:
            rows = [line for word in layout for line in _big(word)]
            if max(len(r) for r in rows) <= self.console.width - 2:
                break
        else:
            rows = []  # nem a versão mais estreita cabe: usa um título simples

        if rows:
            width = max(len(r) for r in rows)
            art = Text(no_wrap=True)
            for i, line in enumerate(rows):
                for col, ch in enumerate(line):
                    color = _GRADIENT[min(col * len(_GRADIENT) // width, len(_GRADIENT) - 1)]
                    art.append(ch, style=f"bold {color}")
                if i < len(rows) - 1:
                    art.append("\n")
        else:
            art = Text(self.name.upper(), style=f"bold {_GRADIENT[2]}")

        info = Text(justify="center")
        info.append(self.name, style="bold white")
        info.append(f"  v{self.version}", style=MUTED)
        info.append("   •   ", style=MUTED)
        info.append("agente: ", style=MUTED)
        info.append(self.agent_name, style=f"bold {AGENT_COLOR}")

        hint = Text(
            "scrivi il tuo messaggio  •  /aiuto per i comandi  •  /esci per uscire",
            style=MUTED, justify="center",
        )
        self.console.print()
        self.console.print(Align.center(art))
        self.console.print()
        self.console.print(Align.center(info))
        self.console.print(Align.center(hint))
        self.console.print()

    def render_user_message(self, text: str) -> None:
        """Mostra un messaggio dell'utente (utile per rivedere la cronologia)."""
        self.console.print(
            Panel(Text(text), title=f"[bold {USER_COLOR}]Tu[/]", title_align="left",
                  border_style=USER_COLOR, box=box.ROUNDED, padding=(0, 1))
        )

    def render_agent_message(self, text: str) -> None:
        self.console.print()
        self.console.print(
            Panel(
                Markdown(text),
                title=f"[bold {AGENT_COLOR}]◆ {self.agent_name}[/]",
                title_align="left",
                border_style=AGENT_COLOR,
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    def render_metrics(self, report: RunReport) -> None:
        self.console.print(Text(f"  {format_metrics(report)}", style=MUTED))
        self.console.print()

    def render_error(self, error: Exception) -> None:
        self.console.print(
            Panel(Text(str(error)), title="errore", title_align="left", border_style=ERROR_COLOR, box=box.ROUNDED)
        )
        self.console.print()


def format_metrics(report: RunReport) -> str:
    """One compact line: always tokens in/out + time; extras only when relevant."""
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


def chat_loop() -> None:
    ChatCLI(agent, gateway).run()


# python -m deep_agents.cli
if __name__ == "__main__":
    chat_loop()
