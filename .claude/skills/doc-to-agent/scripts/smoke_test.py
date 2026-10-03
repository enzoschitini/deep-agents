"""Offline smoke test for a generated prototype folder (no API key, no network).

Checks that:
  1. every .py file in the folder compiles;
  2. agent.py exposes DEFAULT_MODEL and build_agent();
  3. build_agent(model=<fake model>) builds and answers one turn;
  4. run_agent.py --help exits cleanly and no template `ADAPT` markers are left;
  5. every SKILL.md has valid frontmatter whose name matches its directory
     (a mismatch makes Deep Agents skip the skill silently);
  6. the layout holds: usage.md is there and lowercase, agent.py stays within its
     line budget and carries no prompt, option table or subagent dict, and no module
     grew past ~200 lines;
  7. the system prompt carries the rule that makes the agent answer in Portuguese.

It also prints the tools and the system prompt the main agent's model received, which
is the quickest way to confirm that skills, memory, subagents and custom tools are wired.

Usage:
  python smoke_test.py <prototype_dir> [--context '{"org_id": "demo"}'] [--prompt]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import py_compile
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

NAME_RULE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Things that belong in prompts.py / options.py / subagents.py, not in agent.py.
MISPLACED_IN_AGENT = re.compile(r"^[A-Z][A-Z0-9_]*(_PROMPT|_PROMPTS|_MODES|_OPTIONS|_SOURCES|_BACKENDS)\s*(:|=)")
failures: list[str] = []


class FakeModel(BaseChatModel):
    """Answers every call with a fixed text and records what the harness sent it."""

    bound_tools: list[list[str]] = []
    prompts: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "smoke"

    def bind_tools(self, tools, **kwargs):
        names = []
        for t in tools:
            if isinstance(t, dict):
                names.append(t.get("name") or t.get("function", {}).get("name", "?"))
            else:
                names.append(getattr(t, "name", None) or getattr(t, "__name__", "?"))
        self.bound_tools.append(names)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(str(messages[0].content))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="smoke-ok"))])


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def frontmatter(text: str) -> dict[str, str] | None:
    """Minimal parser for the name/description keys (handles `>-` folded blocks)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return None
    fields, key = {}, None
    for line in m.group(1).splitlines():
        top = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if top:
            key, value = top.group(1), top.group(2).strip()
            fields[key] = "" if value in (">-", ">", "|", "|-") else value.strip("\"'")
        elif key and line.startswith(" "):
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline smoke test for a prototype folder.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--context", help="JSON passed as invoke(context=...) for agents with a context_schema")
    parser.add_argument("--prompt", action="store_true", help="print the full system prompt")
    args = parser.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    folder = args.folder.resolve()
    print(f"\nsmoke test: {folder}\n")

    print("files")
    entries = {p.name for p in folder.iterdir()}  # exact names: Windows paths are case-insensitive
    for name in ("agent.py", "run_agent.py"):
        check(f"{name} exists", (folder / name).is_file())
    check("usage.md exists (lowercase, not USAGE.md)", "usage.md" in entries,
          "found " + (", ".join(sorted(n for n in entries if n.lower() == "usage.md")) or "nothing"))
    broken = False
    for py in sorted(folder.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            py_compile.compile(str(py), doraise=True)
        except py_compile.PyCompileError as e:
            check(f"compiles: {py.relative_to(folder)}", False, str(e).splitlines()[-1])
            broken = True
    if broken or not (folder / "agent.py").is_file():  # nothing below can run
        sys.exit(1)

    print("\nlayout")
    agent_lines = (folder / "agent.py").read_text(encoding="utf-8").splitlines()
    check("agent.py within its ~120-line budget", len(agent_lines) <= 140, f"{len(agent_lines)} lines")
    misplaced = [f"{n}: {line.split('=')[0].strip()}" for n, line in enumerate(agent_lines, 1)
                 if MISPLACED_IN_AGENT.match(line)]
    check("agent.py holds no prompts, option tables or subagent dicts", not misplaced,
          "; ".join(misplaced[:4]) + (" ..." if len(misplaced) > 4 else ""))
    oversized = []
    for py in sorted(folder.rglob("*.py")):
        if "__pycache__" in py.parts or py.name == "run_agent.py":  # the shared engine sets its own size
            continue
        n = len(py.read_text(encoding="utf-8").splitlines())
        if n > 220:
            oversized.append(f"{py.relative_to(folder).as_posix()} ({n})")
    check("no module over ~200 lines", not oversized, ", ".join(oversized))

    print("\nagent.py")
    sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location("agent", folder / "agent.py")
    agent_mod = importlib.util.module_from_spec(spec)
    sys.modules["agent"] = agent_mod  # dataclasses and pydantic resolve annotations through sys.modules
    spec.loader.exec_module(agent_mod)
    check("exposes DEFAULT_MODEL", hasattr(agent_mod, "DEFAULT_MODEL"), getattr(agent_mod, "DEFAULT_MODEL", ""))
    check("exposes build_agent()", callable(getattr(agent_mod, "build_agent", None)))

    fake = FakeModel(bound_tools=[], prompts=[])
    try:
        agent = agent_mod.build_agent(model=fake)
        payload: dict[str, Any] = {"messages": [{"role": "user", "content": "ping"}]}
        kwargs: dict[str, Any] = {"config": {"configurable": {"thread_id": "smoke"}}}
        if args.context:
            kwargs["context"] = json.loads(args.context)
        result = agent.invoke(payload, **kwargs)
        answer = result["messages"][-1].content
        check("build_agent(model=fake) answers one turn", answer == "smoke-ok", repr(answer)[:60])
    except Exception as e:  # show the real cause, it is usually a wrong import or kwarg
        check("build_agent(model=fake) answers one turn", False, f"{type(e).__name__}: {e}")

    if fake.bound_tools:
        print(f"\n  tools seen by the main agent: {', '.join(fake.bound_tools[0])}")
    if fake.prompts:
        prompt = fake.prompts[0]
        print(f"  system prompt: {len(prompt)} chars")
        check("system prompt asks for Portuguese answers", "portugu" in prompt.lower(),
              "no 'Responda sempre em portugues...' rule reached the model")
        if args.prompt:
            print("\n" + prompt + "\n")

    print("\nrun_agent.py")
    run = subprocess.run([sys.executable, str(folder / "run_agent.py"), "--help"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    check("--help exits 0", run.returncode == 0, run.stderr.strip().splitlines()[-1] if run.returncode else "")
    leftovers = [n for n, line in enumerate((folder / "run_agent.py").read_text(encoding="utf-8").splitlines(), 1)
                 if "ADAPT" in line or "<topic>" in line]
    check("no template ADAPT/<topic> markers left", not leftovers, f"lines {leftovers}" if leftovers else "")

    skill_files = sorted(folder.rglob("SKILL.md"))
    if skill_files:
        print("\nskills")
    for md in skill_files:
        rel = md.relative_to(folder).as_posix()
        fm = frontmatter(md.read_text(encoding="utf-8"))
        if fm is None:
            check(f"{rel}: frontmatter", False, "missing --- block")
            continue
        name, desc = fm.get("name", ""), fm.get("description", "")
        ok = name == md.parent.name and bool(NAME_RULE.match(name)) and len(name) <= 64 and 0 < len(desc) <= 1024
        check(f"{rel}", ok, f"name={name!r} dir={md.parent.name!r} description={len(desc)} chars")

    print(f"\n{'PASSED' if not failures else f'{len(failures)} FAILED'}\n")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
