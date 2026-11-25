"""Data de hoje no system prompt (evita uma rodada de buscas na web só para descobrir que dia é)."""

from datetime import datetime

from deep_agents.prompts.agent_prompts import AgentPrompts, format_today


def test_format_today_is_in_portuguese_regardless_of_locale():
    assert format_today(datetime(2026, 11, 22)) == "domingo, 22 de novembro de 2026 (2026-11-22)"
    assert format_today(datetime(2027, 3, 1)) == "segunda-feira, 1 de março de 2027 (2027-03-01)"


def test_system_prompt_carries_today_s_date_and_keeps_the_original_text():
    prompt = AgentPrompts().system_prompt

    assert format_today() in prompt
    assert "Your name is Laura" in prompt
    assert "Nunca pesquise a data na web" in prompt
