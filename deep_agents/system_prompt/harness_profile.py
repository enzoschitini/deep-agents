import os
from dotenv import load_dotenv

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
from langchain.agents.middleware import AgentMiddleware

load_dotenv()

class CountCallings(AgentMiddleware):
    """extra_middleware: exemplo mínimo. Roda antes de cada chamada ao modelo."""

    def __init__(self) -> None:
        super().__init__()
        self.n = 0

    def before_model(self, state, runtime):
        self.n += 1
        print(f"[extra_middleware] chamada ao modelo nº {self.n} ({len(state['messages'])} mensagens)")
        return None

class HarnessProfiler:
    @staticmethod
    def build() -> HarnessProfile:
        return HarnessProfile(
            # BASE: texto fixo do "harness", logo depois do system_prompt= do agente (que aqui não existe).
            base_system_prompt="Você é um assistente técnico. Seja direto e preciso.",
            # SUFFIX: último bloco do prompt, o mais perto do histórico da conversa.
            system_prompt_suffix="REGRA DO PERFIL: responda em no máximo 3 frases e use português do Brasil.",
            # Troca a descrição que o modelo lê da ferramenta `ls` (chave com nome errado = no-op silencioso).
            tool_description_overrides={"ls": "Lista os arquivos do diretório virtual. (descrição do perfil)"},
            # Some da lista de ferramentas do modelo (calibragem, não segurança).
            excluded_tools=frozenset({"execute"}),
            # Remove o middleware de resumo da pilha. Nome que não casa com nada na pilha é rejeitado.
            excluded_middleware=frozenset({"SummarizationMiddleware"}),
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
