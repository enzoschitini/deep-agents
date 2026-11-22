"""Contrato dos subagents: um arquivo em `subagents/` = um papel = uma subclasse de `SubagentDef`."""
from typing import Any, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware

from deep_agents.config import SUBAGENT_CALL_LIMIT


class SubagentDef:
    """Definição de um subagent. `spec()` devolve o dict que o `create_deep_agent(subagents=...)` espera.

    O subagent roda em contexto isolado: só vê a `description` da tarefa que o principal enviou, usa só as
    tools do `toolkit` que declara e devolve ao principal apenas a última mensagem. Usa o modelo recebido
    (o do `LLMGateway`, com as regras do provedor e as métricas).

    Por que um agente já compilado (`CompiledSubAgent`) e não o dict declarativo (`system_prompt=`, `tools=`):
    o `HarnessProfile` do modelo (prompts/harness_profile.py) se aplica também aos subagents declarativos, e o
    `base_system_prompt` dele SUBSTITUI o `system_prompt` do subagent (o `system_prompt_suffix` é anexado). O
    subagent perderia as próprias instruções. Compilado, ele fica fora do perfil e só tem as tools que declarou
    (sem tools de arquivo).
    """

    name: str = ""            # o principal chama com task(subagent_type=<name>)
    description: str = ""     # o que o principal lê para decidir quando delegar
    system_prompt: str = ""   # instruções do subagent
    # Tools dele, no formato da toolkit: {grupo: {"enabled": bool, "tools": [nomes] | None}}. Independe das tools
    # do agente principal (o principal pode até não ter `internet_search` e o subagent continua com ela).
    toolkit: dict[str, dict] = {}

    def middleware(self) -> list[Any]:
        """Teto de chamadas ao modelo por tarefa delegada (o do agente principal não vale para o subagent)."""
        return [ModelCallLimitMiddleware(run_limit=SUBAGENT_CALL_LIMIT, exit_behavior="end")]

    def spec(self, model: Any, tools: list[Callable]) -> dict[str, Any]:
        runnable = create_agent(
            model,
            tools=tools,
            system_prompt=self.system_prompt,
            middleware=self.middleware(),
            name=self.name,
        )
        return {"name": self.name, "description": self.description, "runnable": runnable}
