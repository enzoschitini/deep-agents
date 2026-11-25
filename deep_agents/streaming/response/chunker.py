"""WordCoalescer: agrupa deltas de tokens em palavras inteiras (granularity="word")."""

from __future__ import annotations


class WordCoalescer:
    """`push` devolve pedaços que terminam em espaço/quebra de linha; o resto fica retido até `flush`."""

    def __init__(self, granularity: str = "word") -> None:
        self.granularity = granularity
        self._buf = ""

    def push(self, text: str) -> list[str]:
        if not text:
            return []
        if self.granularity != "word":
            return [text]
        self._buf += text
        cut = max((i for i, ch in enumerate(self._buf) if ch.isspace()), default=-1)
        if cut < 0:
            return []
        out, self._buf = self._buf[: cut + 1], self._buf[cut + 1:]
        return [out]

    def flush(self) -> str:
        out, self._buf = self._buf, ""
        return out
