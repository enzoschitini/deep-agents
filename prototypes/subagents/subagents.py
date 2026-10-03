"""The subagent roster: three isolated specs, one fork, one compiled graph, plus GP.

Each spec carries, as inline comments, the inheritance rule of the `SubAgent` field it
uses — those rules are the part of the doc that is easiest to get wrong.
"""
from __future__ import annotations

from importlib.metadata import version

from langchain.agents import create_agent

from deepagents import CompiledSubAgent, FilesystemPermission

from prompts import (
    FORK_ADDENDUM,
    GENERAL_PURPOSE_PROMPT,
    IMPACT_ANALYST_PROMPT,
    LOG_ANALYST_PROMPT,
    TIMELINE_BUILDER_PROMPT,
)
from schemas import ImpactAssessment, IncidentTimeline
from tools import read_impact_metrics, read_incident_log, shared_lookup, write_postmortem

# mode="fork" needs >=0.7.13; a subagent `response_format` needs >=0.5.3.
_REQUIRED = (0, 7, 13)
_INSTALLED = tuple(int(part) for part in version("deepagents").split(".")[:3])
assert _INSTALLED >= _REQUIRED, f"mode='fork' exige deepagents>={_REQUIRED}, instalado {_INSTALLED}"

# Printed next to every `task()` call so the context mode is visible in the transcript.
SUBAGENT_MODES = {
    "log-analyst": "isolated",
    "impact-analyst": "isolated",
    "timeline-builder": "compiled",
    "postmortem-writer": "fork",
    "general-purpose": "isolated",
}

LOG_ANALYST = {
    "name": "log-analyst",
    "system_prompt": LOG_ANALYST_PROMPT,  # required for isolated: nothing is inherited
    "tools": [read_incident_log, shared_lookup],  # overrides the inherited tool set entirely
    "skills": ["/skills/log-analyst/"],  # custom subagents do NOT inherit the parent's skills
    "permissions": [  # replaces the parent's permissions completely, not merged
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ],
}

IMPACT_ANALYST = {
    "name": "impact-analyst",
    "system_prompt": IMPACT_ANALYST_PROMPT,
    "tools": [read_impact_metrics, shared_lookup],
    "response_format": ImpactAssessment,  # the parent's ToolMessage becomes JSON
}

POSTMORTEM_WRITER = {
    "name": "postmortem-writer",
    "mode": "fork",  # inherits the parent's full history and exact system prompt
    "tools": [write_postmortem],
    # `skills` is rejected under fork. `system_prompt` is allowed but is only appended
    # to the inherited prompt and breaks the parent's prompt cache, so it stays unset.
}

# What a fork-only addendum would look like, had we set `system_prompt` above; the CLI
# prints it under /preamble so the trade-off stays visible without paying for it.
FORK_ONLY_ADDENDUM = FORK_ADDENDUM

GENERAL_PURPOSE = {
    "name": "general-purpose",  # this exact name replaces the auto-added default
    "system_prompt": GENERAL_PURPOSE_PROMPT,
    "tools": [shared_lookup],
}


def timeline_builder(model) -> CompiledSubAgent:
    """A prebuilt graph used as a subagent; it keeps its own prompt even under fork."""
    graph = create_agent(
        model=model,
        tools=[],  # works from the task text the coordinator passes in
        system_prompt=TIMELINE_BUILDER_PROMPT,
        response_format=IncidentTimeline,
        name="timeline-builder",  # binds lc_agent_name, so streaming can tell it apart
    )  # `create_agent` returns a compiled graph whose state already has `messages`
    return CompiledSubAgent(
        name="timeline-builder",
        description="",  # filled in by build_roster from the chosen description style
        runnable=graph,
    )


def build_roster(mode: dict, descriptions: dict, interrupt: bool, model, analyst_model=None) -> list:
    """Assemble the subagent list for one `build_agent` call.

    `mode` is a ROSTER_MODES entry; `descriptions` is a DESCRIPTION_STYLES entry.
    """
    if not mode["custom"]:
        return []

    specs = [dict(LOG_ANALYST), dict(IMPACT_ANALYST), dict(POSTMORTEM_WRITER)]
    if analyst_model is not None:  # doc: choose models by task
        specs[0]["model"] = analyst_model
        specs[1]["model"] = analyst_model
    if interrupt:  # needs a checkpointer, which build_agent always passes
        specs[2]["interrupt_on"] = {"write_postmortem": True}

    roster: list = [*specs, timeline_builder(model)]
    if mode["general_purpose"] == "custom":
        roster.append(dict(GENERAL_PURPOSE))

    for spec in roster:
        spec["description"] = descriptions[spec["name"]]
    return roster
