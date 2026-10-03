"""Deep Agents harness: an incident coordinator that only works through subagents.

Architecture:
  coordinator (create_deep_agent, name="coordinator")
    ├─ skills: /skills/coordinator/  -> incident-triage
    ├─ harness tools: ls, read_file, glob, grep, write_file, edit_file, task
    ├─ tools: shared_lookup
    ├─ subagent "log-analyst" (isolated)
    │    ├─ skills: /skills/log-analyst/  -> log-forensics  (not inherited from the parent)
    │    ├─ tools: read_incident_log, shared_lookup
    │    └─ permissions: read-only (replaces the parent's rules entirely)
    ├─ subagent "impact-analyst" (isolated, response_format=ImpactAssessment -> JSON)
    │    └─ tools: read_impact_metrics, shared_lookup
    ├─ subagent "timeline-builder" (CompiledSubAgent: a create_agent graph)
    ├─ subagent "postmortem-writer" (mode="fork": inherits history and prompt)
    │    └─ tools: write_postmortem
    └─ subagent "general-purpose" (auto-added, inherits the coordinator's skills)

`roster_mode` decides who is on the roster: the default GP, our own replacement for
it, no GP, or no subagents at all — the last one leaves the agent without `task`.
`description_style` swaps specific descriptions for vague ones, which is how the
doc's "subagent not being called" symptom is reproduced on demand.
`interrupt` makes the fork's write pause for approval; `dynamic_mode` attaches the
code interpreter so the agent can dispatch subagents from code.

This module only wires the agent together. Prompts, tools, subagents and options live
in their own modules; running it — one-shot or as a terminal chat — lives in
run_agent.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents._models import get_model_provider  # the harness' own profile-key lookup
from deepagents.backends.filesystem import FilesystemBackend

# `python -m ...` puts the CWD on sys.path, not this directory, so `prompts` would not resolve.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from options import DESCRIPTION_STYLES, DYNAMIC_MODES, ROSTER_MODES  # noqa: E402
from prompts import COORDINATOR_PROMPT  # noqa: E402
from schemas import IncidentContext  # noqa: E402
from subagents import build_roster  # noqa: E402
from tools import shared_lookup  # noqa: E402

load_dotenv()  # loads environment variables from .env

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"


def _apply_gp_profile(model, enabled: bool) -> None:
    """Turn the auto-added general-purpose subagent on or off for this model.

    Harness profiles are keyed by provider and registration merges, so both states are
    always written explicitly — leaving `enabled` at None would inherit the previous
    call's value for the rest of the process.
    """
    key = model.split(":", 1)[0] if isinstance(model, str) else get_model_provider(model)
    if key:
        register_harness_profile(
            key,
            HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=enabled)),
        )


def _interpreter_middleware(dynamic_mode: str) -> list:
    """The interpreter that enables dispatching subagents from code.

    Needs `deepagents[quickjs]`; without it the agent still runs, delegating only
    through the `task` tool.
    """
    setting = DYNAMIC_MODES[dynamic_mode]
    if setting is None:
        return []
    try:
        from langchain_quickjs import CodeInterpreterMiddleware
    except ImportError:
        print("  aviso: langchain-quickjs não está instalado — subagentes dinâmicos desligados.")
        return []
    # subagents=False keeps the interpreter but forces delegation back through `task`.
    return [CodeInterpreterMiddleware(subagents=setting)]


def build_agent(
    model=DEFAULT_MODEL,
    analyst_model=None,
    roster_mode="full",
    description_style="specific",
    interrupt=False,
    dynamic_mode="off",
):
    mode = ROSTER_MODES[roster_mode]
    _apply_gp_profile(model, mode["general_purpose"] == "auto")
    return create_deep_agent(
        model=model,
        system_prompt=COORDINATOR_PROMPT,
        tools=[shared_lookup],
        backend=FilesystemBackend(root_dir=str(ROOT), virtual_mode=True),
        skills=["/skills/coordinator/"],  # the GP subagent inherits these; the custom ones do not
        subagents=build_roster(
            mode, DESCRIPTION_STYLES[description_style], interrupt, model, analyst_model
        ),
        middleware=_interpreter_middleware(dynamic_mode),
        context_schema=IncidentContext,  # propagates unchanged to every subagent and tool
        checkpointer=MemorySaver(),  # chat threads, approval pauses and forks all need it
        name="coordinator",  # becomes lc_agent_name on every run the coordinator produces
    )

"""
1. Normal execution:
python -m prototypes.subagents.run_agent

2. CLI usage:
python prototypes/subagents/run_agent.py --chat --roster gp-override --descriptions vague --stream events
"""
