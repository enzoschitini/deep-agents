"""Runtime context and the structured-output models the subagents return.

`IncidentContext` is the `context_schema` of the whole agent: whatever is passed to
`invoke(context=...)` reaches every subagent and every tool, unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass
class IncidentContext:
    """Propagates to all subagents: each run gets the parent's context as-is.

    The per-subagent settings are modelled as separate fields prefixed with the
    subagent's name, which is the doc's alternative to namespaced string keys.
    """

    user_id: str
    log_analyst_max_lines: int | None = None  # read by read_incident_log
    impact_analyst_strict_mode: bool | None = None  # read by read_impact_metrics


class ImpactAssessment(BaseModel):
    """`response_format` of the impact-analyst: the parent gets JSON, not prose."""

    severity: str = Field(description="Severidade estimada: baixa, media, alta ou critica")
    affected_users: int = Field(description="Número de usuários afetados")
    revenue_at_risk_brl: float = Field(description="Receita em risco, em reais")
    confidence: float = Field(description="Confiança na estimativa, de 0 a 1")
    drivers: list[str] = Field(description="Fatores que explicam o impacto")


class IncidentTimeline(BaseModel):
    """`response_format` of the timeline-builder, set on its compiled graph."""

    events: list[str] = Field(description="Eventos em ordem cronológica, com horário")
    detection_delay_min: int = Field(description="Minutos entre o início e a detecção")
    total_duration_min: int = Field(description="Duração total do incidente em minutos")
