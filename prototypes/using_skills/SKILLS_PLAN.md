# Deep Agents skills, in practice

Turning the documentation (`skills_doc.md`) into a runnable agent that exercises,
one by one, the capabilities behind the `skills` argument of `create_deep_agent`.

## 1. The documentation's core arguments

**Progressive disclosure in 3 levels.** This is the idea holding up everything else.
The agent never carries instructions it might not use:

| Level | What enters the context | When |
|---|---|---|
| 1. Metadata | `name` + `description` from the frontmatter | at startup, for every configured skill |
| 2. Instructions | the whole `SKILL.md` body | when the agent decides to activate the skill |
| 3. Resources | `scripts/`, `references/`, `assets/` | only when the instructions say to read them |

Levels 1 and 2 are the `SkillsMiddleware`'s job; level 3 is the LLM's own decision.

**The `description` is the only activation hook.** At discovery the agent sees nothing
but the name and description — that is what it uses to decide whether to read the
`SKILL.md`. A vague description ("helps with PDFs"), or descriptions that overlap
between skills, is the number one cause of a skill that never fires. Hence the advice
to keep few, well-scoped skills.

**Isolation and composition.** Skills are addressed by path, so you can vary who sees
what: per role, per tenant, per subagent. Two rules worth remembering: later sources
override earlier ones when names collide (*last one wins*), and skill state is isolated
between the main agent and its subagents — with one important exception, the
`general-purpose` subagent, which inherits the parent's skills automatically.

**Permissions.** Availability decides what the agent *sees*; permissions decide what it
may *write*. The three useful regimes: a curated library (`deny`), skills the agent
refines on its own (`allow`), and writes gated by human approval (`interrupt`).

**Reloading.** Skills load once per thread and stay in state. Editing a `SKILL.md` on
disk changes nothing for a thread that has already run — you have to clear
`skills_metadata` to `None` (not to an empty list, which means "loaded and found nothing").

**Skills ≠ memory ≠ tools.** A skill is an on-demand capability (read when relevant);
memory (`AGENTS.md`) is context loaded every time; a tool is a programmatic action
available every turn. In practice the border between skill and memory is porous: an
agent that writes its own skills is using skills as memory with progressive disclosure.

## 2. What this prototype builds

```
orchestrator  (create_deep_agent, FilesystemBackend, MemorySaver)
├─ skills: /skills/orchestrator/ → executive-summary, trip-planning
├─ custom subagent "analyst"
│    ├─ skills: /skills/analyst/ → numeric-analysis   (does NOT inherit the parent's)
│    └─ tool: calculate
└─ subagent "general-purpose"  (automatic, DOES inherit the parent's skills)
```

The orchestrator's two skills cover different shapes of skill: `executive-summary`
pulls in a supporting resource (`references/template.md`), while `trip-planning`
delegates arithmetic to another agent. The analyst's skill points at a script
(`scripts/calc.py`) whose logic is the same one behind the `calculate` tool — the
script is the deterministic reference, the tool is how it reaches the model.

Every skill ends with a `[skill:name]` marker, which makes activation observable from
the outside without inspecting the model's reasoning.

## 3. Map: principle → check

Everything below runs offline against scripted models (`ScriptedModel`), so the checks
measure real harness behavior rather than an LLM's goodwill.

| Documented principle | Check in `validate.py` |
|---|---|
| Level 1: metadata in the system prompt | orchestrator sees `executive-summary` and `trip-planning` |
| Level 1: body does NOT leak at startup | `SKILL.md` body absent from the prompt |
| Level 2: activation via `read_file` | `read_file` returned the skill instructions |
| Level 3: resource on demand | `references/template.md` read only after the instructions |
| Isolation (custom subagent) | analyst sees only its own skill; orchestrator doesn't see it |
| Inheritance (general-purpose subagent) | GP prompt carries the parent's skills, not the custom one's |
| Delegation between agents | `task` → analyst uses `calculate` and returns 920 |
| `deny` permission (curated library) | write under `/skills/**` blocked, file untouched |
| `allow` permission (editable skills) | write under `/skills/**` lands and persists |
| `interrupt` permission (approval) | run pauses, nothing written, writes once approved |
| Reload: per-thread cache | skill created at runtime absent on the same thread |
| Reload: clearing `skills_metadata` | after clearing to `None`, the new skill shows up |

## 4. How to run

```bash
cd prototypes/using_skills

python validate.py            # offline suite, no API key — 23 checks
python validate.py --live     # optional: a real LLM picks the skills itself
python run_agent.py           # one-shot run with the default prompt
python run_agent.py "your question"
python run_agent.py --chat    # interactive chat (needs ANTHROPIC_API_KEY)
```

`agent.py` holds only the agent definition (tools, prompts, subagent, permissions);
`run_agent.py` owns execution and terminal rendering.

`--chat` covers the part no test captures: watching the agent *decide*. It echoes every
tool call (`→ read_file(...)`, `→ task(analyst, ...)`) before the answer, so you can
follow disclosure happening turn by turn. Commands: `/skills` (what the agent sees right
now), `/reset` (force a reload), `/mode deny|interrupt|writable` (swap the permission
regime), `/exit`.

Good prompts for testing activation: a summary request, an itinerary request with
arithmetic (should delegate to the analyst), and a trivial control question — that last
one should activate no skill at all.

The default model is `anthropic:claude-sonnet-4-6`, inherited from the documentation's
example; the current generation is `claude-sonnet-5` / `claude-opus-5`. Override with
`--model`.

## 5. What is left out, and why

- **Skill selection by a real LLM** — only covered by `--live`, which costs API calls.
  The offline suite validates the mechanics, not the model's judgment.
- **`StateBackend` / `StoreBackend` / `CompositeBackend`** — the prototype uses
  `FilesystemBackend` because skills on disk are the case being studied. Libraries
  isolated per tenant or user would need a store and would shift the focus.
- **Running scripts in a sandbox** — the documentation is explicit: reading a script
  works on any backend, *executing* one requires a sandbox backend. Here
  `scripts/calc.py` is loaded as the implementation of the `calculate` tool, which
  preserves the tested, deterministic logic but is not the same as the agent running
  the script inside a container.
