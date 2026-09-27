"""Validates how skills behave in the harness.

Modes:
  python validate.py          -> OFFLINE: scripted models (no API key). Checks the harness
                                 mechanics: discovery (level 1), reading SKILL.md (level 2),
                                 supporting resources (level 3), skill isolation between the
                                 orchestrator and a custom subagent, inheritance by the
                                 general-purpose subagent, the three permission modes
                                 (deny / interrupt / writable) and skill reloading.
  python validate.py --live   -> LIVE: uses a real LLM (ANTHROPIC_API_KEY) and checks that
                                 the model picks the right skills on its own.
"""
from __future__ import annotations

import os
import shutil
import sys
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.types import Command

# `python -m ...` puts the CWD on sys.path, not this directory, so `agent` would not resolve.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import ROOT, build_agent  # noqa: E402

ORCH = "/skills/orchestrator"
ANALYST = "/skills/analyst"

# Throwaway files used by the permission and reload tests.
SCRATCH = f"{ORCH}/_scratch.md"
SCRATCH_DISK = ROOT / "skills/orchestrator/_scratch.md"
NEW_SKILL_DISK = ROOT / "skills/orchestrator/temporary-skill"


# ---------------------------------------------------------------- fake model
class ScriptedModel(BaseChatModel):
    """Fake model: replays predefined steps and records the system prompt it received."""

    steps: list[Any]
    seen_prompts: list[str] = []
    i: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen_prompts.append(str(messages[0].content))
        step = self.steps[self.i]
        self.i += 1
        if isinstance(step, str):
            msg = AIMessage(content=step)
        else:  # (tool_name, args)
            name, args = step
            msg = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{uuid.uuid4().hex[:8]}"}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


# ---------------------------------------------------------------- helpers
def tool_calls(messages):
    return [tc for m in messages if isinstance(m, AIMessage) for tc in m.tool_calls]


def tool_results(messages):
    return {m.tool_call_id: str(m.content) for m in messages if isinstance(m, ToolMessage)}


results: list[tuple[str, bool]] = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  [{'OK' if cond else 'FAILED'}] {name}")


# ---------------------------------------------------------------- offline
def offline():
    orch = ScriptedModel(steps=[
        ("read_file", {"file_path": f"{ORCH}/trip-planning/SKILL.md"}),
        ("read_file", {"file_path": f"{ORCH}/executive-summary/references/template.md"}),
        ("task", {"subagent_type": "analyst", "description": "Compute the budget: 2 nights at 300 + 4 meals at 80."}),
        ("write_file", {"file_path": f"{ORCH}/trip-planning/SKILL.md", "content": "hack"}),
        "Day 1: ... Day 2: ... Total budget: 920. [skill:trip-planning]",
    ], seen_prompts=[])
    analyst = ScriptedModel(steps=[
        ("read_file", {"file_path": f"{ANALYST}/numeric-analysis/SKILL.md"}),
        ("calculate", {"expression": "2*300 + 4*80"}),
        "2*300 + 4*80 = 920 [skill:numeric-analysis]",
    ], seen_prompts=[])

    agent = build_agent(model=orch, analyst_model=analyst)
    out = agent.invoke(
        {"messages": [{"role": "user", "content": "2-day itinerary in Salvador with a budget"}]},
        config={"configurable": {"thread_id": "offline"}},
    )
    msgs = out["messages"]
    calls, res = tool_calls(msgs), tool_results(msgs)
    by_name = {tc["name"]: tc for tc in calls}

    print("\nLevel 1 — discovery (metadata in the system prompt)")
    p0 = orch.seen_prompts[0]
    check("orchestrator sees 'executive-summary'", "executive-summary" in p0)
    check("orchestrator sees 'trip-planning'", "trip-planning" in p0)
    check("orchestrator does NOT see 'numeric-analysis' (isolation)", "numeric-analysis" not in p0)
    check("SKILL.md body is NOT in the prompt (progressive disclosure)", "ALWAYS end" not in p0)
    a0 = analyst.seen_prompts[0]
    check("analyst sees 'numeric-analysis'", "numeric-analysis" in a0)
    check("analyst does NOT see the orchestrator's skills", "trip-planning" not in a0)

    print("\nLevel 2 — activation (read_file on SKILL.md)")
    read = [res[tc["id"]] for tc in calls if tc["name"] == "read_file"]
    check("read_file returned the skill instructions", "delegate the math" in read[0])

    print("\nLevel 3 — supporting resource (only once the instructions ask for it)")
    check("template under references/ was read on demand", "Key points" in read[1])

    print("\nDelegation + subagent skill")
    task_out = res[by_name["task"]["id"]]
    check("subagent used calculate and returned 920", "920" in task_out)
    check("subagent response carries the skill marker", "[skill:numeric-analysis]" in task_out)

    print("\nPermissions — deny mode (default)")
    wf = res[by_name["write_file"]["id"]]
    skill_md = (ROOT / "skills/orchestrator/trip-planning/SKILL.md").read_text(encoding="utf-8")
    check("write under /skills/** blocked", "hack" not in skill_md)
    print(f"     (harness message: {wf[:90]!r})")

    print("\nFinal answer")
    check("marker [skill:trip-planning] in the answer", "[skill:trip-planning]" in msgs[-1].content)


# ------------------------------------------------ general-purpose inheritance
def general_purpose():
    """The general-purpose subagent is added on its own and inherits the parent's skills."""
    orch = ScriptedModel(steps=[
        ("task", {"subagent_type": "general-purpose", "description": "Summarize project X."}),
        "summary delivered by general-purpose",
        "Done.",
    ], seen_prompts=[])

    agent = build_agent(model=orch)
    agent.invoke(
        {"messages": [{"role": "user", "content": "Delegate the summary to general-purpose."}]},
        config={"configurable": {"thread_id": "gp"}},
    )

    print("\nGeneral-purpose subagent — skill inheritance")
    gp = orch.seen_prompts[1]  # 2nd model call = inside the subagent
    check("prompt belongs to general-purpose, not the orchestrator", "ORCHESTRATOR" not in gp)
    check("inherited 'executive-summary' from the parent", "executive-summary" in gp)
    check("inherited 'trip-planning' from the parent", "trip-planning" in gp)
    check("does NOT see the custom subagent's skill", "numeric-analysis" not in gp)


# ------------------------------------------------------------------ permissions
def permissions():
    """Writable mode lets writes through; interrupt mode pauses and only writes once approved."""
    try:
        print("\nPermissions — writable mode")
        m = ScriptedModel(steps=[("write_file", {"file_path": SCRATCH, "content": "skill edited by the agent"}), "ok"],
                          seen_prompts=[])
        build_agent(model=m, permission_mode="writable").invoke(
            {"messages": [{"role": "user", "content": "write"}]},
            config={"configurable": {"thread_id": "writable"}},
        )
        check("write under /skills/** allowed", SCRATCH_DISK.exists()
              and "skill edited by the agent" in SCRATCH_DISK.read_text(encoding="utf-8"))
        SCRATCH_DISK.unlink(missing_ok=True)

        print("\nPermissions — interrupt mode (human approval)")
        m = ScriptedModel(steps=[("write_file", {"file_path": SCRATCH, "content": "written after approval"}), "ok"],
                          seen_prompts=[])
        agent = build_agent(model=m, permission_mode="interrupt")
        cfg = {"configurable": {"thread_id": "interrupt"}}
        out = agent.invoke({"messages": [{"role": "user", "content": "write"}]}, config=cfg)

        itr = out.get("__interrupt__")
        check("execution paused before writing", bool(itr))
        check("nothing was written while paused", not SCRATCH_DISK.exists())
        if itr:
            request = itr[0].value["action_requests"][0]
            check("the interrupt describes the pending write_file", request["name"] == "write_file")
            agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=cfg)
            check("once approved, the write happens", SCRATCH_DISK.exists()
                  and "written after approval" in SCRATCH_DISK.read_text(encoding="utf-8"))
    finally:
        SCRATCH_DISK.unlink(missing_ok=True)


# --------------------------------------------------------------------- reload
def reload_skills():
    """Skills load once per thread; they only reappear after clearing skills_metadata."""
    orch = ScriptedModel(steps=["turn 1", "turn 2", "turn 3"], seen_prompts=[])
    agent = build_agent(model=orch)
    cfg = {"configurable": {"thread_id": "reload"}}
    run = lambda: agent.invoke({"messages": [{"role": "user", "content": "hi"}]}, config=cfg)

    try:
        run()

        # Create a new skill on disk AFTER the thread has already loaded the list.
        NEW_SKILL_DISK.mkdir(parents=True, exist_ok=True)
        (NEW_SKILL_DISK / "SKILL.md").write_text(
            "---\nname: temporary-skill\ndescription: Skill created at runtime to test reloading.\n---\n\n# temporary-skill\n",
            encoding="utf-8",
        )
        run()

        print("\nSkill reloading")
        check("new skill absent on the same thread (metadata cached)",
              "temporary-skill" not in orch.seen_prompts[1])

        agent.update_state(cfg, {"skills_metadata": None})
        run()
        check("after clearing skills_metadata, the new skill shows up",
              "temporary-skill" in orch.seen_prompts[2])
    finally:
        shutil.rmtree(NEW_SKILL_DISK, ignore_errors=True)


# ---------------------------------------------------------------- live
CASES = [
    ("Summarize for the board: project X slipped 2 weeks for lack of QA, "
     "cost rose 10% and the client asked for a new demo on Friday.", "executive-summary", None),
    ("Plan a 2-day itinerary in Salvador with a budget: 2 nights at 300 and 4 meals at 80.",
     "trip-planning", "numeric-analysis"),
    ("What is the capital of France? Answer in one word.", None, None),  # control: no skill
]


def live(model: str):
    for i, (prompt, skill, sub_skill) in enumerate(CASES):
        print(f"\nCase {i + 1}: {prompt[:60]}...")
        agent = build_agent(model=model)
        out = agent.invoke({"messages": [{"role": "user", "content": prompt}]},
                           config={"configurable": {"thread_id": f"live-{i}"}})
        msgs = out["messages"]
        calls = tool_calls(msgs)
        read = [tc["args"].get("file_path", "") for tc in calls if tc["name"] == "read_file"]
        final = msgs[-1].content if isinstance(msgs[-1].content, str) else str(msgs[-1].content)
        if skill:
            check(f"read {skill}/SKILL.md", any(f"{skill}/SKILL.md" in p for p in read))
            check(f"marker [skill:{skill}] in the answer", f"[skill:{skill}]" in final)
        else:
            check("no skill activated (control case)", not any("SKILL.md" in p for p in read))
        if sub_skill:
            task_out = " ".join(str(m.content) for m in msgs if isinstance(m, ToolMessage) and m.name == "task")
            check("delegated to the analyst subagent", any(tc["name"] == "task" for tc in calls))
            check(f"subagent applied {sub_skill}", f"[skill:{sub_skill}]" in task_out)
        print("  answer:", final[:200].replace("\n", " "), "...")


if __name__ == "__main__":
    if "--live" in sys.argv:
        live(sys.argv[sys.argv.index("--live") + 1] if len(sys.argv) > sys.argv.index("--live") + 1
             else "anthropic:claude-sonnet-4-6")
    else:
        offline()
        general_purpose()
        permissions()
        reload_skills()
    ok = sum(r for _, r in results)
    print(f"\n{ok}/{len(results)} checks OK")
    sys.exit(0 if ok == len(results) else 1)
