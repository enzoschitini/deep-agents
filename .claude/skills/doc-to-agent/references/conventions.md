# Prototype conventions

How every prototype in `prototypes/` is laid out, extracted from the reference
implementation `prototypes/using_skills/` (read its modules too when they exist — they
are the living example of everything below).

## Contents
1. Folder layout
2. Module anatomy
3. Language split
4. Observability patterns
5. `run_agent.py`
6. Support files
7. Worked example: the skills doc

---

## 1. Folder layout

One responsibility per file. `agent.py` is the heart of the agent: it says what the
agent *is* — architecture, defaults, wiring — and imports everything else.

```
prototypes/<folder>/
├── <topic>_doc.md      the source doc — never modified
├── schemas.py          context schema and structured-output models (only if used)
├── tools.py            the tool functions
├── prompts.py          every prompt constant (Portuguese)
├── subagents.py        subagent dicts and prebuilt graph factories
├── options.py          the option tables the doc's alternatives become
├── agent.py            architecture docstring, DEFAULT_MODEL, build_agent() — nothing else
├── run_agent.py        the standard CLI, filled in from assets/run_agent_template.py
├── usage.md            how to run it + prompts to try (SKILL.md step 7)
└── ...                 only what the agent reads or runs: skills/, AGENTS.md,
                        memories/, data files, scripts
```

Only the modules the doc needs get created: no subagents in the doc, no
`subagents.py`; no alternatives, no `options.py`. But a file never mixes two of these
concerns — that is the whole point of the split. `agent.py` stays under ~120 lines;
any other module passing ~200 lines is split by responsibility (`tools_logs.py` +
`tools_metrics.py`, one prompts module per role) instead of growing.

The usage file is `usage.md`, lowercase. No plan, report or test file: the user removed
those from the first prototype on purpose, and the explanation belongs in the
docstrings and comments instead. `usage.md` is the one exception — a short, generated
write-up of how to run the CLI and what to type at it, which the user reopens every
time rather than re-deriving it from the code.

The folder name must be a valid Python identifier (`using_memory`, not `using-memory`)
for `python -m prototypes.<folder>.run_agent` to work.

**Imports between the modules.** Siblings are imported as top-level modules
(`from prompts import COORDINATOR_PROMPT`). `agent.py` is the only file that
bootstraps `sys.path`, right above its local imports, so `python -m
prototypes.<folder>.run_agent`, `python run_agent.py` and the smoke test all resolve
the same way:

```python
# `python -m ...` puts the CWD on sys.path, not this directory, so `prompts` would not resolve.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from options import PERMISSION_MODES  # noqa: E402
from prompts import ORCHESTRATOR_PROMPT  # noqa: E402
from subagents import ANALYST  # noqa: E402
from tools import calculate  # noqa: E402
```

Dependencies run one way: `schemas` ← `tools` ← `subagents` → `prompts`, and
`agent.py` on top of all of them. A cycle means two files are sharing one
responsibility.

## 2. Module anatomy

### `agent.py`

**Module docstring.** A one-line summary naming the doc's topic, then an
`Architecture:` tree of the agent (main agent, subagents, skills, tools, backend
routes), then one short paragraph per option saying what each value demonstrates, and
it ends with: *This module only wires the agent together. Prompts, tools, subagents
and options live in their own modules; running it — one-shot or as a terminal chat —
lives in run_agent.py.* The tree is the first thing a reader sees, so draw it before
writing code; if it will not come out clean, the design is too tangled.

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

This module only wires the agent together. Prompts, tools, subagents and options live
in their own modules; running it lives in run_agent.py.
"""
```

Then, in this order: `from __future__ import annotations`; stdlib, third-party and
`deepagents` imports; the `sys.path` bootstrap and the local imports (section 1);

```python
load_dotenv()  # loads environment variables from .env

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "anthropic:claude-sonnet-5"
```

`DEFAULT_MODEL` stays here (`run_agent.py` and the smoke test read it from `agent`),
and **`build_agent()`** is the only factory:

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
- Small wiring helpers that exist only to serve `build_agent` (applying an option to a
  subagent dict, building a permission list) may stay here. Anything with a life of
  its own goes to its module.

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

### `tools.py`

Plain functions. The docstring is the description the model sees, so write it for the
model, in Portuguese. Return `str`; turn exceptions into `f"ERROR: {e}"` so the model
can recover instead of the run crashing. When a skill ships a script with the same
logic, load that script with `importlib` and reuse it as the tool's implementation —
script and tool then cannot drift apart. Tools that need the run's context take a
`ToolRuntime[...]` parameter typed with the schema from `schemas.py`.

### `prompts.py`

`UPPER_CASE` string constants, nothing else — no imports from the other prototype
modules, so prompts can be read on their own. Short, and limited to the rules that
make the doc's behaviors happen (e.g. "antes de responder, verifique se alguma skill
se aplica"; "delegue qualquer cálculo ao subagente `analyst`"), plus the language rule
(section 3) and the observability marker (section 4).

### `subagents.py`

Dict constants (`name`, `description`, `system_prompt`, `tools`, and whatever the doc
covers such as `skills`), importing their prompts from `prompts.py` and their tools
from `tools.py`, with an inline comment on the doc rule each key demonstrates:

```python
    "skills": ["/skills/analyst/"],  # custom subagents do NOT inherit the parent's skills
```

Factories for prebuilt graphs (`def _timeline_builder(model): ...`) live here too.

### `options.py`

Each variant the doc presents as an alternative becomes a dict from the CLI value to
what `build_agent` uses, one comment per entry saying what it shows. Both `agent.py`
and `run_agent.py` import these tables — `run_agent.py` for argparse `choices` and
chat commands.

```python
# Effect of the write rule over /skills/** in each mode.
PERMISSION_MODES = {
    "deny": "deny",            # read-only skills: a curated library (default)
    "interrupt": "interrupt",  # writes pause for human approval
    "writable": "allow",       # the agent may create and refine its own skills
}
```

### `schemas.py`

The `context_schema` dataclass and the Pydantic models for structured output, with a
comment tying each field to the doc rule it comes from. Created only when the doc
covers them.

**Comments** everywhere are sparse. A comment earns its place by tying a line to the
doc rule it demonstrates, in the doc's own terms. Do not narrate what the code plainly
does.

## 3. Language split

The agent speaks Portuguese (pt-BR); the code is English. SKILL.md's *Language rules*
section is the authority; in terms of files:

| File | Portuguese | English |
|---|---|---|
| `prompts.py` | every string | constant names, comments |
| `tools.py` | docstrings (the model reads them) | names, signatures, `ERROR:` prefixes, comments |
| `subagents.py` | `description` and `system_prompt` values | `name`, dict keys, tool names, comments |
| `options.py` | — | keys, values, comments (CLI values are flags) |
| `agent.py` | — | docstring and architecture tree, identifiers, comments |
| `run_agent.py` | subtitle, `HELP`, notices, approval question, argparse texts | flags, command names, function names, comments |
| `skills/**/SKILL.md` | `description` and body | `name` (= directory name), file paths, marker |
| `usage.md` | all of it | commands, flags, file, tool and option names, markers |

Each main prompt ends up carrying a line such as `Responda sempre em português do
Brasil.`, so the agent's own answers are Portuguese too. Observability markers stay in
their English slug form (`[skill:trip-planning]`) because `run_agent.py` matches them
with a regex.

## 4. Observability patterns

The user learns by watching the agent run, so each mechanism has to be visible from
the terminal, not only true in the code.

- **Markers.** Instructions the agent follows (a `SKILL.md`, a subagent prompt) end with
  "termine SEMPRE com a linha `[kind:name]`", e.g. `[skill:trip-planning]`. The CLI
  paints any `[word:name]` marker green, so the final answer shows which pieces fired.
- **Transcript.** The chat echoes every tool call (`→ read_file(...)`,
  `→ task(analyst: ...)`) and result. Pick tool and argument names that read well there.
- **Key-event highlight.** `_fmt_call` in `run_agent.py` appends a `◆ ...` note at the
  moment the doc's central mechanism fires (`◆ ativando trip-planning` when a
  `SKILL.md` is read). Choose the equivalent event for the new doc.
- **Inspect commands.** A chat command per piece of state the doc talks about
  (`/skills` prints `skills_metadata`; a memory doc might get `/memory`).
- **Toggle commands.** A chat command per option (`/mode <value>`), which rebuilds the
  agent and says "(conversa reiniciada)".
- **Reset commands** for anything the doc says is cached per thread (`/reset` clears
  `skills_metadata` to `None`).

## 5. `run_agent.py`

Copy `assets/run_agent_template.py` and fill in only the spots marked `ADAPT`; the
header of the template lists them. Then delete the template notes and every `ADAPT`
comment — the finished file should read as if written by hand, like
`prototypes/using_skills/run_agent.py`. Leave the engine functions (`paint`,
`use_utf8`, `message_text`, `print_banner`, `_echo`, `_ask_decisions`, `turn`,
`one_shot`) as they are, so every prototype looks and behaves the same — their
user-facing strings are already Portuguese in the template.

It imports `DEFAULT_MODEL` and `build_agent` from `agent`, and the option tables from
`options`. When the doc needs something the engine lacks (printing a
`structured_response`, streaming custom events, an async agent), extend the engine
minimally and in the same style, rather than rewriting it.

## 6. Support files

- **Skills**: `skills/<source>/<skill-name>/SKILL.md` with frontmatter whose `name`
  equals the directory name (otherwise Deep Agents skips the skill silently), a
  specific Portuguese description (what + when + keywords), numbered instructions, and
  a marker line. Reference each supporting file from the body with what it holds and
  when to read it.
- **Scripts**: self-contained, stdlib only where possible, runnable directly
  (`if __name__ == "__main__":`). Code and comments in English; anything they print for
  the user, in Portuguese.
- **Data and references**: small and realistic — just enough for the scenario, written
  in Portuguese when the scenario reads them as prose.
- Anything the agent may write at runtime (scratch files, created skills) goes to a
  path the demo expects, so reruns stay clean.

## 7. Worked example: the skills doc

How `prototypes/using_skills/` maps the skills doc onto code — the quality bar for
turning prose into mechanisms:

| Doc section | How the prototype shows it |
|---|---|
| Usage: skill dirs, `SKILL.md`, `skills=[...]` | `skills/orchestrator/` and `skills/analyst/` source dirs, passed to the main agent and to the subagent |
| How skills work — level 1, metadata | `/skills` lists `skills_metadata`; the prompt carries only name + description |
| Level 2, reading `SKILL.md` | `◆ ativando <skill>` in the transcript; `[skill:name]` marker in the answer |
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
