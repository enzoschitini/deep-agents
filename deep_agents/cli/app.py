"""ChatCLI: orquestra o loop do chat, o histórico e a comunicação com o agente."""

from __future__ import annotations

from typing import Any

from rich.console import Console

from deep_agents.cli.banner import Banner
from deep_agents.cli.commands import Command, CommandRegistry
from deep_agents.cli.renderer import Renderer
from deep_agents.cli.theme import APP_NAME, APP_VERSION
from deep_agents.utils.json_manager import extract_response_text, manage_result_json


class ChatCLI:
    """Controla a sessão de chat. A aparência fica no `Renderer`/`Banner`, os comandos no
    `CommandRegistry`; aqui só vivem o loop, o histórico e as chamadas ao agente.

    Para trocar o agente em execução basta instanciar outro `ChatCLI`.
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
        self.agent_name = agent_name or getattr(gateway.config, "model_id", "agent")
        self.console = console or Console()
        self.banner = Banner(name, version, self.agent_name)
        self.view = Renderer(self.console, self.agent_name)
        self.commands = self._build_commands()
        self.messages: list = []
        self._running = False

    # ------------------------------------------------------------------ ciclo
    def run(self) -> None:
        self._running = True
        self.banner.render(self.console)
        while self._running:
            text = self._read_input()
            if text is None:
                break
            if not text:
                continue
            if self.commands.is_command(text):
                if not self.commands.dispatch(text):
                    self.view.unknown_command(text)
                continue
            self._send(text)
        self.view.goodbye()

    def _read_input(self) -> str | None:
        try:
            self.view.separator()
            return self.view.prompt().strip()
        except (EOFError, KeyboardInterrupt):
            return None

    def _send(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
        try:
            with self.view.status():
                result, report = self.gateway.run_agent(self.agent, {"messages": self.messages})
        except KeyboardInterrupt:
            self.messages.pop()
            self.view.notice("\nRisposta interrotta.")
            return
        except Exception as e:
            self.messages.pop()  # mantém o histórico consistente
            self.view.error(e)
            return

        # As mensagens retornadas já contêm todo o histórico + a nova resposta
        self.messages = result["messages"]
        manage_result_json(result)
        self.view.agent_message(extract_response_text(result))
        self.view.metrics(report)

    # --------------------------------------------------------------- comandos
    def _build_commands(self) -> CommandRegistry:
        registry = CommandRegistry()
        registry.register(Command("/aiuto", "mostra questo aiuto", self._cmd_help, ("/help",)))
        registry.register(Command("/pulisci", "cancella la conversazione e lo schermo", self._cmd_clear, ("/clear",)))
        registry.register(Command("/metriche", "totali accumulati della sessione", self._cmd_metrics, ("/metrics",)))
        registry.register(
            Command("/esci", "termina la chat (anche: /exit, /quit)", self._cmd_exit, ("/exit", "/quit", "exit", "quit"))
        )
        return registry

    def _cmd_help(self) -> None:
        self.view.commands_table(self.commands.listing())

    def _cmd_clear(self) -> None:
        self.messages = []
        self.console.clear()
        self.banner.render(self.console)
        self.view.notice("Cronologia cancellata.")

    def _cmd_metrics(self) -> None:
        self.view.totals_table(self.gateway.totals())

    def _cmd_exit(self) -> None:
        self._running = False
