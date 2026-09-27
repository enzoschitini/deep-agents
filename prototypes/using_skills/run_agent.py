"""Runs the agent defined in agent.py: one-shot, or as an interactive terminal chat.

Usage:
  python run_agent.py                     one-shot run with the default prompt
  python run_agent.py "your question"     one-shot run
  python run_agent.py --chat              interactive terminal chat
  python run_agent.py --chat --mode interrupt --model anthropic:claude-sonnet-5
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

from agent import DEFAULT_MODEL, PERMISSION_MODES, build_agent  # noqa: E402

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
    "calculate": "green",
}
MODE_STYLES = {"deny": "green", "interrupt": "yellow", "writable": "red"}
SKILL_MARKER = re.compile(r"\[skill:([a-z0-9-]+)\]")


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
SUBTITLE = "LangChain Deep Agents · skills playground"


def print_banner(model: str, mode: str) -> None:
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
    print(
        f"\n  {paint('model', 'dim')} {paint(model, 'bold')}"
        f"   {paint('·', 'dim')}   {paint('/skills/**', 'dim')} "
        f"{paint(mode, MODE_STYLES[mode], 'bold')}"
    )
    legend = "  ".join(
        paint(f"● {kind}", style)
        for kind, style in (("read", "cyan"), ("write", "yellow"), ("delegate", "magenta"), ("compute", "green"))
    )
    print(f"  {legend}")
    print(paint("  /help for commands, /exit to quit.", "dim") + "\n")


# ---------------------------------------------------------------- transcript
def _fmt_args(name: str, args: dict) -> str:
    """Condense a tool call's arguments into one line."""
    if name == "task":
        return f"{args.get('subagent_type', '?')}: {str(args.get('description', ''))[:60]}"
    for key in ("file_path", "expression", "pattern", "path"):
        if key in args:
            return str(args[key])
    return str(args)[:70]


def _fmt_call(name: str, args: dict) -> str:
    """Render one tool call, flagging the moment a skill actually gets activated."""
    line = f"{paint(name, TOOL_STYLES.get(name, 'blue'), 'bold')}{paint('(' + _fmt_args(name, args) + ')', 'dim')}"
    path = str(args.get("file_path", ""))
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


def _ask_decision(interrupt) -> Command:
    """Ask the human what to do about the paused action."""
    request = interrupt.value["action_requests"][0]
    print(f"\n  {paint(' PAUSED ', 'yellow', 'bold')} the agent wants to run")
    print(f"  {_fmt_call(request['name'], request['args'])}")
    if input(paint("  approve? [y/N] ", "yellow")).strip().lower().startswith("y"):
        return Command(resume={"decisions": [{"type": "approve"}]})
    return Command(resume={"decisions": [{"type": "reject", "message": "Human rejected the write."}]})


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
        payload = _ask_decision(interrupt)

    answer = message_text(agent.get_state(config).values["messages"][-1])
    answer = SKILL_MARKER.sub(lambda m: paint(m.group(0), "green", "bold"), answer)
    print(f"\n{paint('agent', 'orange', 'bold')}\n{answer}\n")


# --------------------------------------------------------------------- chat
HELP = """
  /skills           list the skills the agent can see on this thread
  /reset            reload skills on the next question (clears skills_metadata)
  /mode <mode>      change the write permission over /skills/** (restarts the conversation)
  /help             show this help
  /exit             quit
"""


def chat(model: str, mode: str) -> None:
    """Interactive REPL so you can watch progressive disclosure happen turn by turn."""
    agent = build_agent(model=model, permission_mode=mode)
    config = {"configurable": {"thread_id": "chat"}}
    print_banner(model, mode)

    def notice(text, *styles):
        print(f"  {paint(text, *(styles or ('cyan',)))}\n")

    while True:
        try:
            line = input(paint("you> ", "orange", "bold")).strip()
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
            elif cmd == "/reset":
                agent.update_state(config, {"skills_metadata": None})
                notice("skills will be reloaded on the next question.")
            elif cmd == "/skills":
                metadata = agent.get_state(config).values.get("skills_metadata")
                if not metadata:
                    notice("no skills loaded yet (ask something first).", "dim")
                else:
                    for s in metadata:
                        print(f"  {paint('◆', 'green')} {paint(s['name'], 'bold')}"
                              f" {paint(s['description'][:70], 'dim')}")
                    print()
            elif cmd == "/mode":
                if arg.strip() not in PERMISSION_MODES:
                    notice(f"modes: {', '.join(PERMISSION_MODES)}", "dim")
                else:
                    mode = arg.strip()
                    agent = build_agent(model=model, permission_mode=mode)
                    notice(f"/skills/** is now {mode} (conversation restarted).", MODE_STYLES[mode])
            else:
                notice("unknown command — /help lists the available ones.", "red")
            continue

        turn(agent, {"messages": [{"role": "user", "content": line}]}, config)


# ----------------------------------------------------------------- one-shot
DEFAULT_PROMPT = (
    "Plan a 2-day itinerary in Salvador with a budget: 2 nights at 300 and 4 meals at 80."
)


def one_shot(question: str, model: str, mode: str) -> None:
    agent = build_agent(model=model, permission_mode=mode)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"configurable": {"thread_id": "one-shot"}},
    )
    print(message_text(result["messages"][-1]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Deep Agents skills playground.")
    parser.add_argument("question", nargs="*", help="question for a one-shot run")
    parser.add_argument("--chat", action="store_true", help="interactive terminal chat")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--mode", default="deny", choices=list(PERMISSION_MODES))
    args = parser.parse_args()

    use_utf8()

    if args.chat:
        chat(args.model, args.mode)
    else:
        one_shot(" ".join(args.question) or DEFAULT_PROMPT, args.model, args.mode)


if __name__ == "__main__":
    main()
