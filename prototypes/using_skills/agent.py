"""Agente harness (Deep Agents) com orquestrador + skills + subagente especialista.

Arquitetura:
  orquestrador (create_deep_agent)
    ├─ skills: /skills/orquestrador/   -> resumo-executivo, planejamento-viagem
    ├─ tools do harness: ls, read_file, glob, grep, write_file, edit_file, task
    └─ subagente "analista" (contexto isolado)
         ├─ skills: /skills/analista/  -> analise-numerica
         └─ tools: calcular
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from dotenv import load_dotenv

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver

load_dotenv()  # carrega variáveis de ambiente do .env

ROOT = Path(__file__).resolve().parent

# Reaproveita o script da própria skill como implementação da tool (lógica testada, determinística).
_spec = importlib.util.spec_from_file_location(
    "calc", ROOT / "skills/analista/analise-numerica/scripts/calc.py"
)
_calc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_calc)


def calcular(expressao: str) -> str:
    """Avalia uma expressão aritmética (+ - * / ** %) e devolve o resultado."""
    try:
        return str(_calc.safe_eval(expressao))
    except Exception as e:  # erro legível para o modelo
        return f"ERRO: {e}"


ORCH_PROMPT = """Você é um ORQUESTRADOR. Regras:
- Antes de responder, verifique se alguma skill disponível se aplica ao pedido; se sim,
  leia o SKILL.md dela com read_file e siga as instruções.
- Delegue qualquer cálculo ao subagente `analista` usando a ferramenta `task`.
- Responda em português."""

ANALISTA = {
    "name": "analista",
    "description": "Especialista em contas, orçamentos e estatística. Use para qualquer cálculo.",
    "system_prompt": "Você é um analista numérico. Consulte suas skills antes de agir. Responda em português.",
    "tools": [calcular],
    "skills": ["/skills/analista/"],  # subagente custom NÃO herda skills do pai
}


def build_agent(model="anthropic:claude-sonnet-4-6", analista_model=None):
    backend = FilesystemBackend(root_dir=str(ROOT), virtual_mode=True)
    analista = dict(ANALISTA)
    if analista_model is not None:
        analista["model"] = analista_model
    return create_deep_agent(
        model=model,
        system_prompt=ORCH_PROMPT,
        backend=backend,
        skills=["/skills/orquestrador/"],
        subagents=[analista],
        # skills são somente-leitura para o agente
        permissions=[FilesystemPermission(operations=["write"], paths=["/skills/**"], mode="deny")],
        checkpointer=MemorySaver(),
        name="orquestrador",
    )


if __name__ == "__main__":
    import sys

    agent = build_agent()
    pergunta = " ".join(sys.argv[1:]) or "Monte um roteiro de 2 dias em Salvador com orçamento: 2 diárias de 300 e 4 refeições de 80."
    out = agent.invoke(
        {"messages": [{"role": "user", "content": pergunta}]},
        config={"configurable": {"thread_id": "demo"}},
    )
    print(out["messages"][-1].content)

# python -m prototypes.using_skills.agent