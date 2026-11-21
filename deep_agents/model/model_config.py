"""ModelConfig: configuração genérica de um modelo (provedor, id, parâmetros comuns)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelConfig:
    provider: str                       # "openai", "anthropic", "google_genai", ...
    model_id: str                       # "gpt-5.4", "claude-sonnet-4-6", ...
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None        # segundos
    max_retries: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)   # específicos do provedor

    @classmethod
    def from_spec(cls, spec: str, **kwargs: Any) -> "ModelConfig":
        """Cria a partir de "provider:model_id" (ex.: "openai:gpt-5.4")."""
        provider, sep, model_id = spec.partition(":")
        if not (sep and provider.strip() and model_id.strip()):
            raise ValueError(f'Modelo inválido: {spec!r} (use "provider:model_id")')
        return cls(provider=provider.strip(), model_id=model_id.strip(), **kwargs)

    @property
    def spec(self) -> str:
        return f"{self.provider}:{self.model_id}"
