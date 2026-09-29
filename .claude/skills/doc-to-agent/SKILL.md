---
name: doc-to-agent
description: >-
  Turns a documentation page (usually a LangChain Deep Agents doc saved as .md/.mdx
  inside a prototypes/ folder) into a runnable prototype agent in that same folder:
  agent.py, the standard run_agent.py CLI (one-shot or --chat), and the support files
  the agent needs, putting every topic of the doc into practice. Use whenever the user
  gives a path to a doc and wants an agent, a prototype, a practical example or a
  playground built from it ("crie o agente dessa doc", "gera o protótipo de
  prototypes/using_memory/memory_doc.md"), or wants to regenerate one of the
  prototypes/ agents from its doc — even if they only paste the path. Also produces a
  USAGE.md next to the agent with how to run the CLI and example prompts to try.
---

# doc-to-agent

The user studies Deep Agents one doc page at a time. For each page they create a
folder in `prototypes/` holding the doc, and a real agent that puts every topic of
that page into practice, runnable normally (`python -m prototypes.<folder>.run_agent`)
or through the CLI (`run_agent.py --chat ...`). This skill builds that agent.

A prototype succeeds on two counts:

1. **Coverage.** Every topic of the doc shows up as a working mechanism in the agent,
   or is set aside with a stated reason. The user will hold the doc next to the code.
2. **Observability.** Running it, you can *see* each mechanism fire: markers in the
   answer, highlighted tool calls, chat commands that inspect and toggle state.

## Inputs and outputs

- **Input**: the path to a doc file. The target folder is the doc's parent directory.
- **Output**, in that folder: `agent.py`, `run_agent.py`, `USAGE.md` (how to run it
  plus prompts to try — step 7), and only the support files the agent reads or runs
  (skills, memory files, data, scripts). No plan, report or test file alongside these
  — the user deliberately removed those from the first prototype; `USAGE.md` is the
  one write-up they do want, since it is what they open before every run. The doc
  itself is never modified.
- If `agent.py` or `run_agent.py` already exists, ask before overwriting, unless the
  user asked to regenerate.

Write code, prompts, comments and skill files in English, like the rest of the repo.
Talk to the user in the language they wrote in.

Run Python through the project's environment from the repo root:
`.venv/Scripts/python.exe` on Windows (or `uv run python`). In the commands below,
`<skill-dir>` is this skill's directory (`.claude/skills/doc-to-agent/` in this repo)
and `<scratchpad>` is your scratchpad or a temp dir — working files never go in the
prototype folder.

## Workflow

### 1. Read the whole doc

The generated agent can only be as complete as your reading of the doc, so read all
of it, not a skim of the headings. LangChain pages repeat each example once per model
provider, which can double their length; condense first:

```bash
.venv/Scripts/python.exe <skill-dir>/scripts/condense_doc.py <doc> -o <scratchpad>/condensed.md
```

It keeps one variant (Anthropic when present) of each near-identical group, leaves all
prose, notes and distinct code untouched, and prints the outline plus the links to
other doc pages. Then read the condensed file from top to bottom in chunks.

As you read, build the **topic inventory** in `<scratchpad>/coverage.md`. A topic is
anything the doc teaches that could be shown working:

- each section and subsection;
- each piece of API: parameters, classes, functions, config and state keys;
- each behavioral rule, especially those in `<Note>`, `<Warning>`, `<Tip>` and
  `<Info>` callouts — "use `None`, not an empty list", "custom subagents do not
  inherit", "last one wins". These subtle rules are what the user most needs to see
  happen;
- version requirements (`requires deepagents>=0.7.16`);
- each troubleshooting entry: a failure mode the agent can make visible or avoid;
- reference tables.

One row per topic: `| # | doc section | topic | how the agent shows it | where |`.
Leave the last two columns empty for now.

Stay within this page: linked pages are the subject of other prototypes. When a
detail the page leaves out is needed to make something run, get it from the installed
package source (step 2), not the web.

### 2. Check the API against the installed package

The doc may be ahead of or behind the installed `deepagents`. Before relying on any
symbol, confirm it exists:

```bash
.venv/Scripts/python.exe -c "import importlib.metadata as m; print(m.version('deepagents'))"
.venv/Scripts/python.exe -c "import inspect; from deepagents import create_deep_agent; print(inspect.signature(create_deep_agent))"
```

and grep `.venv/Lib/site-packages/deepagents/` (or `langchain/`, `langgraph/`) for
anything else. If the doc needs a newer version than the one installed, tell the user
and let them decide on the upgrade. Likewise, ask before adding a package to
`pyproject.toml`; a local stand-in usually demonstrates the same mechanism. Check
which API keys `.env` defines by name only — never print their values.

### 3. Design the scenario

Read `references/conventions.md` now; it defines the structure every prototype
follows and shows how the skills doc was mapped onto code.

- **One coherent mini-domain** in which every topic has a natural job (the skills
  prototype: an orchestrator planning trips, summarizing reports, delegating math to
  an analyst). A realistic task makes the mechanisms meaningful; a zoo of unrelated
  toys, one per feature, does not.
- **Every inventory row gets a runtime role**: something the agent does, a
  configuration it runs under, or a command that shows it. A comment saying "this
  demonstrates X" is not a demonstration.
- **Alternatives become options.** When the doc presents variants of one thing
  (backends, permission modes, sources), expose them as a `build_agent` option plus a
  CLI flag plus a chat command, so the user can switch and compare in one session.
- **Emulate what needs infrastructure you lack.** A LangSmith deployment, a remote
  sandbox or an auth server usually has a local equivalent that exercises the same
  API: `InMemoryStore` for a deployment's store, a `context` object for auth claims,
  `LocalShellBackend` (check it exists) for a sandbox. Say in a comment what the local
  piece stands in for. Leave a topic out only when no faithful local version exists,
  and record why.
- **Make each mechanism observable** with the patterns in the conventions: markers,
  the `◆` highlight for the doc's central event, inspect/toggle/reset commands.
- **Pick a default prompt** that exercises as many topics as possible in one
  unattended one-shot run, and plan three or four chat prompts for the rest,
  including one control prompt that should trigger none of the mechanisms.

Draw the architecture tree for the `agent.py` docstring before writing code. If it
will not come out clean, simplify the design.

### 4. Write `agent.py`

Follow `references/conventions.md` section 2: docstring with the tree, tools,
prompts, subagents, option tables, `DEFAULT_MODEL`, a `build_agent()` whose options
all have defaults, `MemorySaver`, and the trailing usage string with the real folder
name and flags.

### 5. Write `run_agent.py`

Copy `assets/run_agent_template.py` into the folder and fill in the `ADAPT` spots
listed in its header: imports, tool colors and legend, option colors and labels,
subtitle, key-event highlight, chat commands, default prompt, CLI flags. Then delete
the template notes and every `ADAPT` comment. Keep the engine functions as they are:
the user wants every prototype's CLI to look and behave the same.

### 6. Write the support files

Skills, memory files, data, scripts — see conventions section 5. Each `SKILL.md`
`name` must equal its directory name, or Deep Agents silently skips it.

### 7. Write `USAGE.md`

A short guide the user opens before every run — they will not remember which flags
and chat commands this particular prototype has, or what to type at the prompt to see
something happen. Keep it scannable, not a rewrite of the doc. Structure:

```md
# <topic> — usage

<one or two sentences: what this prototype demonstrates and its architecture in short>

## Run

Normal:
    python -m prototypes.<folder>.run_agent

CLI:
    python prototypes/<folder>/run_agent.py [flags]
    python prototypes/<folder>/run_agent.py --chat [flags]

Flags:
- `--model <provider:model>` — default <DEFAULT_MODEL>
- `--<flag> <choices>` — one line per option table in agent.py, saying what each choice does

## Chat commands

- `/help`
- one line per command added in run_agent.py, same wording as its HELP string

## Prompts to try

1. "<default prompt>" — exercises: <topics>. Expect: <marker or ◆ highlight to look for>.
2. "<prompt>" — exercises: <topics>. Expect: ...
3. "<prompt>" — exercises: <topics>. Expect: ...
4. "<control prompt>" (control) — should trigger no skill/mechanism. Expect: a plain answer, no markers.
```

Reuse the prompts and coverage decided in step 3 — this file is where they become
something the user actually runs, not new material to invent. If a mechanism needs a
specific chat sequence to see (e.g. switch `/mode` then retry a write), spell out the
sequence as one numbered prompt entry.

### 8. Verify

1. Offline smoke test — no API key needed:

   ```bash
   .venv/Scripts/python.exe <skill-dir>/scripts/smoke_test.py prototypes/<folder>
   ```

   It compiles every file, builds the agent with a fake model and runs one turn,
   prints the tools and system-prompt size the model received, runs
   `run_agent.py --help`, flags leftover `ADAPT` markers, and validates every
   `SKILL.md`. Add `--prompt` to print the system prompt and confirm that skills,
   memory or subagents appear in it. Fix every failure before going on.
2. A live run from the repo root, when `ANTHROPIC_API_KEY` is set: run
   `.venv/Scripts/python.exe -m prototypes.<folder>.run_agent` once (the default
   one-shot, which also proves the `python -m` entry point works). It costs one
   real run and is the only proof that the model actually uses the mechanisms. Check
   that the expected markers appear. If a mechanism did not fire, apply the doc's own
   advice (usually a sharper skill description or a clearer prompt rule), then rerun.
   If the run fails for reasons outside the code (quota, network), report that rather
   than changing the code.
3. Walk `coverage.md`: every row has a "where" (file and line, or CLI command) or a
   stated reason for leaving it out.
4. Reread `USAGE.md` as if you were the user: does every flag and command it lists
   still match `run_agent.py`? Does every prompt still make sense given the final
   `agent.py`? Fix drift before reporting.

### 9. Report

Reply in the chat, in the user's language — a summary that points at the files rather
than re-explaining them:

- the folder tree that was created;
- the coverage table — doc section → how the agent shows it → where; then the topics
  left out, each with its reason;
- a pointer to `USAGE.md` for how to run it and what to try, not a restatement of it;
- what was verified (smoke test, live run and its markers) and anything that was not.
