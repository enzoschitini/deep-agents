"""Catálogo de modelos oferecidos pelo comando /modello e interpretação da escolha."""

from __future__ import annotations

from dataclasses import replace

from deep_agents.model.model_config import ModelConfig

# Modelos mostrados no seletor. Para outros, digite "provider:model_id" no próprio seletor.
AVAILABLE_MODELS: list[ModelConfig] = [
    ModelConfig(provider="openai", model_id="gpt-6.1-sol"),
    ModelConfig(provider="openai", model_id="gpt-5.4"),
    ModelConfig(provider="openai", model_id="gpt-5"),
    ModelConfig(provider="openai", model_id="gpt-5-mini"),
    ModelConfig(provider="openai", model_id="gpt-5-nano"),
    ModelConfig(provider="openai", model_id="gpt-4.1"),
    ModelConfig(provider="openai", model_id="gpt-4o"),
    ModelConfig(provider="openai", model_id="o3"),
    ModelConfig(provider="openai", model_id="o4-mini"),
    ModelConfig(provider="anthropic", model_id="claude-fable-5-2"),
    ModelConfig(provider="anthropic", model_id="claude-opus-5-5"),
    ModelConfig(provider="anthropic", model_id="claude-sonnet-5-5"),
    ModelConfig(provider="anthropic", model_id="claude-haiku-5-5"),
]


# Opções dos seletores /temperatura e /thinking: (rótulo, valor). None = padrão do modelo.
TEMPERATURES: list[tuple[str, float | None]] = [
    ("Padrão del modello", None),
    ("0.0  · preciso, deterministico", 0.0),
    ("0.3  · equilibrato", 0.3),
    ("0.7  · creativo", 0.7),
    ("1.0  · molto creativo", 1.0),
]

THINKING_LEVELS: list[tuple[str, str | None]] = [
    ("Padrão del modello", None),
    ("Disattivato", "off"),
    ("Basso", "low"),
    ("Medio", "medium"),
    ("Alto", "high"),
]

_THINKING_ALIASES = {
    "default": None, "auto": None, "padrao": None, "padrão": None, "predefinito": None,
    "off": "off", "no": "off", "disattivato": "off", "spento": "off",
    "low": "low", "basso": "low",
    "medium": "medium", "medio": "medium",
    "high": "high", "alto": "high",
}


def parse_temperature(text: str) -> tuple[bool, float | None]:
    """"0.7" -> (True, 0.7); "default" -> (True, None); inválido -> (False, None)."""
    text = text.strip().lower().replace(",", ".")
    if text in {"default", "auto", "padrao", "padrão", "predefinito"}:
        return True, None
    try:
        value = float(text)
    except ValueError:
        return False, None
    return (0.0 <= value <= 2.0), value


def parse_thinking(text: str) -> tuple[bool, str | None]:
    """"high"/"alto" -> (True, "high"); "default" -> (True, None); inválido -> (False, None)."""
    key = text.strip().lower()
    return (key in _THINKING_ALIASES), _THINKING_ALIASES.get(key)


def resolve_choice(choice: str, models: list[ModelConfig], current: ModelConfig) -> ModelConfig | None:
    """Converte o que o usuário digitou ("2" ou "provider:model_id") em um ModelConfig.

    Mantém timeout/max_retries/etc. do modelo atual. Devolve None se a entrada é inválida.
    """
    choice = choice.strip()
    if choice.isdigit():
        index = int(choice) - 1
        if not 0 <= index < len(models):
            return None
        picked = models[index]
        return replace(current, provider=picked.provider, model_id=picked.model_id)
    provider, sep, model_id = choice.partition(":")
    if sep and provider.strip() and model_id.strip():
        return replace(current, provider=provider.strip(), model_id=model_id.strip())
    return None
