"""ChatCLI: orquestra o loop do chat, o histórico e a comunicação com o agente."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from rich.console import Console

from deep_agents.cli.banner import Banner
from deep_agents.cli.commands import Command, CommandRegistry
from deep_agents.cli.models import (
    AVAILABLE_MODELS,
    TEMPERATURES,
    THINKING_LEVELS,
    parse_temperature,
    parse_thinking,
    resolve_choice,
)
from deep_agents.cli.prompt import ChatPrompt, SlashCompleter
from deep_agents.cli.renderer import Renderer, skills_used, tools_used
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
        memory: Any | None = None,
        toolkit: Any | None = None,
    ) -> None:
        """`agent_factory(model_config) -> (agent, gateway)` habilita o comando /modello.
        `memory` (um `MemoryBuilder`) habilita as sessões: grava cada turno e o comando /sessioni.
        `toolkit` (um `ToolkitBuilder`) habilita o feedback das tools e a seção de fontes (lidas do canal lateral)."""
        self.channel = toolkit.channel if toolkit is not None else None
        self.tool_names = toolkit.tool_names() if toolkit is not None else set()
        self.agent = agent
        self.gateway = gateway
        self.agent_factory = agent_factory
        self.memory = memory
        self.models = models if models is not None else AVAILABLE_MODELS
        self.agent_name = agent_name or getattr(gateway.config, "model_id", "agent")
        self.console = console or Console()
        self.banner = Banner(name, version, self.agent_name)
        self.view = Renderer(self.console, self.agent_name)
        self._refresh_session()
        self.commands = self._build_commands()
        self.prompt = ChatPrompt(
            self.console,
            SlashCompleter(
                self.commands.listing,
                {
                    "/modello": lambda: [m.spec for m in self.models],
                    "/temperatura": lambda: ["default"] + [f"{v:.1f}" for _, v in TEMPERATURES if v is not None],
                    "/thinking": lambda: ["default", "off", "low", "medium", "high"],
                    "/sessioni": lambda: [s.id for s in self.memory.sessions()] if self.memory else [],
                },
            ),
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
        turn = self.channel.begin_turn() if self.channel is not None else None
        try:
            with self.view.status():
                result, report = self.gateway.run_agent(self.agent, {"messages": self.messages})
        except KeyboardInterrupt:
            self.messages.pop()
            self.view.notice("\nRisposta interrotta.")
            return
        except Exception as e:
            self.messages.pop()  # mantém o histórico consistente
            self.view.error(e, f"chiamata al modello {self.gateway.config.spec}")
            return

        # As mensagens retornadas já contêm todo o histórico + a nova resposta
        self.messages = result["messages"]
        manage_result_json(result)
        self.view.skills(skills_used(report))
        self.view.tools(tools_used(report, self.tool_names))
        answer = extract_response_text(result)
        self.view.agent_message(answer)
        if self.channel is not None:
            self.view.sources(self.channel.query(turn=turn, kind="sources"))
        self.view.metrics(report)
        self._save_turn(text, answer)

    # ----------------------------------------------------------------- sessões
    def _refresh_session(self) -> None:
        """Atualiza no banner o ID da sessão atual e o número de mensagens."""
        if self.memory is not None:
            self.banner.session = (self.memory.session_id, self.memory.message_count())

    def _save_turn(self, user_text: str, answer: str) -> None:
        """Grava o turno na sessão atual. Uma falha ao gravar não derruba o chat: só avisa."""
        if self.memory is None:
            return
        try:
            self.memory.record_turn(user_text, answer)
            self._refresh_session()
        except Exception as e:
            self.view.error(e, f"salvataggio del messaggio nella sessione {self.memory.session_id}")

    def _cmd_sessions(self, args: str = "") -> None:
        """`/sessioni` abre a lista; `/sessioni <id>` retoma direto. A conversa continua com o contexto salvo."""
        sessions = self.memory.sessions()
        if not sessions:
            self.view.notice("Nessuna sessione salvata.")
            return
        if args:
            chosen = next((s for s in sessions if s.id == args.strip()), None)
        else:
            labels = [self.view.session_label(s, s.id == self.memory.session_id) for s in sessions]
            current = next((i for i, s in enumerate(sessions) if s.id == self.memory.session_id), 0)
            picked = self._pick_setting("Sessione", labels, current)
            if picked is None:
                self.view.notice("Nessuna modifica.")
                return
            chosen = sessions[picked]
        if chosen is None:
            self.view.notice("Sessione non trovata (usa /sessioni per vedere l'elenco).")
            return
        if chosen.id == self.memory.session_id:
            self.view.notice("È già la sessione in uso.")
            return
        self.memory.resume(chosen.id)
        self.messages = self.memory.history()
        self._redraw()
        for message in self.messages:  # mostra a conversa anterior para dar contexto visual
            if message["role"] == "user":
                self.view.user_message(message["content"])
            else:
                self.view.agent_message(message["content"])
        self.view.notice(f"Sessione {chosen.id} ripresa: {len(self.messages)} messaggi (la conversazione continua)")

    def _redraw(self) -> None:
        """Limpa a tela e redesenha o banner (com a sessão atual)."""
        self._refresh_session()
        self.console.clear()
        self.banner.render(self.console)

    # --------------------------------------------------------------- comandos
    def _build_commands(self) -> CommandRegistry:
        registry = CommandRegistry()
        registry.register(Command("/aiuto", "mostra questo aiuto", self._cmd_help, ("/help",)))
        registry.register(
            Command("/pulisci", "inizia una nuova sessione vuota (e pulisce lo schermo)", self._cmd_clear, ("/clear",))
        )
        if self.memory is not None:
            registry.register(
                Command("/sessioni", "riprendi una sessione precedente (anche: /sessioni <id>)", self._cmd_sessions, ("/sessions",))
            )
        registry.register(Command("/metriche", "totali accumulati della sessione", self._cmd_metrics, ("/metrics",)))
        registry.register(
            Command("/esci", "termina la chat (anche: /exit, /quit)", self._cmd_exit, ("/exit", "/quit", "exit", "quit"))
        )
        if self.agent_factory is not None:
            registry.register(Command("/modello", "scegli il modello (anche: /modello provider:modello)", self._cmd_model))
            registry.register(Command("/temperatura", "imposta la temperatura (anche: /temperatura 0.7)", self._cmd_temperature))
            registry.register(Command("/thinking", "imposta il thinking (anche: /thinking high)", self._cmd_thinking))
        return registry

    def _cmd_help(self, args: str = "") -> None:
        self.view.commands_table(self.commands.listing())

    def _cmd_clear(self, args: str = "") -> None:
        self.messages = []
        if self.memory is not None:
            self.memory.new_session()  # a sessão anterior continua salva e pode ser retomada com /sessioni
        self._redraw()
        self.view.notice("Nuova sessione iniziata." if self.memory is not None else "Cronologia cancellata.")

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
        self._apply_config(new_config, f"Modello impostato: {new_config.spec}")

    def _cmd_temperature(self, args: str = "") -> None:
        """`/temperatura` abre o seletor; `/temperatura 0.7` (ou `default`) aplica direto."""
        current = self.gateway.config
        if args:
            ok, value = parse_temperature(args)
            if not ok:
                self.view.notice("Temperatura non valida (usa un numero tra 0 e 2, oppure 'default').")
                return
        else:
            picked = self._pick_setting(
                "Temperatura", [label for label, _ in TEMPERATURES],
                next((i for i, (_, v) in enumerate(TEMPERATURES) if v == current.temperature), 0),
                other="Altro… (digita un numero tra 0 e 2)",
            )
            if picked is None:
                self.view.notice("Nessuna modifica.")
                return
            if picked < len(TEMPERATURES):
                value = TEMPERATURES[picked][1]
            else:
                ok, value = parse_temperature(self._ask_free("0-2"))
                if not ok:
                    self.view.notice("Temperatura non valida.")
                    return
        label = "default" if value is None else f"{value:g}"
        self._apply_config(replace(current, temperature=value), f"Temperatura impostata: {label}")

    def _cmd_thinking(self, args: str = "") -> None:
        """`/thinking` abre o seletor; `/thinking high` (off/low/medium/high/default) aplica direto."""
        current = self.gateway.config
        if args:
            ok, value = parse_thinking(args)
            if not ok:
                self.view.notice("Livello non valido (usa: default, off, low, medium, high).")
                return
        else:
            picked = self._pick_setting(
                "Thinking", [label for label, _ in THINKING_LEVELS],
                next((i for i, (_, v) in enumerate(THINKING_LEVELS) if v == current.thinking), 0),
            )
            if picked is None:
                self.view.notice("Nessuna modifica.")
                return
            value = THINKING_LEVELS[picked][1]
        self._apply_config(replace(current, thinking=value), f"Thinking impostato: {value or 'default'}")

    # ------------------------------------------------------------ auxiliares
    def _ask_free(self, hint: str) -> str:
        try:
            return self.console.input(f"[grey50]{hint}[/] ❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    def _pick_setting(self, title: str, labels: list[str], current: int, other: str | None = None) -> int | None:
        """Seletor com setas (terminal) ou menu numerado (fallback). Devolve o índice ou None.
        O índice `len(labels)` significa a opção extra `other` (texto livre)."""
        options = labels + ([other] if other else [])
        try:
            if self.prompt.interactive:
                return self.prompt.select(options, current, title=f"Scegli: {title}")
            for i, label in enumerate(options, start=1):
                self.console.print(f"  [bold]{i}[/]  {label}")
            choice = self._ask_free("numero (invio per annullare)")
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                return int(choice) - 1
        except (EOFError, KeyboardInterrupt):
            pass
        return None

    def _apply_config(self, new_config: Any, message: str) -> None:
        """Reconstrói agente/gateway com a nova configuração; em caso de erro mantém a anterior."""
        try:
            with self.view.status(f"applico {new_config.spec}…"):
                agent, gateway = self.agent_factory(new_config)
        except Exception as e:
            self.view.error(e, f"configurazione di {new_config.spec} (modello precedente mantenuto)")
            return
        self.agent, self.gateway = agent, gateway
        self.agent_name = new_config.model_id
        self.banner.agent_name = self.view.agent_name = self.agent_name
        self.view.notice(f"{message} (la conversazione continua)")

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
