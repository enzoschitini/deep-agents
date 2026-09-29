# Prototype conventions

How every prototype in `prototypes/` is laid out, extracted from the reference
implementation `prototypes/using_skills/` (read its `agent.py` and `run_agent.py` too
when they exist — they are the living example of everything below).

## Contents
1. Folder layout
2. `agent.py` anatomy
3. Observability patterns
4. `run_agent.py`
5. Support files
6. Worked example: the skills doc

---

## 1. Folder layout

```
prototypes/<folder>/
├── <topic>_doc.md      the source doc — never modified
├── agent.py            the agent definition only
├── run_agent.py        the standard CLI, filled in from assets/run_agent_template.py
├── USAGE.md            how to run it + prompts to try (SKILL.md step 7)
└── ...                 only what the agent reads or runs: skills/, AGENTS.md,
                        memories/, data files, scripts
```

No plan, report or test file: the user removed those from the first prototype on
purpose, and the explanation belongs in the docstrings and comments instead.
`USAGE.md` is the one exception — a short, generated write-up of how to run the CLI
and what to type at it, which the user reopens every time rather than re-deriving it
from `agent.py`. The folder name must be a valid Python identifier (`using_memory`,
not `using-memory`) for `python -m prototypes.<folder>.run_agent` to work.

## 2. `agent.py` anatomy

In this order:

**Module docstring.** A one-line summary naming the doc's topic, then an
`Architecture:` tree of the agent (main agent, subagents, skills, tools, backend
routes), then one short paragraph per option saying what each value demonstrates, and
it ends with: *This module only defines the agent. Running it — one-shot or as a
terminal chat — lives in run_agent.py.* The tree is the first thing a reader sees, so
draw it before writing code; if it will not come out clean, the design is too tangled.

```python
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
```

**Imports and setup.** `from __future__ import annotations`; stdlib, third-party and
`deepagents` groups; then

```python
load_dotenv()  # loads environment variables from .env

ROOT = Path(__file__).resolve().parent
```

**Tools.** Plain functions. The docstring is the description the model sees, so write
it for the model. Return `str`; turn exceptions into `f"ERROR: {e}"` so the model can
recover instead of the run crashing. When a skill ships a script with the same logic,
load that script with `importlib` and reuse it as the tool's implementation — script
and tool then cannot drift apart.

**Prompts.** `UPPER_CASE` string constants. Short, and limited to the rules that make
the doc's behaviors happen (e.g. "before answering, check whether a skill applies";
"delegate any arithmetic to the `analyst` subagent").

**Subagents.** Dict constants (`name`, `description`, `system_prompt`, `tools`, and
whatever the doc covers such as `skills`), with an inline comment on the doc rule each
key demonstrates:

```python
    "skills": ["/skills/analyst/"],  # custom subagents do NOT inherit the parent's skills
```

**Option tables.** Each variant the doc presents as an alternative becomes a dict from
the CLI value to what `build_agent` uses, one comment per entry saying what it shows.
`run_agent.py` imports these tables for argparse `choices` and chat commands.

```python
# Effect of the write rule over /skills/** in each mode.
PERMISSION_MODES = {
    "deny": "deny",           # read-only skills: a curated library (default)
    "interrupt": "interrupt",  # writes pause for human approval
    "writable": "allow",      # the agent may create and refine its own skills
}
```

**Model.** `DEFAULT_MODEL = "anthropic:claude-sonnet-5"`. The repo's `.env` carries an
Anthropic key; translate examples written for other providers.

**`build_agent()`** — the only factory:

```python
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
        permissions=[...],
        checkpointer=MemorySaver(),
        name="orchestrator",
    )
```

- `model` accepts a provider string or a `BaseChatModel` instance (the smoke test and
  any scripted test pass a fake model). `<subagent>_model=None` lets tests script each
  subagent separately; copy the subagent dict before injecting it.
- Every option has a default, so `build_agent(model=...)` alone works, and the defaults
  let a one-shot run finish unattended — approval pauses are opt-in through a flag.
- `checkpointer=MemorySaver()` always: chat threads and interrupts need it.
- `FilesystemBackend(root_dir=str(ROOT), virtual_mode=True)` is the default backend:
  virtual paths such as `/skills/` resolve inside the prototype folder, the files on
  disk are part of the study material, and the agent cannot write outside the folder.
  When the doc is about other backends, those become an option instead.

**Trailing usage string.** The file ends with a bare string literal showing both ways
to run:

```python
"""
1. Normal execution:
python -m prototypes.using_skills.run_agent

2. CLI usage:
python prototypes/using_skills/run_agent.py --chat --mode interrupt --model anthropic:claude-sonnet-5
"""
```

**Comments.** Sparse. A comment earns its place by tying a line to the doc rule it
demonstrates, in the doc's own terms. Do not narrate what the code plainly does.

## 3. Observability patterns

The user learns by watching the agent run, so each mechanism has to be visible from
the terminal, not only true in the code.

- **Markers.** Instructions the agent follows (a `SKILL.md`, a subagent prompt) end with
  "ALWAYS end with the line `[kind:name]`", e.g. `[skill:trip-planning]`. The CLI paints
  any `[word:name]` marker green, so the final answer shows which pieces fired.
- **Transcript.** The chat echoes every tool call (`→ read_file(...)`,
  `→ task(analyst: ...)`) and result. Pick tool and argument names that read well there.
- **Key-event highlight.** `_fmt_call` in `run_agent.py` appends a `◆ ...` note at the
  moment the doc's central mechanism fires (`◆ activating trip-planning` when a
  `SKILL.md` is read). Choose the equivalent event for the new doc.
- **Inspect commands.** A chat command per piece of state the doc talks about
  (`/skills` prints `skills_metadata`; a memory doc might get `/memory`).
- **Toggle commands.** A chat command per option (`/mode <value>`), which rebuilds the
  agent and says "(conversation restarted)".
- **Reset commands** for anything the doc says is cached per thread (`/reset` clears
  `skills_metadata` to `None`).

## 4. `run_agent.py`

Copy `assets/run_agent_template.py` and fill in only the spots marked `ADAPT`; the
header of the template lists them. Then delete the template notes and every `ADAPT`
comment — the finished file should read as if written by hand, like
`prototypes/using_skills/run_agent.py`. Leave the engine functions (`paint`,
`use_utf8`, `message_text`, `print_banner`, `_echo`, `_ask_decisions`, `turn`,
`one_shot`) as they are, so every prototype looks and behaves the same.

When the doc needs something the engine lacks (printing a `structured_response`,
streaming custom events, an async agent), extend the engine minimally and in the same
style, rather than rewriting it.

## 5. Support files

- **Skills**: `skills/<source>/<skill-name>/SKILL.md` with frontmatter whose `name`
  equals the directory name (otherwise Deep Agents skips the skill silently), a
  specific description (what + when + keywords), numbered instructions, and a marker
  line. Reference each supporting file from the body with what it holds and when to
  read it.
- **Scripts**: self-contained, stdlib only where possible, runnable directly
  (`if __name__ == "__main__":`).
- **Data and references**: small and realistic — just enough for the scenario.
- Anything the agent may write at runtime (scratch files, created skills) goes to a
  path the demo expects, so reruns stay clean.

## 6. Worked example: the skills doc

How `prototypes/using_skills/` maps the skills doc onto code — the quality bar for
turning prose into mechanisms:

| Doc section | How the prototype shows it |
|---|---|
| Usage: skill dirs, `SKILL.md`, `skills=[...]` | `skills/orchestrator/` and `skills/analyst/` source dirs, passed to the main agent and to the subagent |
| How skills work — level 1, metadata | `/skills` lists `skills_metadata`; the prompt carries only name + description |
| Level 2, reading `SKILL.md` | `◆ activating <skill>` in the transcript; `[skill:name]` marker in the answer |
| Level 3, resources on demand | `executive-summary` opens `references/template.md` only when its instructions say so |
| Write effective skills | three short skills with specific, non-overlapping descriptions |
| Skills for subagents | custom `analyst` has its own skill source (no inheritance); the general-purpose subagent inherits the parent's |
| Skill permissions (read-only / writable / approval) | `--mode deny\|interrupt\|writable` and `/mode` swap one `FilesystemPermission` over `/skills/**` |
| Reload skills | `/reset` sets `skills_metadata` to `None` (not `[]`) |
| Execute code with skills | `scripts/calc.py` is reused as the `calculate` tool, since running scripts needs a sandbox |
| Troubleshooting | the markers and transcript make "skill not activated" visible at a glance |

That prototype also left topics out — `StateBackend`/`StoreBackend`, per-tenant
libraries through `CompositeBackend`, selecting skills by context. Those can run
locally (`InMemoryStore`, a `--role` option, a routed backend), so a new generation of
it should cover them rather than skip them.
