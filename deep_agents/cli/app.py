"""ChatCLI: orquestra o loop do chat, o histórico e a comunicação com o agente."""

from __future__ import annotations

from typing import Any, Callable

from rich.console import Console

from deep_agents.cli.banner import Banner
from deep_agents.cli.commands import Command, CommandRegistry
from deep_agents.cli.models import AVAILABLE_MODELS, resolve_choice
from deep_agents.cli.prompt import ChatPrompt, SlashCompleter
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
        agent_factory: Callable[[Any], tuple[Any, Any]] | None = None,
        models: list | None = None,
    ) -> None:
        """`agent_factory(model_config) -> (agent, gateway)` habilita o comando /modello."""
        self.agent = agent
        self.gateway = gateway
        self.agent_factory = agent_factory
        self.models = models if models is not None else AVAILABLE_MODELS
        self.agent_name = agent_name or getattr(gateway.config, "model_id", "agent")
        self.console = console or Console()
        self.banner = Banner(name, version, self.agent_name)
        self.view = Renderer(self.console, self.agent_name)
        self.commands = self._build_commands()
        self.prompt = ChatPrompt(
            self.console,
            SlashCompleter(self.commands.listing, lambda: [m.spec for m in self.models]),
        )
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
            return self.prompt.ask().strip()
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
        if self.agent_factory is not None:
            registry.register(Command("/modello", "scegli il modello (anche: /modello provider:modello)", self._cmd_model))
        return registry

    def _cmd_help(self, args: str = "") -> None:
        self.view.commands_table(self.commands.listing())

    def _cmd_clear(self, args: str = "") -> None:
        self.messages = []
        self.console.clear()
        self.banner.render(self.console)
        self.view.notice("Cronologia cancellata.")

    def _cmd_metrics(self, args: str = "") -> None:
        self.view.totals_table(self.gateway.totals())

    def _cmd_model(self, args: str = "") -> None:
        """`/modello` abre o menu; `/modello provider:modello` (ou número) troca direto."""
        current = self.gateway.config
        choice = args
        if not choice:
            choice = self._pick_model(current.spec)
        if not choice:
            self.view.notice("Nessuna modifica.")
            return
        new_config = resolve_choice(choice, self.models, current)
        if new_config is None:
            self.view.notice("Scelta non valida.")
            return
        if new_config.spec == current.spec:
            self.view.notice("È già il modello in uso.")
            return
        try:
            with self.view.status(f"carico {new_config.spec}…"):
                agent, gateway = self.agent_factory(new_config)
        except Exception as e:
            self.view.error(e)  # mantém o modelo anterior
            return
        self.agent, self.gateway = agent, gateway
        self.agent_name = new_config.model_id
        self.banner.agent_name = self.view.agent_name = self.agent_name
        self.view.notice(f"Modello impostato: {new_config.spec} (la conversazione continua)")

    def _pick_model(self, current_spec: str) -> str:
        """Pede o modelo ao usuário: seletor com setas (terminal) ou menu numerado (fallback)."""
        other = "Altro… (digita provider:modello)"
        try:
            if self.prompt.interactive:
                options = [m.spec for m in self.models] + [other]
                current = next((i for i, m in enumerate(self.models) if m.spec == current_spec), 0)
                picked = self.prompt.select(options, current, title="Scegli il modello")
                if picked is None:
                    return ""
                if picked < len(self.models):
                    return self.models[picked].spec
                return self.view.model_prompt().strip()  # "Altro…": texto livre
            self.view.model_menu(self.models, current_spec)
            return self.view.model_prompt().strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    def _cmd_exit(self, args: str = "") -> None:
        self._running = False
