"""Snapshot da configuração do agente (o que ESTÁ declarado) e do ambiente de execução.

O que realmente foi enviado ao modelo em cada chamada fica em `llm_calls.json`; aqui vai o contexto declarado:
modelo e parâmetros, prompts, regras, skills, toolkit, subagents, limites. O hash do conteúdo deduplica."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import Any

from deep_agents.tracing.serialize import to_json_safe

_PACKAGES = ("deepagents", "langgraph", "langchain", "langchain-core", "langchain-openai", "langchain-anthropic",
             "langchain-google-genai", "langchain-quickjs", "tavily-python", "rich")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def config_hash(snapshot: dict[str, Any]) -> str:
    return _sha(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str))[:16]


@lru_cache(maxsize=1)
def environment_info() -> dict[str, Any]:
    """Python, SO, versões das libs e git (cacheado: não muda durante o processo). Sem usuário/host."""
    packages: dict[str, str] = {}
    for name in _PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue

    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", *args], cwd=_REPO_ROOT, capture_output=True, text=True, timeout=3)
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:
            return None

    commit = git("rev-parse", "--short", "HEAD")
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": packages,
        "git": {"commit": commit, "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                "dirty": bool(git("status", "--porcelain")) if commit else None},
    }


def _read_text_files(folder: Path, pattern: str, limit: int) -> list[dict[str, Any]]:
    out = []
    for path in sorted(folder.glob(pattern)):
        text = path.read_text(encoding="utf-8", errors="replace")
        out.append({"path": str(path.relative_to(folder.parent)).replace("\\", "/"), "sha256": _sha(text)[:16],
                    "chars": len(text), "text": text[:limit]})
    return out


def build_config_snapshot(
    model_config: Any,
    *,
    toolkit: dict | None = None,
    subagents: dict | None = None,
    dynamic: dict | None = None,
    streaming: Any = None,
    max_chars: int = 100_000,
) -> dict[str, Any]:
    """Configuração declarada do agente para o modelo `model_config`. Nunca levanta: cada bloco falho vira `{"error": ...}`."""
    snapshot: dict[str, Any] = {}

    def block(name: str, fn) -> None:
        try:
            snapshot[name] = to_json_safe(fn(), max_chars)
        except Exception as e:   # o snapshot é informativo: não pode derrubar o run
            snapshot[name] = {"error": f"{type(e).__name__}: {e}"}

    def model():
        from deep_agents.model.provider_rules import DEFAULT_RULES, build_kwargs
        return {
            "spec": model_config.spec, "provider": model_config.provider, "model_id": model_config.model_id,
            "temperature": model_config.temperature, "thinking": model_config.thinking,
            "max_tokens": model_config.max_tokens, "timeout": model_config.timeout,
            "max_retries": model_config.max_retries, "extra": model_config.extra,
            "resolved_kwargs": build_kwargs(model_config, DEFAULT_RULES),   # o que as regras do provedor fazem com a config
        }

    def prompts():
        from deep_agents.prompts import system
        from deep_agents.prompts.agent_prompts import AgentPrompts
        ap = AgentPrompts()
        return {
            "system_prompt": ap.system_prompt,   # com a data de hoje
            "summary_prompt": system.SUMMARY_PROMPT,
            "harness_profile": {
                "base_system_prompt": system.HARNESS_BASE_PROMPT, "system_prompt_suffix": system.HARNESS_SUFFIX_PROMPT,
                "tool_description_overrides": system.HARNESS_TOOL_DESCRIPTIONS, "excluded_tools": ["execute"],
            },
            "memory_files": ap.memory_files,
            "skills_dirs": ap.skills,
            "rules": _read_text_files(ap.root / ap.RULES_DIR, "*.md", max_chars),
            "skills": _read_text_files(ap.root / ap.SKILLS_DIR, "*/SKILL.md", max_chars),
            "permissions": ap.permissions,
        }

    def subagent_defs():
        from deep_agents.subagents.build_subagents import DEFAULT_SUBAGENTS
        enabled = subagents or {}
        out = {}
        for name, cls in DEFAULT_SUBAGENTS.items():
            out[name] = {"enabled": bool((enabled.get(name) or {}).get("enabled", False)), "description": cls.description,
                         "system_prompt": cls.system_prompt, "toolkit": cls.toolkit}
        return out

    def limits():
        from deep_agents import config as c
        from deep_agents.memory import config as m
        return {"model_call_limit": c.MODEL_CALL_LIMIT, "subagent_call_limit": c.SUBAGENT_CALL_LIMIT,
                "dynamic_max_concurrency": c.DYNAMIC_MAX_CONCURRENCY, "summary_trigger_tokens": m.SUMMARY_TRIGGER_TOKENS,
                "trim_tokens_to_summarize": m.TRIM_TOKENS_TO_SUMMARIZE, "keep_messages": m.KEEP_MESSAGES}

    block("model", model)
    block("prompts", prompts)
    block("toolkit", lambda: toolkit or {})
    block("subagents", subagent_defs)
    block("dynamic_subagents", lambda: dynamic or {})
    block("limits", limits)
    block("streaming", lambda: streaming)
    return snapshot
