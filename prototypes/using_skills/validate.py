"""Valida o uso de skills no harness.

Modos:
  python validate.py            -> OFFLINE: modelos roteirizados (sem API key). Valida a
                                   mecânica do harness: descoberta (nível 1), leitura do
                                   SKILL.md (nível 2), recurso de apoio (nível 3), isolamento
                                   de skills entre orquestrador e subagente, e permissão read-only.
  python validate.py --live     -> LIVE: usa um LLM real (ANTHROPIC_API_KEY) e verifica se o
                                   modelo ESCOLHE sozinho as skills certas.
"""
from __future__ import annotations

import sys
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent import build_agent

ORCH = "/skills/orquestrador"
ANA = "/skills/analista"


# ---------------------------------------------------------------- fake model
class ScriptedModel(BaseChatModel):
    """Modelo falso: devolve passos pré-definidos e grava o system prompt recebido."""

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
    print(f"  [{'OK' if cond else 'FALHOU'}] {name}")


# ---------------------------------------------------------------- offline
def offline():
    orch = ScriptedModel(steps=[
        ("read_file", {"file_path": f"{ORCH}/planejamento-viagem/SKILL.md"}),
        ("task", {"subagent_type": "analista", "description": "Calcule o orçamento: 2 diárias de 300 + 4 refeições de 80."}),
        ("write_file", {"file_path": f"{ORCH}/planejamento-viagem/SKILL.md", "content": "hack"}),
        "Dia 1: ... Dia 2: ... Orçamento total: 920. [skill:planejamento-viagem]",
    ], seen_prompts=[])
    ana = ScriptedModel(steps=[
        ("read_file", {"file_path": f"{ANA}/analise-numerica/SKILL.md"}),
        ("calcular", {"expressao": "2*300 + 4*80"}),
        "2*300 + 4*80 = 920 [skill:analise-numerica]",
    ], seen_prompts=[])

    agent = build_agent(model=orch, analista_model=ana)
    out = agent.invoke(
        {"messages": [{"role": "user", "content": "Roteiro de 2 dias em Salvador com orçamento"}]},
        config={"configurable": {"thread_id": "offline"}},
    )
    msgs = out["messages"]
    calls, res = tool_calls(msgs), tool_results(msgs)
    by_name = {tc["name"]: tc for tc in calls}

    print("\nNível 1 — descoberta (metadados no system prompt)")
    p0 = orch.seen_prompts[0]
    check("orquestrador vê 'resumo-executivo'", "resumo-executivo" in p0)
    check("orquestrador vê 'planejamento-viagem'", "planejamento-viagem" in p0)
    check("orquestrador NÃO vê 'analise-numerica' (isolamento)", "analise-numerica" not in p0)
    check("corpo do SKILL.md NÃO está no prompt (progressive disclosure)", "Termine SEMPRE" not in p0)
    a0 = ana.seen_prompts[0]
    check("analista vê 'analise-numerica'", "analise-numerica" in a0)
    check("analista NÃO vê skills do orquestrador", "planejamento-viagem" not in a0)

    print("\nNível 2 — ativação (read_file do SKILL.md)")
    rf = res[by_name["read_file"]["id"]]
    check("read_file retornou as instruções da skill", "delegue os cálculos" in rf)

    print("\nDelegação + skill do subagente")
    task_out = res[by_name["task"]["id"]]
    check("subagente usou calcular e devolveu 920", "920" in task_out)
    check("resposta do subagente traz marcador da skill", "[skill:analise-numerica]" in task_out)

    print("\nPermissões")
    wf = res[by_name["write_file"]["id"]]
    check("escrita em /skills/** bloqueada", "hack" not in open("skills/orquestrador/planejamento-viagem/SKILL.md").read())
    print(f"     (mensagem do harness: {wf[:90]!r})")

    print("\nResposta final")
    check("marcador [skill:planejamento-viagem] na resposta", "[skill:planejamento-viagem]" in msgs[-1].content)


# ---------------------------------------------------------------- live
CASES = [
    ("Resuma para a diretoria: o projeto X atrasou 2 semanas por falta de QA, "
     "o custo subiu 10% e o cliente pediu nova demo na sexta.", "resumo-executivo", None),
    ("Monte um roteiro de 2 dias em Salvador com orçamento: 2 diárias de 300 e 4 refeições de 80.",
     "planejamento-viagem", "analise-numerica"),
    ("Qual é a capital da França? Responda em uma palavra.", None, None),  # controle: nenhuma skill
]


def live(model: str):
    for i, (prompt, skill, sub_skill) in enumerate(CASES):
        print(f"\nCaso {i + 1}: {prompt[:60]}...")
        agent = build_agent(model=model)
        out = agent.invoke({"messages": [{"role": "user", "content": prompt}]},
                           config={"configurable": {"thread_id": f"live-{i}"}})
        msgs = out["messages"]
        calls = tool_calls(msgs)
        read = [tc["args"].get("file_path", "") for tc in calls if tc["name"] == "read_file"]
        final = msgs[-1].content if isinstance(msgs[-1].content, str) else str(msgs[-1].content)
        if skill:
            check(f"leu {skill}/SKILL.md", any(f"{skill}/SKILL.md" in p for p in read))
            check(f"marcador [skill:{skill}] na resposta", f"[skill:{skill}]" in final)
        else:
            check("nenhuma skill ativada (caso controle)", not any("SKILL.md" in p for p in read))
        if sub_skill:
            task_out = " ".join(str(m.content) for m in msgs if isinstance(m, ToolMessage) and m.name == "task")
            check("delegou ao subagente analista", any(tc["name"] == "task" for tc in calls))
            check(f"subagente aplicou {sub_skill}", f"[skill:{sub_skill}]" in task_out)
        print("  resposta:", final[:200].replace("\n", " "), "...")


if __name__ == "__main__":
    if "--live" in sys.argv:
        live(sys.argv[sys.argv.index("--live") + 1] if len(sys.argv) > sys.argv.index("--live") + 1
             else "anthropic:claude-sonnet-4-6")
    else:
        offline()
    ok = sum(r for _, r in results)
    print(f"\n{ok}/{len(results)} verificações OK")
    sys.exit(0 if ok == len(results) else 1)
