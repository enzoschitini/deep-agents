"""The doc's alternatives, as tables both agent.py and run_agent.py read.

Each table backs one CLI flag and one chat command, so two variants can be compared
inside a single session.
"""
from __future__ import annotations

from prompts import SPECIFIC_DESCRIPTIONS, VAGUE_DESCRIPTIONS
from schemas import IncidentContext

# Who is on the roster, and what happens to the auto-added `general-purpose`.
# `SubAgentMiddleware` — and with it the `task` tool — is attached only when at least
# one synchronous subagent exists, so dropping GP alone is not enough to remove it.
# (`excluded_middleware=["SubAgentMiddleware"]` is not the way: it raises ValueError.)
ROSTER_MODES = {
    "full": {"custom": True, "general_purpose": "auto"},  # GP added automatically, inherits the skills
    "gp-override": {"custom": True, "general_purpose": "custom"},  # our own spec fully replaces it
    "gp-off": {"custom": True, "general_purpose": "off"},  # profile enabled=False; `task` survives
    "no-task": {"custom": False, "general_purpose": "off"},  # nothing left to delegate to: no `task`
}

# The descriptions are the only thing the coordinator uses to pick a subagent.
DESCRIPTION_STYLES = {
    "specific": SPECIFIC_DESCRIPTIONS,  # action-oriented: delegation lands on the right specialist
    "vague": VAGUE_DESCRIPTIONS,  # reproduces the troubleshooting section: no or wrong delegation
}

# Context values handed to invoke(context=...); they reach every subagent unchanged.
CONTEXT_PRESETS = {
    "default": IncidentContext(user_id="sre-duty-01"),
    "strict": IncidentContext(  # impact-analyst also sees the error margins
        user_id="sre-duty-01", log_analyst_max_lines=12, impact_analyst_strict_mode=True
    ),
    "deep": IncidentContext(  # log-analyst reads the whole log instead of the head
        user_id="sre-duty-01", log_analyst_max_lines=60, impact_analyst_strict_mode=False
    ),
}

# `interrupt_on` on the fork's write tool; needs the checkpointer build_agent passes.
INTERRUPT_MODES = {
    "off": False,  # unattended runs
    "on": True,  # write_postmortem pauses for human approval
}

# The interpreter that turns `task()` into something the agent can call from code.
DYNAMIC_MODES = {
    "off": None,  # delegation only through the `task` tool
    "on": True,  # CodeInterpreterMiddleware(): dynamic dispatch, triggered by "workflow"
    "task-only": False,  # CodeInterpreterMiddleware(subagents=False): code but no fan-out
}

# How a turn is rendered: plain update stream, or the typed v3 projections.
STREAM_MODES = {
    "updates": "updates",  # agent.stream(stream_mode="updates"); handles approval pauses
    "events": "events",  # stream_events(version="v3"): live per-subagent panel
}
