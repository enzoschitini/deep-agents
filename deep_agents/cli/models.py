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
