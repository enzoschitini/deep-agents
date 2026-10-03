"""Runs the agent defined in agent.py: one-shot, or as an interactive terminal chat.

Usage:
  python run_agent.py                     one-shot run with the default prompt
  python run_agent.py "your question"     one-shot run
  python run_agent.py --chat              interactive terminal chat
  python run_agent.py --chat --model anthropic:claude-sonnet-5
"""
# ADAPT (docstring): the last usage line shows the topic's flags, e.g. `--chat --mode interrupt --model ...`.
#
# TEMPLATE NOTES — delete this block and every `# ADAPT` comment once the file is filled in.
# Everything outside the ADAPT spots is the standard engine shared by all prototypes:
# colors, banner, transcript echo, approval pauses, REPL loop, one-shot. Keep it as is so
# every prototype looks and behaves the same in the terminal.
# Language: every string the user reads is Portuguese (subtitle, HELP, notices, argparse
# texts, prompts); flags, slash-command names, identifiers and comments stay English.
# The ADAPT spots are:
#   imports          which option tables options.py exposes
#   TOOL_STYLES      one color per kind of action (add the agent's custom tools)
#   LEGEND           the kinds shown under the banner (only kinds this agent has)
#   OPTION_STYLES    color for each value of each option shown in the banner
#   OPTION_LABELS    how each option is labelled in the banner
#   SUBTITLE         "LangChain Deep Agents · playground de <topic>"
#   _fmt_args        which argument summarizes a custom tool call
#   _fmt_call        the "◆ ..." highlight for the moment the doc's key mechanism fires
#   HELP + commands  slash commands that inspect/toggle what the doc is about
#   DEFAULT_PROMPT   one Portuguese prompt exercising as many of the doc's topics as possible
#   main()           CLI flags -> build_agent options
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
# ADAPT: the option tables this topic exposes, e.g. `from options import PERMISSION_MODES  # noqa: E402`

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
    # ADAPT: custom tools, e.g. "calculate": "green"; "execute" (sandbox shell) is usually "green" too
}
# ADAPT: only the kinds this agent actually has (drop "compute" if it has no custom tools).
LEGEND = (("read", "cyan"), ("write", "yellow"), ("delegate", "magenta"), ("compute", "green"))
# ADAPT: color of each value an option can take in the banner, e.g. {"deny": "green", "interrupt": "yellow", "writable": "red"}.
OPTION_STYLES: dict[str, str] = {}
# ADAPT: banner label of each build_agent option, e.g. {"permission_mode": "/skills/**"}; defaults to the kwarg name.
OPTION_LABELS: dict[str, str] = {}
# Highlights observable markers such as [skill:trip-planning] in the final answer.
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
SUBTITLE = "LangChain Deep Agents · playground de <topic>"  # ADAPT


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
    for key in ("file_path", "pattern", "path", "command"):  # ADAPT: the key that best summarizes each custom tool
        if key in args:
            return str(args[key])
    return str(args)[:70]


def _fmt_call(name: str, args: dict) -> str:
    """Render one tool call, flagging the moment the doc's key mechanism fires."""
    line = f"{paint(name, TOOL_STYLES.get(name, 'blue'), 'bold')}{paint('(' + _fmt_args(name, args) + ')', 'dim')}"
    path = str(args.get("file_path", ""))
    # ADAPT: flag what this doc is about (reading AGENTS.md, writing under /memories/, ...).
    if name == "read_file" and path.endswith("SKILL.md"):
        line += "  " + paint(f"◆ activating {path.rsplit('/', 2)[-2]}", "green", "bold")
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


def turn(agent, payload, config) -> None:
    """Run one full turn, handling however many approval pauses show up."""
    already_seen: set[str] = set()
    while True:
        interrupt = None
        for update in agent.stream(payload, config=config, stream_mode="updates"):
            for node, value in update.items():
                if node == "__interrupt__":
                    interrupt = value[0]
                elif isinstance(value, dict) and value.get("messages"):
                    _echo(value["messages"], already_seen)
        if interrupt is None:
            break
        payload = _ask_decisions(interrupt)

    answer = message_text(agent.get_state(config).values["messages"][-1])
    answer = MARKER.sub(lambda m: paint(m.group(0), "green", "bold"), answer)
    print(f"\n{paint('agente', 'orange', 'bold')}\n{answer}\n")


# --------------------------------------------------------------------- chat
# ADAPT: one line per topic command, keeping /help and /exit last.
HELP = """
  /help             mostra esta ajuda
  /exit             sai
"""


def chat(model: str, options: dict) -> None:
    """Interactive REPL so you can watch the agent work turn by turn."""
    agent = build_agent(model=model, **options)
    config = {"configurable": {"thread_id": "chat"}}
    print_banner(model, options)

    def notice(text, *styles):
        print(f"  {paint(text, *(styles or ('cyan',)))}\n")

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
            if cmd == "/exit":
                return
            if cmd == "/help":
                print(HELP)
            # ADAPT: topic commands go here. Two shapes cover most docs:
            #   inspect state  -> agent.get_state(config).values.get("<key>") and print it
            #   switch option  -> validate arg, options["<name>"] = arg,
            #                     agent = build_agent(model=model, **options), then
            #                     notice("... (conversa reiniciada).", OPTION_STYLES[arg])
            else:
                notice("comando desconhecido — /help lista os disponíveis.", "red")
            continue

        turn(agent, {"messages": [{"role": "user", "content": line}]}, config)


# ----------------------------------------------------------------- one-shot
DEFAULT_PROMPT = "<um prompt em português que exercite o máximo de tópicos da doc>"  # ADAPT


def one_shot(question: str, model: str, options: dict) -> None:
    agent = build_agent(model=model, **options)
    config = {"configurable": {"thread_id": "one-shot"}}
    result = agent.invoke({"messages": [{"role": "user", "content": question}]}, config=config)
    while result.get("__interrupt__"):  # an approval pause still needs a human, even here
        result = agent.invoke(_ask_decisions(result["__interrupt__"][0]), config=config)
    print(message_text(result["messages"][-1]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa o playground <topic> do Deep Agents.")  # ADAPT
    parser.add_argument("question", nargs="*", help="pergunta para uma execução one-shot")
    parser.add_argument("--chat", action="store_true", help="chat interativo no terminal")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    # ADAPT: one flag per build_agent option, choices taken from agent.py's tables, e.g.
    # parser.add_argument("--mode", default="deny", choices=list(PERMISSION_MODES))
    args = parser.parse_args()

    use_utf8()
    options: dict = {}  # ADAPT: flags -> build_agent kwargs, e.g. {"permission_mode": args.mode}

    if args.chat:
        chat(args.model, options)
    else:
        one_shot(" ".join(args.question) or DEFAULT_PROMPT, args.model, options)


if __name__ == "__main__":
    main()
