"""The tools the subagents get. Docstrings are what the model reads, so Portuguese.

`shared_lookup` is deliberately shared between the coordinator and every subagent: it
reads `lc_agent_name` out of the run metadata to find out who called it, and records
each call in a journal the CLI can filter — the local stand-in for filtering runs by
`lc_agent_name` in LangSmith, which the doc does through the SDK.
"""
from __future__ import annotations

from pathlib import Path

from langchain.tools import ToolRuntime, tool

from schemas import IncidentContext

ROOT = Path(__file__).resolve().parent
DEFAULT_LOG_LINES = 12

# One entry per shared_lookup call: (lc_agent_name, query). Module-level because the
# journal is an observability device, not agent state.
_JOURNAL: list[tuple[str, str]] = []


def journal_entries(agent_name: str | None = None) -> list[tuple[str, str]]:
    """Journal rows, optionally only those from one agent.

    Mirrors `has(metadata, '{"lc_agent_name": "<name>"}')` from the doc's SDK filter.
    """
    if agent_name is None:
        return list(_JOURNAL)
    return [row for row in _JOURNAL if row[0] == agent_name]


def clear_journal() -> None:
    _JOURNAL.clear()


def _caller(runtime: ToolRuntime) -> str:
    """Which agent initiated this tool call, from the run metadata."""
    return runtime.config.get("metadata", {}).get("lc_agent_name") or "coordinator"


@tool
def read_incident_log(incident_id: str, runtime: ToolRuntime[IncidentContext]) -> str:
    """Lê o log bruto de um incidente (ex.: INC-2043).

    Retorna no máximo as primeiras linhas definidas em `log_analyst_max_lines` no
    contexto da execução. Use para investigar a causa raiz nos logs.
    """
    try:
        path = ROOT / "incidents" / "logs" / f"{incident_id}.log"
        lines = path.read_text(encoding="utf-8").splitlines()
        limit = (runtime.context.log_analyst_max_lines if runtime.context else None) or DEFAULT_LOG_LINES
        head = lines[:limit]
        omitted = len(lines) - len(head)
        body = "\n".join(head)
        if omitted > 0:
            body += f"\n... ({omitted} linhas omitidas pelo limite log_analyst_max_lines={limit})"
        return body
    except Exception as e:
        return f"ERROR: {e}"


@tool
def read_impact_metrics(incident_id: str, runtime: ToolRuntime[IncidentContext]) -> str:
    """Lê as métricas de impacto de um incidente (ex.: INC-2043).

    Em modo estrito (`impact_analyst_strict_mode`) devolve também as colunas de
    margem de erro, que ficam de fora na leitura normal. Use para estimar severidade,
    usuários afetados e receita em risco.
    """
    try:
        path = ROOT / "incidents" / "metrics" / f"{incident_id}.csv"
        rows = [line.split(",") for line in path.read_text(encoding="utf-8").splitlines() if line]
        strict = bool(runtime.context and runtime.context.impact_analyst_strict_mode)
        keep = len(rows[0]) if strict else 3  # as duas últimas colunas são margens de erro
        lines = [" | ".join(cell.strip() for cell in row[:keep]) for row in rows]
        mode = "estrito" if strict else "normal"
        return f"[leitura em modo {mode}]\n" + "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


@tool
def shared_lookup(query: str, runtime: ToolRuntime[IncidentContext]) -> str:
    """Consulta o runbook interno da Nimbus sobre um termo técnico ou serviço.

    Ferramenta compartilhada: o coordenador e todos os subagentes podem chamá-la, e a
    resposta é adaptada a quem chamou.
    """
    try:
        caller = _caller(runtime)
        _JOURNAL.append((caller, query))
        path = ROOT / "incidents" / "runbook.md"
        hits = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if query.lower() in line.lower()
        ]
        if not hits:
            return f"[consulta de {caller}] nada no runbook sobre '{query}'."
        # O log-analyst quer as linhas cruas; os demais recebem só a primeira (doc:
        # resultados concisos). O prefixo diz qual dos dois ramos respondeu.
        if caller == "log-analyst":
            return f"[consulta de {caller}: {len(hits)} linha(s), completas]\n" + "\n".join(hits)
        return f"[consulta de {caller}: 1 de {len(hits)} linha(s)] {hits[0]}"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def write_postmortem(incident_id: str, content: str) -> str:
    """Grava o post-mortem de um incidente em /reports/<incident_id>-postmortem.md.

    Use para salvar o texto final em disco em vez de devolvê-lo inteiro ao
    coordenador, mantendo o contexto dele limpo.
    """
    try:
        folder = ROOT / "reports"
        folder.mkdir(exist_ok=True)
        path = folder / f"{incident_id}-postmortem.md"
        path.write_text(content, encoding="utf-8")
        return f"post-mortem gravado em /reports/{path.name} ({len(content)} caracteres)"
    except Exception as e:
        return f"ERROR: {e}"
