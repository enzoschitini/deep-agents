"""Dublês para testar o agente real sem API: um modelo de chat com roteiro e uma tool de busca falsa."""

from __future__ import annotations

import itertools

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

SUMMARY_MARKER = "Resuma a conversa abaixo"   # início do SUMMARY_PROMPT (prompts/system.py)
_ids = itertools.count(1)


def _size(message: BaseMessage) -> int:
    size = len(str(message.content))
    if isinstance(message, AIMessage):
        size += len(str(message.tool_calls))
    return size


class ScriptedChat(BaseChatModel):
    """Responde com as `AIMessage` do `script`, uma por chamada ao modelo do agente, na ordem.

    Chamadas de resumo (a mensagem única do SUMMARY_PROMPT) não consomem o roteiro: respondem um texto fixo e
    ficam registradas em `log` com kind="summary". Faz-se passar por openai:gpt-6.1-sol para o agente aplicar o
    mesmo perfil do harness que usa de verdade.
    """

    model_name: str = "gpt-6.1-sol"
    script: list = Field(default_factory=list)
    log: list = Field(default_factory=list)       # (kind, nº de mensagens, caracteres, texto do system prompt)
    cursor: int = 0

    def _get_ls_params(self, stop=None, **kwargs):
        return {"ls_provider": "openai", "ls_model_name": self.model_name, "ls_model_type": "chat"}

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        chars = sum(_size(m) for m in messages)
        system = str(messages[0].content) if messages and messages[0].type == "system" else ""
        is_summary = len(messages) == 1 and isinstance(messages[0], HumanMessage) and SUMMARY_MARKER in str(messages[0].content)
        if is_summary:
            self.log.append(("summary", len(messages), chars, system))
            reply = AIMessage(content="- resumo curto da conversa")
        else:
            self.log.append(("main", len(messages), chars, system))
            reply = self.script[self.cursor] if self.cursor < len(self.script) else AIMessage(content="fim")
            self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def calls(self, kind: str) -> list:
        return [entry for entry in self.log if entry[0] == kind]


def tool_call(name: str, args: dict) -> dict:
    return {"name": name, "args": args, "id": f"call_{next(_ids)}", "type": "tool_call"}


def tool_round(*calls: dict) -> AIMessage:
    """Resposta do modelo que pede tools (várias na mesma rodada = em paralelo)."""
    return AIMessage(content="", tool_calls=list(calls))


def read_skill() -> dict:
    return tool_call("read_file", {"file_path": "/prompts/skills/busca-na-web/SKILL.md"})


def search(query: str) -> dict:
    return tool_call("internet_search", {"query": query})


def internet_search(query: str, max_results: int = 5, topic: str = "general") -> str:
    """Busca na web e devolve título, URL e trecho de cada resultado."""
    return "\n\n".join(
        f"[{i}] Título {i} sobre {query}\nhttps://exemplo.com/{i}\n" + ("trecho de conteúdo da página " * 30)
        for i in range(1, max_results + 1)
    )
