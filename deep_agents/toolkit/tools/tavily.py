"""
Integração com o Tavily para fazer buscas na web.

Canal direto: título, URL e trecho de cada resultado, para o modelo.
Canal lateral: kind="sources" com `{domain, title, url}` de cada página.
"""
import os
from typing import Any, Callable, Literal
from urllib.parse import urlparse

from deep_agents.toolkit.side_channel import SideChannel
from deep_agents.toolkit.tools.base import ToolGroup


class TavilyTools(ToolGroup):
    name = "tavily"

    def __init__(self, channel: SideChannel, client: Any | None = None) -> None:
        """`client` permite injetar um cliente fake nos testes; por padrão usa TAVILY_API_KEY."""
        super().__init__(channel)
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from tavily import TavilyClient  # import tardio: só exige o pacote/chave se a tool for usada

            self._client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
        return self._client

    def tools(self) -> dict[str, Callable]:
        return {"internet_search": self.internet_search}

    def internet_search(
        self,
        query: str,
        max_results: int = 5,
        topic: Literal["general", "news", "finance"] = "general",
    ) -> str:
        """Busca na web e devolve título, URL e trecho de cada resultado.

        Args:
            query: o que pesquisar.
            max_results: quantidade máxima de resultados.
            topic: "general", "news" ou "finance".
        """
        try:
            response = self._get_client().search(query, max_results=max_results, topic=topic)
        except Exception as e:  # falha da API não derruba o turno: o modelo recebe o erro e decide
            return f"Erro na busca: {type(e).__name__}: {e}"

        results = response.get("results", [])
        self.publish("internet_search", "sources", [
            {"domain": urlparse(r.get("url", "")).netloc, "title": r.get("title", ""), "url": r.get("url", "")}
            for r in results
        ])
        if not results:
            return "Nenhum resultado encontrado."
        return "\n\n".join(
            f"[{i}] {r.get('title', '')}\n{r.get('url', '')}\n{r.get('content', '')}"
            for i, r in enumerate(results, 1)
        )
