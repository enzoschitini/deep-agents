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

This module only defines the agent. Running it — one-shot or as a terminal chat —
lives in run_agent.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

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

DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"


def build_agent(model=DEFAULT_MODEL, analyst_model=None, permission_mode="deny"):
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

"""
1. Normal execution:
python -m prototypes.using_skills.run_agent

2. CLI usage:
python prototypes/using_skills/run_agent.py --chat --mode interrupt --model anthropic:claude-sonnet-5
"""