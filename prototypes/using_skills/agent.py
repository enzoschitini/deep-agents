"""Deep Agents harness: an orchestrator plus skills plus a specialist subagent.

Architecture:
  orchestrator (create_deep_agent)
    ├─ skills: /skills/orchestrator/  -> executive-summary, trip-planning
    ├─ harness tools: ls, read_file, glob, grep, write_file, edit_file, task
    ├─ subagent "analyst" (isolated context)
    │    ├─ skills: /skills/analyst/  -> numeric-analysis
    │    └─ tools: calculate
    └─ subagent "general-purpose" (added automatically, inherits the parent's skills)

`permission_mode` swaps the write rule over /skills/**: read-only (deny), human
approval (interrupt) or agent-editable skills (writable).

Usage:
  python agent.py                     one-shot run with the default prompt
  python agent.py "your question"     one-shot run
  python agent.py --chat              interactive terminal chat
  python agent.py --chat --mode interrupt --model anthropic:claude-sonnet-5
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend

load_dotenv()  # loads environment variables from .env

ROOT = Path(__file__).resolve().parent

# Reuse the skill's own script as the tool implementation (tested, deterministic logic).
_spec = importlib.util.spec_from_file_location(
    "calc", ROOT / "skills/analyst/numeric-analysis/scripts/calc.py"
)
_calc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_calc)


def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression (+ - * / ** %) and return the result."""
    try:
        return str(_calc.safe_eval(expression))
    except Exception as e:  # readable error for the model
        return f"ERROR: {e}"


ORCHESTRATOR_PROMPT = """You are an ORCHESTRATOR. Rules:
- Before answering, check whether any available skill applies to the request; if one
  does, read its SKILL.md with read_file and follow the instructions.
- Delegate any arithmetic to the `analyst` subagent through the `task` tool."""

ANALYST = {
    "name": "analyst",
    "description": "Specialist in arithmetic, budgets and statistics. Use for any calculation.",
    "system_prompt": "You are a numeric analyst. Consult your skills before acting.",
    "tools": [calculate],
    "skills": ["/skills/analyst/"],  # custom subagents do NOT inherit the parent's skills
}

# Effect of the write rule over /skills/** in each mode.
PERMISSION_MODES = {
    "deny": "deny",           # read-only skills: a curated library (default)
    "interrupt": "interrupt",  # writes pause for human approval
    "writable": "allow",      # the agent may create and refine its own skills
}


def build_agent(model="anthropic:claude-sonnet-4-6", analyst_model=None, permission_mode="deny"):
    backend = FilesystemBackend(root_dir=str(ROOT), virtual_mode=True)
    analyst = dict(ANALYST)
    if analyst_model is not None:
        analyst["model"] = analyst_model
    return create_deep_agent(
        model=model,
        system_prompt=ORCHESTRATOR_PROMPT,
        backend=backend,
        skills=["/skills/orchestrator/"],
        subagents=[analyst],
        permissions=[
            FilesystemPermission(
                operations=["write"],
                paths=["/skills/**"],
                mode=PERMISSION_MODES[permission_mode],
            )
        ],
        checkpointer=MemorySaver(),
        name="orchestrator",
    )


# ------------------------------------------------------------------- banner
LOGO = [
    "██████  ███████ ███████ ██████ ",
    "██   ██ ██      ██      ██   ██",
    "██   ██ █████   █████   ██████ ",
    "██   ██ ██      ██      ██     ",
    "██████  ███████ ███████ ██     ",
    " █████   ██████ ███████ ██   ██ ███████",
    "██   ██ ██      ██      ███  ██    ██  ",
    "███████ ██  ███ █████   ██ █ ██    ██  ",
    "██   ██ ██   ██ ██      ██  ███    ██  ",
    "██   ██  ██████ ███████ ██   ██    ██  ",
]
SUBTITLE = "LangChain Deep Agents · skills playground"


def use_utf8() -> None:
    """The box-drawing characters below are unprintable under Windows' cp1252 default."""
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def print_banner(model: str, mode: str) -> None:
    use_utf8()
    color, dim, off = ("\033[38;5;209m", "\033[2m", "\033[0m") if sys.stdout.isatty() else ("", "", "")
    art = max(len(line) for line in LOGO)
    width = max(art, len(SUBTITLE)) + 6  # 3 columns of padding on each side

    def row(text, style=""):
        body = text.center(width)
        print(f"{dim}│{off}{style}{body}{off}{dim}│{off}")

    print()
    print(f"{dim}╭{'─' * width}╮{off}")
    row("")
    for line in LOGO:
        row(line.center(art), color)
    row("")
    row(SUBTITLE, dim)
    row("")
    print(f"{dim}╰{'─' * width}╯{off}")
    print(f"\n  model {model}   ·   /skills/** {mode}")
    print(f"  {dim}tool calls show up as →. /help for commands, /exit to quit.{off}\n")


# --------------------------------------------------------------------- chat
def _fmt_args(name: str, args: dict) -> str:
    """Condense a tool call's arguments into one line."""
    if name == "task":
        return f"{args.get('subagent_type', '?')}: {str(args.get('description', ''))[:60]}"
    for key in ("file_path", "expression", "pattern", "path"):
        if key in args:
            return str(args[key])
    return str(args)[:70]


def _echo(messages, already_seen: set) -> None:
    """Print tool calls and their results as they come off the stream."""
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                if tc["id"] in already_seen:  # reappears when resuming from a pause
                    continue
                already_seen.add(tc["id"])
                print(f"  → {tc['name']}({_fmt_args(tc['name'], tc['args'])})")
        elif isinstance(m, ToolMessage):
            print(f"    ← {' '.join(str(m.content).split())[:80]}")


def _ask_decision(interrupt) -> Command:
    """Ask the human what to do about the paused action."""
    request = interrupt.value["action_requests"][0]
    print(f"\n  [PAUSED] the agent wants to run {request['name']}({_fmt_args(request['name'], request['args'])})")
    if input("  approve? [y/N] ").strip().lower().startswith("y"):
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

    print(f"\n{agent.get_state(config).values['messages'][-1].content}\n")


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

    while True:
        try:
            line = input("you> ").strip()
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
                print("  skills will be reloaded on the next question.\n")
            elif cmd == "/skills":
                metadata = agent.get_state(config).values.get("skills_metadata")
                if not metadata:
                    print("  no skills loaded yet (ask something first).\n")
                else:
                    for s in metadata:
                        print(f"  - {s['name']}: {s['description'][:70]}")
                    print()
            elif cmd == "/mode":
                if arg.strip() not in PERMISSION_MODES:
                    print(f"  modes: {', '.join(PERMISSION_MODES)}\n")
                else:
                    mode = arg.strip()
                    agent = build_agent(model=model, permission_mode=mode)
                    print(f"  /skills/** is now {mode} (conversation restarted).\n")
            else:
                print("  unknown command — /help lists the available ones.\n")
            continue

        turn(agent, {"messages": [{"role": "user", "content": line}]}, config)


DEFAULT_PROMPT = (
    "Plan a 2-day itinerary in Salvador with a budget: 2 nights at 300 and 4 meals at 80."
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deep Agents skills playground.")
    parser.add_argument("question", nargs="*", help="question for a one-shot run")
    parser.add_argument("--chat", action="store_true", help="interactive terminal chat")
    parser.add_argument("--model", default="anthropic:claude-sonnet-4-6")
    parser.add_argument("--mode", default="deny", choices=list(PERMISSION_MODES))
    args = parser.parse_args()

    use_utf8()

    if args.chat:
        chat(args.model, args.mode)
        return

    agent = build_agent(model=args.model, permission_mode=args.mode)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": " ".join(args.question) or DEFAULT_PROMPT}]},
        config={"configurable": {"thread_id": "one-shot"}},
    )
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()

# Normal execcution: python -m prototypes.using_skills.agent
# CLI usage: python prototypes/using_skills/agent.py --chat --mode interrupt --model anthropic:claude-sonnet-5