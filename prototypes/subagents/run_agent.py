"""Runs the agent defined in agent.py: one-shot, or as an interactive terminal chat.

Usage:
  python run_agent.py                     one-shot run with the default prompt
  python run_agent.py "your question"     one-shot run
  python run_agent.py --chat              interactive terminal chat
  python run_agent.py --chat --roster gp-override --descriptions vague --stream events
"""
from __future__ import annotations

import argparse
import os
import re
import sys

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

# `python -m ...` puts the CWD on sys.path, not this directory, so `agent` would not resolve.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import DEFAULT_MODEL, build_agent  # noqa: E402
from options import (  # noqa: E402
    CONTEXT_PRESETS,
    DESCRIPTION_STYLES,
    DYNAMIC_MODES,
    INTERRUPT_MODES,
    ROSTER_MODES,
    STREAM_MODES,
)
from subagents import FORK_ONLY_ADDENDUM, SUBAGENT_MODES, build_roster  # noqa: E402
from tools import clear_journal, journal_entries  # noqa: E402

# ------------------------------------------------------------------- colors
STYLES = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "orange": "\033[38;5;209m", "cyan": "\033[38;5;117m", "green": "\033[38;5;114m",
    "yellow": "\033[38;5;215m", "magenta": "\033[38;5;176m", "red": "\033[38;5;203m",
    "grey": "\033[38;5;245m", "blue": "\033[38;5;110m",
}
# FORCE_COLOR keeps the palette when output is piped (demos, screen recordings).
COLOR = (sys.stdout.isatty() or os.environ.get("FORCE_COLOR")) and not os.environ.get("NO_COLOR")

# One hue per kind of action, so a long transcript is skimmable.
TOOL_STYLES = {
    "read_file": "cyan", "ls": "cyan", "glob": "cyan", "grep": "cyan",
    "write_file": "yellow", "edit_file": "yellow",
    "task": "magenta",
    "write_todos": "blue",
    "read_incident_log": "cyan", "read_impact_metrics": "cyan",
    "shared_lookup": "green",
    "write_postmortem": "yellow",
}
LEGEND = (("read", "cyan"), ("write", "yellow"), ("delegate", "magenta"), ("consult", "green"))
# Green for the configurations that behave, red for the ones that reproduce a failure.
OPTION_STYLES = {
    "full": "green", "gp-override": "magenta", "gp-off": "yellow", "no-task": "red",
    "specific": "green", "vague": "red",
    "off": "green", "on": "yellow", "task-only": "cyan",
    "default": "green", "strict": "magenta", "deep": "cyan",
    "updates": "green", "events": "magenta",
}
OPTION_LABELS = {
    "roster": "roster", "descriptions": "descrições", "interrupt": "interrupt",
    "dynamic": "dynamic", "context": "contexto", "stream": "stream",
}
# Highlights observable markers such as [subagent:log-analyst] in the final answer.
MARKER = re.compile(r"\[[a-z]+:[a-z0-9-]+\]")


def paint(text: str, *styles: str) -> str:
    if not COLOR:
        return text
    return "".join(STYLES[s] for s in styles) + text + STYLES["reset"]


def use_utf8() -> None:
    """The box-drawing characters below are unprintable under Windows' cp1252 default."""
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def message_text(message) -> str:
    """Flatten a message's content to text.

    Models that return thinking blocks give `content` as a list of blocks, which prints
    as a raw Python repr if handed straight to print().
    """
    content = message.content
    if isinstance(content, str):
        return content
    blocks = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(b for b in blocks if b).strip()


# ------------------------------------------------------------------- banner
LOGO = [
    "█████  ██████ ██████ ██████    ",
    "██  ██ ██     ██     ██  ██    ",
    "██  ██ █████  █████  █████     ",
    "██  ██ ██     ██     ██        ",
    "█████  ██████ ██████ ██        ",
    "",
    " ████   █████ ██████ ██   ██ ██████",
    "██  ██ ██     ██     ███  ██   ██  ",
    "██████ ██ ███ █████  ██ █ ██   ██  ",
    "██  ██ ██  ██ ██     ██  ███   ██  ",
    "██  ██  █████ ██████ ██   ██   ██  ",
]
SUBTITLE = "LangChain Deep Agents · playground de subagentes"


def print_banner(model: str, options: dict) -> None:
    use_utf8()
    art = max(len(line) for line in LOGO) + 4  # breathing room so AGENT isn't flush to the edges
    width = max(art, len(SUBTITLE)) + 6  # 3 columns of padding on each side

    def row(text, *styles):
        print(paint("│", "dim") + paint(text.center(width), *styles) + paint("│", "dim"))

    print()
    print(paint(f"╭{'─' * width}╮", "dim"))
    row("")
    for line in LOGO:
        row(line.center(art), "orange")
    row("")
    row(SUBTITLE, "dim")
    row("")
    print(paint(f"╰{'─' * width}╯", "dim"))
    status = f"  {paint('model', 'dim')} {paint(model, 'bold')}"
    for name, value in options.items():
        label, value = OPTION_LABELS.get(name, name), str(value)
        status += f"   {paint('·', 'dim')}   {paint(label, 'dim')} {paint(value, OPTION_STYLES.get(value, 'blue'), 'bold')}"
    print("\n" + status)
    print("  " + "  ".join(paint(f"● {kind}", style) for kind, style in LEGEND))
    print(paint("  /help para ver os comandos, /exit para sair.", "dim") + "\n")


# ---------------------------------------------------------------- transcript
def _fmt_args(name: str, args: dict) -> str:
    """Condense a tool call's arguments into one line."""
    if name == "task":
        return f"{args.get('subagent_type', '?')}: {str(args.get('description', ''))[:60]}"
    for key in ("incident_id", "query", "file_path", "pattern", "path", "command"):
        if key in args:
            return str(args[key])
    return str(args)[:70]


def _fmt_call(name: str, args: dict) -> str:
    """Render one tool call, flagging the moment the doc's key mechanism fires."""
    line = f"{paint(name, TOOL_STYLES.get(name, 'blue'), 'bold')}{paint('(' + _fmt_args(name, args) + ')', 'dim')}"
    if name == "task":  # delegation is what this doc is about: show the context mode
        target = args.get("subagent_type", "?")
        mode = SUBAGENT_MODES.get(target, "isolated")
        line += "  " + paint(f"◆ delegando → {target} ({mode})", "green", "bold")
    path = str(args.get("file_path", ""))
    if name == "read_file" and path.endswith("SKILL.md"):
        line += "  " + paint(f"◆ ativando {path.rsplit('/', 2)[-2]}", "green", "bold")
    return line


def _is_error(text: str) -> bool:
    head = text[:80].lower()
    return head.startswith("error") or "permission denied" in head or "rejected the tool call" in head


def _echo(messages, already_seen: set) -> None:
    """Print tool calls and their results as they come off the stream."""
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                if tc["id"] in already_seen:  # reappears when resuming from a pause
                    continue
                already_seen.add(tc["id"])
                print(f"  {paint('→', 'grey')} {_fmt_call(tc['name'], tc['args'])}")
        elif isinstance(m, ToolMessage):
            body = " ".join(str(m.content).split())
            if _is_error(body):  # errors stay long enough to be actionable
                print(f"    {paint('✗', 'red')} {paint(body[:200], 'red')}")
            else:
                print(f"    {paint('←', 'grey')} {paint(body[:90], 'grey')}")


def _ask_decisions(interrupt) -> Command:
    """Ask the human about every paused action; the resume needs one decision per action."""
    decisions = []
    for request in interrupt.value["action_requests"]:
        print(f"\n  {paint(' PAUSADO ', 'yellow', 'bold')} o agente quer executar")
        print(f"  {_fmt_call(request['name'], request['args'])}")
        if input(paint("  aprovar? [s/N] ", "yellow")).strip().lower().startswith(("s", "y")):
            decisions.append({"type": "approve"})
        else:
            decisions.append({"type": "reject", "message": "O humano rejeitou a ação."})
    return Command(resume={"decisions": decisions})


def _print_answer(text: str) -> None:
    text = MARKER.sub(lambda m: paint(m.group(0), "green", "bold"), text)
    print(f"\n{paint('agente', 'orange', 'bold')}\n{text}\n")


def turn(agent, payload, config, context=None) -> None:
    """Run one full turn, handling however many approval pauses show up."""
    already_seen: set[str] = set()
    while True:
        interrupt = None
        for update in agent.stream(payload, config=config, context=context, stream_mode="updates"):
            for node, value in update.items():
                if node == "__interrupt__":
                    interrupt = value[0]
                elif isinstance(value, dict) and value.get("messages"):
                    _echo(value["messages"], already_seen)
        if interrupt is None:
            break
        payload = _ask_decisions(interrupt)

    _print_answer(message_text(agent.get_state(config).values["messages"][-1]))


def turn_events(agent, payload, config, context=None) -> None:
    """Same turn through the v3 typed projections, with a live panel per subagent.

    `interleave` drives one run and hands back whichever projection produced the next
    item; the subagent handles have to be drained inside the loop body, before the
    next pump cycle. Approval pauses are not handled here — use --stream updates.
    """
    stream = agent.stream_events(payload, config=config, context=context, version="v3")
    for projection, item in stream.interleave("messages", "subagents"):
        if projection == "messages":
            for call in item.tool_calls.get() or []:
                print(f"  {paint('→', 'grey')} {_fmt_call(call['name'], call['args'])}")
            continue
        # A subagent handle: .name is its lc_agent_name, .status its lifecycle.
        print(f"  {paint('┌ ' + str(item.name), 'magenta', 'bold')} {paint('iniciou', 'dim')}")
        for message in item.messages:
            for call in message.tool_calls.get() or []:
                print(f"  {paint('│', 'magenta')} {_fmt_call(call['name'], call['args'])}")
            body = " ".join(str(message.text).split())
            if body:
                print(f"  {paint('│', 'magenta')} {paint(body[:120], 'grey')}")
        print(f"  {paint('└ ' + str(item.name), 'magenta', 'bold')} {paint('status: ' + str(item.status), 'dim')}")

    _print_answer(message_text(agent.get_state(config).values["messages"][-1]))


def run_turn(agent, payload, config, context, stream_mode) -> None:
    (turn_events if STREAM_MODES[stream_mode] == "events" else turn)(agent, payload, config, context)


# --------------------------------------------------------------------- chat
HELP = """
  /roster           lista o roster configurado e se a ferramenta task existe
  /roster <modo>    troca o roster: full, gp-override, gp-off, no-task
  /descriptions <e> troca as descrições dos subagentes: specific, vague
  /interrupt <v>    aprovação humana na escrita do post-mortem: off, on
  /dynamic <v>      interpretador de código: off, on, task-only
  /context <v>      contexto da execução: default, strict, deep
  /stream <v>       renderização do turno: updates, events
  /journal [agente] consultas ao shared_lookup, filtradas por lc_agent_name
  /journal clear    limpa o journal
  /preamble         como o fork vê a conversa do pai
  /help             mostra esta ajuda
  /exit             sai
"""


def cmd_roster(choices: dict, model: str) -> None:
    """Print the roster the coordinator's `task` tool currently advertises."""
    mode = ROSTER_MODES[choices["roster"]]
    roster = build_roster(mode, DESCRIPTION_STYLES[choices["descriptions"]],
                          INTERRUPT_MODES[choices["interrupt"]], model)
    for spec in roster:
        name = spec["name"]
        compiled = "runnable" in spec
        kind = "CompiledSubAgent" if compiled else f"mode={spec.get('mode', 'isolated')}"
        extras = [k for k in ("skills", "permissions", "response_format", "interrupt_on") if k in spec]
        tools = [getattr(t, "name", "?") for t in spec.get("tools", [])]
        print(f"  {paint(name, 'magenta', 'bold')} {paint(kind, 'dim')}")
        detail = "grafo próprio, já compilado" if compiled else (", ".join(tools) or "(herda do pai)")
        print(f"    {paint('tools', 'dim')} {detail}")
        if extras:
            print(f"    {paint('campos', 'dim')} {', '.join(extras)}")
        print(f"    {paint('descrição', 'dim')} {spec['description'][:88]}")
    if mode["general_purpose"] == "auto":
        print(f"  {paint('general-purpose', 'magenta', 'bold')} {paint('adicionado automaticamente', 'dim')}")
        print(f"    {paint('skills', 'dim')} herda /skills/coordinator/ do coordenador")
    elif mode["general_purpose"] == "off":
        print(f"  {paint('general-purpose', 'grey')} {paint('desligado pelo harness profile', 'dim')}")
    has_task = bool(roster) or mode["general_purpose"] == "auto"
    verdict = "task disponível" if has_task else "sem ferramenta task: nada para delegar"
    print(f"\n  {paint(verdict, 'green' if has_task else 'red', 'bold')}\n")


def cmd_journal(arg: str) -> None:
    """The local stand-in for filtering runs by lc_agent_name in LangSmith."""
    if arg == "clear":
        clear_journal()
        print(f"  {paint('journal limpo.', 'cyan')}\n")
        return
    rows = journal_entries(arg or None)
    if not rows:
        print(f"  {paint('nenhuma consulta registrada' + (f' para {arg}' if arg else '') + '.', 'grey')}\n")
        return
    for caller, query in rows:
        print(f"  {paint(caller, 'magenta', 'bold')} {paint('lc_agent_name', 'dim')}  {query}")
    print()


def cmd_preamble() -> None:
    """Show what a forked subagent actually receives instead of a task description."""
    try:
        from deepagents.middleware.subagents import _FORK_TASK_PREAMBLE  # texto real da versão instalada
    except ImportError:
        _FORK_TASK_PREAMBLE = "(não disponível nesta versão de deepagents)"
    print(f"\n  {paint('o fork não recebe uma tarefa nova:', 'bold')}")
    print("  a última AIMessage do pai (a que chamou task) é descartada e substituída")
    print("  por uma HumanMessage com este preâmbulo, seguido da descrição da tarefa:\n")
    print(paint("  " + str(_FORK_TASK_PREAMBLE).replace("\n", "\n  "), "cyan"))
    print(f"  {paint('a doc descreve um preâmbulo mais curto; este é o da versão instalada,', 'dim')}")
    print(f"  {paint('e ele também avisa que delegar de novo será recusado.', 'dim')}\n")
    print(f"  {paint('addendum fork-only que NÃO usamos (quebraria o prompt cache do pai):', 'dim')}")
    print(paint("  " + FORK_ONLY_ADDENDUM.replace("\n", "\n  "), "grey") + "\n")


def chat(model: str, choices: dict, analyst_model=None) -> None:
    """Interactive REPL so you can watch the agent work turn by turn."""
    agent = build_agent(model=model, analyst_model=analyst_model, **agent_kwargs(choices))
    config = {"configurable": {"thread_id": "chat"}}
    print_banner(model, choices)

    def notice(text, *styles):
        print(f"  {paint(text, *(styles or ('cyan',)))}\n")

    def switch(key, table, arg):
        nonlocal agent
        if arg not in table:
            notice(f"valor inválido — use: {', '.join(table)}.", "red")
            return
        choices[key] = arg
        if key in ("context", "stream"):  # nada para reconstruir: não são opções do build_agent
            notice(f"{OPTION_LABELS[key]} agora é {arg}.", OPTION_STYLES.get(arg, "cyan"))
            return
        agent = build_agent(model=model, analyst_model=analyst_model, **agent_kwargs(choices))
        notice(f"{OPTION_LABELS[key]} agora é {arg} (conversa reiniciada).", OPTION_STYLES.get(arg, "cyan"))

    while True:
        try:
            line = input(paint("você> ", "orange", "bold")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue

        if line.startswith("/"):
            cmd, _, arg = line.partition(" ")
            arg = arg.strip()
            if cmd == "/exit":
                return
            if cmd == "/help":
                print(HELP)
            elif cmd == "/roster":
                if arg:
                    switch("roster", ROSTER_MODES, arg)
                else:
                    cmd_roster(choices, model)
            elif cmd == "/descriptions":
                switch("descriptions", DESCRIPTION_STYLES, arg)
            elif cmd == "/interrupt":
                switch("interrupt", INTERRUPT_MODES, arg)
            elif cmd == "/dynamic":
                switch("dynamic", DYNAMIC_MODES, arg)
            elif cmd == "/context":
                switch("context", CONTEXT_PRESETS, arg)
            elif cmd == "/stream":
                switch("stream", STREAM_MODES, arg)
            elif cmd == "/journal":
                cmd_journal(arg)
            elif cmd == "/preamble":
                cmd_preamble()
            else:
                notice("comando desconhecido — /help lista os disponíveis.", "red")
            continue

        run_turn(agent, {"messages": [{"role": "user", "content": line}]}, config,
                 CONTEXT_PRESETS[choices["context"]], choices["stream"])


# ----------------------------------------------------------------- one-shot
DEFAULT_PROMPT = (
    "Assuma o incidente INC-2043: investigue a causa raiz, estime o impacto, monte a "
    "cronologia e grave o post-mortem."
)


def one_shot(question: str, model: str, choices: dict, analyst_model=None) -> None:
    agent = build_agent(model=model, analyst_model=analyst_model, **agent_kwargs(choices))
    config = {"configurable": {"thread_id": "one-shot"}}
    context = CONTEXT_PRESETS[choices["context"]]
    payload = {"messages": [{"role": "user", "content": question}]}
    if STREAM_MODES[choices["stream"]] == "events":  # mostra o painel por subagente também aqui
        turn_events(agent, payload, config, context)
        return
    result = agent.invoke(payload, config=config, context=context)
    while result.get("__interrupt__"):  # an approval pause still needs a human, even here
        result = agent.invoke(_ask_decisions(result["__interrupt__"][0]), config=config, context=context)
    print(message_text(result["messages"][-1]))


def agent_kwargs(choices: dict) -> dict:
    """The CLI choices as build_agent options."""
    return {
        "roster_mode": choices["roster"],
        "description_style": choices["descriptions"],
        "interrupt": INTERRUPT_MODES[choices["interrupt"]],
        "dynamic_mode": choices["dynamic"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa o playground de subagentes do Deep Agents.")
    parser.add_argument("question", nargs="*", help="pergunta para uma execução one-shot")
    parser.add_argument("--chat", action="store_true", help="chat interativo no terminal")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--analyst-model", default=None,
                        help="modelo só para log-analyst e impact-analyst (escolher modelo por tarefa)")
    parser.add_argument("--roster", default="full", choices=list(ROSTER_MODES),
                        help="quem está no roster e o que acontece com o general-purpose")
    parser.add_argument("--descriptions", default="specific", choices=list(DESCRIPTION_STYLES),
                        help="descrições específicas ou vagas, para ver a delegação falhar")
    parser.add_argument("--interrupt", default="off", choices=list(INTERRUPT_MODES),
                        help="pausa para aprovação humana antes de gravar o post-mortem")
    parser.add_argument("--dynamic", default="off", choices=list(DYNAMIC_MODES),
                        help="interpretador de código para despachar subagentes de dentro do código")
    parser.add_argument("--context", default="default", choices=list(CONTEXT_PRESETS),
                        help="valores de contexto repassados a todos os subagentes")
    parser.add_argument("--stream", default="updates", choices=list(STREAM_MODES),
                        help="renderização do turno: updates simples ou projeções v3 por subagente")
    args = parser.parse_args()

    use_utf8()
    choices = {
        "roster": args.roster, "descriptions": args.descriptions, "interrupt": args.interrupt,
        "dynamic": args.dynamic, "context": args.context, "stream": args.stream,
    }

    if args.chat:
        chat(args.model, choices, args.analyst_model)
    else:
        one_shot(" ".join(args.question) or DEFAULT_PROMPT, args.model, choices, args.analyst_model)


if __name__ == "__main__":
    main()
