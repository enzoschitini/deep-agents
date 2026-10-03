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
  usage.md next to the agent with how to run the CLI and example prompts to try.
---

# doc-to-agent

The user studies Deep Agents one doc page at a time. For each page they create a
folder in `prototypes/` holding the doc, and a real agent that puts every topic of
that page into practice, runnable normally (`python -m prototypes.<folder>.run_agent`)
or through the CLI (`run_agent.py --chat ...`). This skill builds that agent.

A prototype succeeds on three counts:

1. **Coverage.** Every topic of the doc shows up as a working mechanism in the agent,
   or is set aside with a stated reason. The user will hold the doc next to the code.
2. **Observability.** Running it, you can *see* each mechanism fire: markers in the
   answer, highlighted tool calls, chat commands that inspect and toggle state.
3. **One responsibility per file.** `agent.py` holds only the agent's heart — the
   architecture and `build_agent()`. Prompts, tools, subagents and option tables live
   in their own modules (see *Module layout* below).

## Language rules

The assistant speaks **Portuguese**; the **code is English**. This is not a style
preference, and it is checked in step 8.

**Portuguese (pt-BR)** — everything a human or the model reads as prose:

- every prompt: `system_prompt` constants, each subagent's `system_prompt` *and*
  `description`, tool docstrings (that text *is* the description the model sees);
- `SKILL.md` bodies and their frontmatter `description`; `AGENTS.md`, memory files,
  and any data file whose content is read as prose in the scenario;
- everything printed in the terminal: banner subtitle, `/help` text, notices, errors,
  the approval question, `argparse` descriptions and every `help=` string;
- `usage.md`, and your final report in the chat.

Every main prompt carries an explicit rule so the agent itself answers in Portuguese,
e.g. `Responda sempre em português do Brasil.` A run whose final answer comes back in
English is a bug, not a detail: sharpen the rule and rerun.

**English** — everything the machine reads:

- all identifiers: module, class, function, variable, tool, subagent and option names,
  the keys and values of the option tables, state keys;
- CLI flags (`--chat`, `--mode`), chat commands (`/help`, `/mode`), observability
  markers (`[skill:trip-planning]`);
- code comments and module docstrings, including the `Architecture:` tree;
- file and folder names, and each `SKILL.md` frontmatter `name`;
- anything the `deepagents` API matches literally.

Talk to the user in the language they wrote in.

## Inputs and outputs

- **Input**: the path to a doc file. The target folder is the doc's parent directory.
- **Output**, in that folder: the agent modules of the *Module layout* below,
  `run_agent.py`, `usage.md` (how to run it plus prompts to try — step 7), and only
  the support files the agent reads or runs (skills, memory files, data, scripts). No
  plan, report or test file alongside these — the user deliberately removed those from
  the first prototype; `usage.md` is the one write-up they do want, since it is what
  they open before every run. The doc itself is never modified.
- The usage file is `usage.md`, lowercase, never `USAGE.md`.
- If `agent.py` or `run_agent.py` already exists, ask before overwriting, unless the
  user asked to regenerate.

Run Python through the project's environment from the repo root:
`.venv/Scripts/python.exe` on Windows (or `uv run python`). In the commands below,
`<skill-dir>` is this skill's directory (`.claude/skills/doc-to-agent/` in this repo)
and `<scratchpad>` is your scratchpad or a temp dir — working files never go in the
prototype folder.

## Module layout

One responsibility per file. `agent.py` is the heart: it says what the agent *is*, not
what its pieces contain.

```
prototypes/<folder>/
├── <topic>_doc.md   the source doc — never modified
├── schemas.py       context schema, structured-output models (only if the doc has them)
├── tools.py         the tool functions
├── prompts.py       every prompt constant (Portuguese)
├── subagents.py     subagent dicts and prebuilt graph factories
├── options.py       the option tables the doc's alternatives become
├── agent.py         architecture docstring, DEFAULT_MODEL, build_agent() — nothing else
├── run_agent.py     the standard CLI, filled in from assets/run_agent_template.py
├── usage.md         how to run it + prompts to try (step 7)
└── ...              only what the agent reads or runs: skills/, AGENTS.md, memories/,
                     data files, scripts
```

- Create only the modules the doc needs: a doc with no subagents gets no
  `subagents.py`, one with no alternatives gets no `options.py`. Two tools and one
  prompt do not need splitting — but the moment a file mixes two of these concerns,
  split it.
- **Budget**: `agent.py` stays under ~120 lines. Any other module passing ~200 lines
  gets split by responsibility (`tools.py` → `tools_logs.py` + `tools_metrics.py`,
  `prompts.py` → one module per role) rather than growing.
- Siblings are imported as top-level modules (`from prompts import COORDINATOR_PROMPT`).
  `agent.py` is the only file that bootstraps the path, right above its local imports,
  so `python -m prototypes.<folder>.run_agent`, `python run_agent.py` and the smoke
  test all resolve the same way:

  ```python
  sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

  from options import HANDOFF_MODES  # noqa: E402
  ```
- `run_agent.py` imports `DEFAULT_MODEL` and `build_agent` from `agent`, and the option
  tables from `options`.

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

Draw the architecture tree for the `agent.py` docstring before writing code, and note
which module each piece will live in. If the tree will not come out clean, or a piece
has no obvious module, simplify the design.

### 4. Write the agent modules

Follow `references/conventions.md` section 2, which gives the anatomy of each module.
Write them in dependency order — `schemas.py`, `tools.py`, `prompts.py`,
`subagents.py`, `options.py` — and `agent.py` last, so it only has to wire up what
already exists: the architecture docstring, `DEFAULT_MODEL`, a `build_agent()` whose
options all have defaults, `MemorySaver`, and the trailing usage string with the real
folder name and flags.

If `agent.py` ends up holding a prompt string, a tool body or a subagent dict, it is
in the wrong file: move it and import it.

### 5. Write `run_agent.py`

Copy `assets/run_agent_template.py` into the folder and fill in the `ADAPT` spots
listed in its header: imports, tool colors and legend, option colors and labels,
subtitle, key-event highlight, chat commands, default prompt, CLI flags. Then delete
the template notes and every `ADAPT` comment. Keep the engine functions as they are:
the user wants every prototype's CLI to look and behave the same. Everything you add
that the user will read — subtitle, `/help` lines, notices, flag help — is in
Portuguese; the flags and command names themselves stay English.

### 6. Write the support files

Skills, memory files, data, scripts — see conventions section 5. Each `SKILL.md`
`name` must equal its directory name (English, like the folder), or Deep Agents
silently skips it; its `description` and body are Portuguese.

### 7. Write `usage.md`

Lowercase filename, written **entirely in Portuguese** — only what belongs to the code
stays English: commands, flags, chat commands, file names, tool and option names,
markers. A short guide the user opens before every run: they will not remember which
flags and chat commands this particular prototype has, or what to type at the prompt
to see something happen. Keep it scannable, not a rewrite of the doc. Structure:

```md
# <topic> — uso

<uma ou duas frases: o que este protótipo demonstra e qual é a sua arquitetura>

## Execução

Normal:
    python -m prototypes.<folder>.run_agent

CLI:
    python prototypes/<folder>/run_agent.py [flags]
    python prototypes/<folder>/run_agent.py --chat [flags]

Flags:
- `--model <provider:model>` — padrão <DEFAULT_MODEL>
- `--<flag> <choices>` — uma linha por tabela de opções de options.py, dizendo o que cada valor faz

## Comandos do chat

- `/help`
- uma linha por comando criado em run_agent.py, com a mesma redação do HELP

## Prompts para experimentar

1. "<prompt padrão>" — exercita: <tópicos>. Esperado: <marcador ou destaque ◆ a observar>.
2. "<prompt>" — exercita: <tópicos>. Esperado: ...
3. "<prompt>" — exercita: <tópicos>. Esperado: ...
4. "<prompt de controle>" (controle) — não deve acionar nenhum mecanismo. Esperado: resposta simples, sem marcadores.
```

Reuse the prompts and coverage decided in step 3 — this file is where they become
something the user actually runs, not new material to invent. The prompts themselves
are in Portuguese, since that is what the user will type at the agent. If a mechanism
needs a specific chat sequence to see (e.g. switch `/mode` then retry a write), spell
out the sequence as one numbered prompt entry.

### 8. Verify

1. Offline smoke test — no API key needed:

   ```bash
   .venv/Scripts/python.exe <skill-dir>/scripts/smoke_test.py prototypes/<folder>
   ```

   It compiles every file, builds the agent with a fake model and runs one turn,
   prints the tools and system-prompt size the model received, runs
   `run_agent.py --help`, flags leftover `ADAPT` markers, checks the layout
   (`usage.md` present and lowercase, `agent.py` within budget and free of prompts,
   tools and subagent dicts), and validates every `SKILL.md`. Add `--prompt` to print
   the system prompt and confirm that skills, memory or subagents appear in it. Fix
   every failure before going on.
2. A live run from the repo root, when `ANTHROPIC_API_KEY` is set: run
   `.venv/Scripts/python.exe -m prototypes.<folder>.run_agent` once (the default
   one-shot, which also proves the `python -m` entry point works). It costs one
   real run and is the only proof that the model actually uses the mechanisms. Check
   that the expected markers appear **and that the answer is in Portuguese**. If a
   mechanism did not fire, or the answer came back in English, apply the doc's own
   advice (usually a sharper skill description, prompt rule or language rule), then
   rerun. If the run fails for reasons outside the code (quota, network), report that
   rather than changing the code.
3. Walk `coverage.md`: every row has a "where" (file and line, or CLI command) or a
   stated reason for leaving it out.
4. Reread the layout and the language split: no prompt, tool or subagent left in
   `agent.py`; every prompt, model-facing docstring and terminal string in Portuguese;
   every identifier, flag, comment and marker in English.
5. Reread `usage.md` as if you were the user: does every flag and command it lists
   still match `run_agent.py`? Does every prompt still make sense given the final
   modules? Fix drift before reporting.

### 9. Report

Reply in the chat, in the user's language — a summary that points at the files rather
than re-explaining them:

- the folder tree that was created, one line per module saying what it holds;
- the coverage table — doc section → how the agent shows it → where; then the topics
  left out, each with its reason;
- a pointer to `usage.md` for how to run it and what to try, not a restatement of it;
- what was verified (smoke test, live run and its markers) and anything that was not.
