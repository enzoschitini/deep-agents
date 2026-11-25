"""ProviderRules: tratamento por provedor/modelo (renomear, descartar, fixar parâmetros)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from deep_agents.model.model_config import ModelConfig


@dataclass
class ProviderRules:
    """Ajustes que o gateway aplica antes de criar o modelo.

    rename: nome genérico -> nome que a integração do provedor espera
    drop_if: lista de (predicado_sobre_model_id, [parâmetros a descartar])
    defaults: kwargs aplicados se o usuário não definiu nada
    thinking: traduz ModelConfig.thinking ("off"/"low"/"medium"/"high") nos kwargs do provedor;
              um valor None no dict devolvido remove aquele kwarg
    """
    rename: dict[str, str] = field(default_factory=dict)
    drop_if: list[tuple[Callable[[str], bool], list[str]]] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    thinking: Callable[[ModelConfig], dict[str, Any]] | None = None


_BUDGETS = {"low": 2048, "medium": 8192, "high": 16384}


def _openai_is_reasoning(model_id: str) -> bool:
    return model_id.startswith(("o1", "o3", "o4", "gpt-5", "gpt-6"))


def _openai_thinking(cfg: ModelConfig) -> dict[str, Any]:
    # reasoning_effort só existe nos modelos de raciocínio; "off" = não enviar nada.
    if cfg.thinking == "off" or not _openai_is_reasoning(cfg.model_id):
        return {}
    return {"reasoning_effort": cfg.thinking, "temperature": None}


def _anthropic_thinking(cfg: ModelConfig) -> dict[str, Any]:
    if cfg.thinking == "off":
        return {}
    budget = _BUDGETS[cfg.thinking]
    # O budget precisa ser menor que max_tokens; com thinking ligado a temperature fica no padrão.
    max_tokens = cfg.max_tokens if cfg.max_tokens and cfg.max_tokens > budget else budget + 4096
    return {
        "thinking": {"type": "enabled", "budget_tokens": budget},
        "max_tokens": max_tokens,
        "temperature": None,
    }


def _google_thinking(cfg: ModelConfig) -> dict[str, Any]:
    if cfg.thinking == "off":
        return {"thinking_budget": 0}
    return {"thinking_budget": _BUDGETS[cfg.thinking] * 2, "include_thoughts": True}


# Pontos de partida. Os nomes de parâmetro divergem entre integrações e mudam
# com as versões: confira a página "chat model integrations" de cada provedor
# e ajuste esta tabela (ou passe a sua em LLMGateway(rules=...)).
DEFAULT_RULES: dict[str, ProviderRules] = {
    # max_tokens genérico -> max_output_tokens no Gemini
    "google_genai": ProviderRules(rename={"max_tokens": "max_output_tokens"}, thinking=_google_thinking),
    # Modelos de raciocínio da OpenAI costumam rejeitar temperature:
    # descartamos quando o id parece ser de raciocínio (ajuste o predicado).
    "openai": ProviderRules(
        drop_if=[(lambda m: m.startswith(("o1", "o3", "o4", "gpt-5")), ["temperature"])],
        thinking=_openai_thinking,
    ),
    "anthropic": ProviderRules(thinking=_anthropic_thinking),
}


def build_kwargs(cfg: ModelConfig, rules: dict[str, ProviderRules]) -> dict[str, Any]:
    r = rules.get(cfg.provider, ProviderRules())
    kwargs: dict[str, Any] = dict(r.defaults)
    generic = {
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "timeout": cfg.timeout,
        "max_retries": cfg.max_retries,
    }
    kwargs.update({k: v for k, v in generic.items() if v is not None})
    if cfg.thinking and r.thinking:
        for k, v in r.thinking(cfg).items():
            if v is None:
                kwargs.pop(k, None)
            else:
                kwargs[k] = v
    kwargs.update(cfg.extra)
    for predicate, names in r.drop_if:
        if predicate(cfg.model_id):
            for n in names:
                kwargs.pop(n, None)
    return {r.rename.get(k, k): v for k, v in kwargs.items()}
