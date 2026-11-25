"""ResponseAccumulator: texto por mensagem e última resposta final do principal."""

from __future__ import annotations


class ResponseAccumulator:
    def __init__(self) -> None:
        self._texts: dict[str, str] = {}
        self._final: str = ""

    def add(self, message_id: str, text: str) -> None:
        self._texts[message_id] = self._texts.get(message_id, "") + text

    def text_of(self, message_id: str) -> str:
        return self._texts.get(message_id, "")

    def close(self, message_id: str, text: str, final: bool) -> None:
        """Fecha a mensagem com o texto autoritativo (cobre AIMessage criado sem LLM)."""
        self._texts[message_id] = text
        if final:
            self._final = text

    def final_text(self) -> str:
        return self._final
