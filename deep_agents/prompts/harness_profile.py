import os
from dotenv import load_dotenv

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
from langchain.agents.middleware import AgentMiddleware

from deep_agents.prompts.system import (
    HARNESS_BASE_PROMPT,
    HARNESS_SUFFIX_PROMPT,
    HARNESS_TOOL_DESCRIPTIONS,
)

load_dotenv()

class CountCallings(AgentMiddleware):
    """extra_middleware: exemplo mínimo. Roda antes de cada chamada ao modelo.

    O nº recomeça a cada pergunta, para bater com o "chiamate LLM" da linha de métricas (que ainda soma as chamadas
    de resumo, feitas dentro do middleware de resumo e que não passam por aqui). O número entre parênteses é a
    contagem bruta de mensagens do estado (histórico de texto + as mensagens das tools deste turno), não o que
    vai ao modelo."""

    def __init__(self) -> None:
        super().__init__()
        self.n = 0

    def before_agent(self, state, runtime):
        self.n = 0
        return None

    def before_model(self, state, runtime):
        self.n += 1
        print(f"[extra_middleware] chamada ao modelo nº {self.n} ({len(state['messages'])} mensagens)")
        return None

class HarnessProfiler:
    @staticmethod
    def build() -> HarnessProfile:
        return HarnessProfile(
            # Textos em system.py: BASE (após o system_prompt=) e SUFFIX (último bloco do prompt).
            base_system_prompt=HARNESS_BASE_PROMPT,
            system_prompt_suffix=HARNESS_SUFFIX_PROMPT,
            # Troca a descrição que o modelo lê de cada ferramenta (chave com nome errado = no-op silencioso).
            tool_description_overrides=HARNESS_TOOL_DESCRIPTIONS,
            # Some da lista de ferramentas do modelo (calibragem, não segurança).
            excluded_tools=frozenset({"execute"}),
            # Função sem argumentos: cada pilha recebe sua própria instância.
            extra_middleware=lambda: [CountCallings()],
            # enabled=False remove o subagente general-purpose; sem outros subagentes, a `task` some também.
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        )

    @staticmethod
    def register(spec=None, harness_profile=None) -> None:
        spec = spec or os.getenv("MODEL", "openai:gpt-4")   # chave "provedor:modelo"
        if harness_profile is None:
            harness_profile = HarnessProfiler.build()
        register_harness_profile(spec, harness_profile)
