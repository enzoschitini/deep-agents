"""Gera dados SINTÉTICOS de rastreamento no mesmo formato do `tracing/` (para desenvolver e testar a interface).

    python -m deep_agents.tracing_app.dev_seed --out PASTA [--runs 25] [--seed 7] [--no-running]

Roda de verdade o agente REAL (create_deep_agent + middlewares) offline, com modelos falsos (`tests/fakes*.py`) e o
`Tracer` ligado; depois reescreve os horários e as durações dos JSONs (espalha os runs em ~10 dias e infla as latências)
mantendo a coerência entre os arquivos. Nada é gravado em `deep_agents/data/tracing/`.

Conteúdo (25 runs em 4 sessões): run simples, com várias tools, com 1 e 2 subagents `pesquisador`, com o `redator`,
com erro (do modelo e de tool), cancelado, com chamada de resumo de contexto; 3 configs (modelos, prompts, regras e
limites diferentes), preços fictícios (custo em 2 dos 3 modelos) e, no fim, um run "em andamento" (só o `run.json`).
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import random
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from langchain_core.messages import AIMessage, AIMessageChunk  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult  # noqa: E402

from deep_agents.agent import AgentBuilder  # noqa: E402
from deep_agents.bootstrap import STREAMING, TOOLKIT  # noqa: E402
from deep_agents.memory import build_memory  # noqa: E402
from deep_agents.memory.build_memory import MemoryBuilder  # noqa: E402
from deep_agents.model.llm_gateway import LLMGateway  # noqa: E402
from deep_agents.model.model_config import ModelConfig  # noqa: E402
from deep_agents.prompts.agent_prompts import AgentPrompts, format_today  # noqa: E402
from deep_agents.prompts.system import SYSTEM_PROMPT, TODAY_PROMPT  # noqa: E402
from deep_agents.streaming import AgentStreamer, EventKind, Phase  # noqa: E402
from deep_agents.subagents.build_subagents import SubagentBuilder  # noqa: E402
from deep_agents.toolkit.build_toolkit import ToolkitBuilder  # noqa: E402
from deep_agents.toolkit.side_channel import SideChannel  # noqa: E402
from deep_agents.toolkit.tools.tavily import TavilyTools  # noqa: E402
from deep_agents.tracing import TraceOptions, Tracer, build_config_snapshot  # noqa: E402
from deep_agents.tracing.options import DEFAULT_DIR  # noqa: E402
from deep_agents.tracing.snapshot import config_hash  # noqa: E402
from tests.fakes import SUMMARY_MARKER, read_skill, search, tool_call, tool_round  # noqa: E402
from tests.fakes_stream import StreamingScriptedChat  # noqa: E402

# --------------------------------------------------------------------------- erros fictícios (o `type` aparece nos JSONs)


class RateLimitError(Exception):
    pass


class APITimeoutError(Exception):
    pass


class OverloadedError(Exception):
    pass


class SearchUnavailableError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ modelo falso
_lock = threading.Lock()
_DOMAINS = ["g1.globo.com", "espn.com.br", "reuters.com", "bbc.com", "pt.wikipedia.org", "techcrunch.com", "docs.python.org",
            "github.com", "gov.br", "bloomberg.com", "infomoney.com.br", "folha.uol.com.br", "arxiv.org", "mit.edu"]


def _size(message: Any) -> int:
    size = len(str(message.content))
    if isinstance(message, AIMessage):
        size += len(str(message.tool_calls))
    return size


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "pagina"


def _findings(angle: str, rng: random.Random) -> str:
    base = angle.strip().rstrip(".")
    lines = []
    for i in range(rng.randint(3, 5)):
        dom = rng.choice(_DOMAINS)
        lines.append(f"- {base}: ponto {i + 1} com dado de {rng.randint(18, 94)}% "
                     f"({dom}/{_slug(base)}-{i + 1}, 2026-11-{rng.randint(10, 24):02d})")
    return "\n".join(lines) + "\nLacunas: " + rng.choice(["nenhuma", "faltam números oficiais de 2026", "uma das fontes diverge"])


class SeedChat(StreamingScriptedChat):
    """Modelo falso com streaming, tokens/cache/reasoning realistas e pequenas esperas (o horário é reescrito depois).

    Principal: segue o `script` (um item `Exception` é levantado). Subagents (`pesquisador`/`redator`): decidem pela situação,
    porque rodam em paralelo e compartilham o modelo. Chamadas de resumo: texto fixo (herdado)."""

    model_name: str = "gpt-6.1-sol"
    provider: str = "openai"
    seed: int = 0
    slow: bool = False
    base_input_tokens: int = 6500   # system prompt + schemas das tools (o fake não os repassa)
    n_calls: int = 0

    def _get_ls_params(self, stop=None, **kwargs):
        return {"ls_provider": self.provider, "ls_model_name": self.model_name, "ls_model_type": "chat"}

    # ---- decisão da resposta
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = str(messages[0].content) if messages and messages[0].type == "system" else ""
        if len(messages) == 1 and SUMMARY_MARKER in str(messages[0].content):
            return super()._generate(messages, stop=stop)
        if "Você é um pesquisador" in system:
            reply = self._sub_reply("pesquisador", messages)
        elif "Você é um redator" in system:
            reply = self._sub_reply("redator", messages)
        else:
            with _lock:
                item = self.script[self.cursor] if self.cursor < len(self.script) else AIMessage(content="fim")
                self.cursor += 1
            if isinstance(item, BaseException):
                raise item
            reply = item
        return ChatResult(generations=[ChatGeneration(message=reply)])

    @staticmethod
    def _sub_reply(role: str, messages) -> AIMessage:
        task = next((str(m.content) for m in messages if m.type == "human"), "tema")
        topic = task.split(":", 1)[-1].strip()[:90]
        rng = random.Random(hashlib.sha1(task.encode()).hexdigest())
        if not any(m.type == "tool" for m in messages):
            q = topic.lower().rstrip(".")
            return tool_round(search(q), search(q + " 2026")) if rng.random() < 0.45 else tool_round(search(q))
        if role == "pesquisador":
            return AIMessage(_findings(topic, rng))
        d1, d2 = rng.sample(_DOMAINS, 2)
        return AIMessage(f"{topic}: o essencial em poucas linhas, com o que mudou nesta semana e o que vem a seguir. "
                         f"Vale acompanhar os próximos dias.\n\n#agentes #ia #dados\n\nFontes:\nhttps://{d1}/{_slug(topic)}\n"
                         f"https://{d2}/{_slug(topic)}-2\n\nAtenção: números de fontes diferentes não foram conciliados.")

    # ---- streaming com usage
    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self._generate(messages, stop=stop).generations[0].message   # pode levantar (erro do modelo)
        with _lock:
            self.n_calls += 1
            n = self.n_calls
        rng = random.Random(f"{self.seed}-{n}")
        text = reply.content if isinstance(reply.content, str) else ""
        in_tok = self.base_input_tokens + sum(_size(m) for m in messages) // 4 + rng.randint(-120, 160)
        out_tok = max(6, (len(text) + len(str(reply.tool_calls))) // 4 + rng.randint(0, 12))
        time.sleep(rng.uniform(0.015, 0.05))   # tempo até o 1º token
        if reply.tool_calls:
            chunks = [{"name": c["name"], "args": json.dumps(c["args"], ensure_ascii=False), "id": c["id"], "index": i}
                      for i, c in enumerate(reply.tool_calls)]
            chunk = ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=chunks))
            if run_manager:
                run_manager.on_llm_new_token("", chunk=chunk)
            yield chunk
        else:
            words = text.split(" ")
            for i, w in enumerate(words):
                piece = w + (" " if i < len(words) - 1 else "")
                chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
                if run_manager:
                    run_manager.on_llm_new_token(piece, chunk=chunk)
                yield chunk
                time.sleep(0.02 if self.slow else 0.0012)
        cache_read = 0 if n == 1 else int(in_tok * rng.uniform(0.62, 0.93))
        in_details: dict[str, int] = {"cache_read": cache_read}
        if self.provider == "anthropic":
            in_details["cache_creation"] = int(in_tok * 0.9) if n == 1 else int((in_tok - cache_read) * rng.uniform(0.3, 0.8))
        out_details = {"reasoning": rng.randint(0, out_tok // 2)} if self.provider != "anthropic" and rng.random() < 0.7 else {}
        stop_key, stop_val = (("stop_reason", "tool_use" if reply.tool_calls else "end_turn") if self.provider == "anthropic"
                              else ("finish_reason", "tool_calls" if reply.tool_calls else "stop"))
        yield ChatGenerationChunk(message=AIMessageChunk(
            content="", chunk_position="last",
            usage_metadata={"input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": in_tok + out_tok,
                            "input_token_details": in_details, "output_token_details": out_details},
            response_metadata={stop_key: stop_val, "model_name": self.model_name, "model_provider": self.provider,
                               "service_tier": "default"},
        ))


class ChatOpenAI(SeedChat):
    __module__ = "langchain_openai.chat_models.base"


class ChatAnthropic(SeedChat):
    __module__ = "langchain_anthropic.chat_models"


class ChatGoogleGenerativeAI(SeedChat):
    __module__ = "langchain_google_genai.chat_models"


# ---------------------------------------------------------------------------------------------- busca falsa
class FakeTavilyClient:
    """Cliente falso do Tavily: resultados determinísticos pela query, com uma pequena espera."""

    def search(self, query: str, max_results: int = 5, topic: str = "general") -> dict:
        rng = random.Random(hashlib.sha1(query.encode()).hexdigest())
        time.sleep(rng.uniform(0.02, 0.085))
        results = []
        for i, dom in enumerate(rng.sample(_DOMAINS, min(max_results, len(_DOMAINS)))):
            body = " ".join(f"Segundo a análise de {query}, o indicador {j} variou {rng.randint(1, 40)}% no período."
                            for j in range(1, rng.randint(4, 14)))
            results.append({"title": f"{query.capitalize()}: o que se sabe ({i + 1})", "url": f"https://{dom}/{_slug(query)}-{i + 1}",
                            "content": body})
        return {"results": results}


class SeedTavily(TavilyTools):
    def __init__(self, channel: SideChannel) -> None:
        super().__init__(channel, client=FakeTavilyClient())


class SeedTavilyFail(SeedTavily):
    """Variante cuja busca estoura (o run termina em erro, com a tool marcada como falha)."""

    def internet_search(self, query: str, max_results: int = 5, topic: str = "general") -> str:
        """Busca na web e devolve título, URL e trecho de cada resultado.

        Args:
            query: o que pesquisar.
            max_results: quantidade máxima de resultados.
            topic: "general", "news" ou "finance".
        """
        time.sleep(0.06)
        raise SearchUnavailableError("Tavily: 503 Service Unavailable (serviço de busca fora do ar)")


# ------------------------------------------------------------------------------------------------- configs
class VariantPrompts(AgentPrompts):
    """`AgentPrompts` com um trecho extra no system prompt e a data fixa da config (o hash não muda a cada dia)."""

    def __init__(self, extra: str, today: datetime) -> None:
        super().__init__()
        self._extra, self._today = extra, today

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT + TODAY_PROMPT.format(today=format_today(self._today)) + self._extra


@dataclass
class Variant:
    key: str
    spec: str
    provider: str
    model_id: str
    extra_prompt: str
    temperature: float | None = None
    thinking: str | None = None
    max_tokens: int | None = None
    prices: dict[str, tuple[float, float]] | None = None   # USD por 1M tokens (entrada, saída): fictícios
    subagents: dict = field(default_factory=lambda: {"pesquisador": {"enabled": True}, "redator": {"enabled": True}})
    limits: dict = field(default_factory=dict)
    drop_rule: int | None = None        # índice da regra removida do snapshot
    edit_rule: int | None = None        # índice da regra alterada no snapshot
    model_cls: type = ChatOpenAI
    first_used: datetime | None = None


VARIANTS = {
    "A": Variant("A", "openai:gpt-6.1-sol", "openai", "gpt-6.1-sol", "", model_cls=ChatOpenAI),
    "B": Variant("B", "anthropic:claude-sonnet-5-5", "anthropic", "claude-sonnet-5-5",
                 "\n\n## Estilo (v2)\nResponda sempre em português do Brasil, com marcadores curtos, e cite as fontes ao final.\n",
                 temperature=0.3, thinking="low", prices={"claude-sonnet-5-5": (3.0, 15.0)}, drop_rule=3, model_cls=ChatAnthropic),
    "C": Variant("C", "google_genai:gemini-3-flash", "google_genai", "gemini-3-flash",
                 "\n\n## Estilo (v3)\nSeja conciso: no máximo 5 linhas por resposta, sem introdução e sem repetir a pergunta.\n",
                 temperature=0.7, max_tokens=4096, prices={"gemini-3-flash": (0.35, 2.8)},
                 subagents={"pesquisador": {"enabled": True}, "redator": {"enabled": False}},
                 limits={"model_call_limit": 14, "subagent_call_limit": 8}, edit_rule=2, model_cls=ChatGoogleGenerativeAI),
}


def _snapshot_for(v: Variant) -> dict[str, Any]:
    """Snapshot declarado da config `v`: o real do repositório com o prompt/regras/limites da variante."""
    cfg = ModelConfig.from_spec(v.spec, temperature=v.temperature, thinking=v.thinking, max_tokens=v.max_tokens, timeout=120, max_retries=2)
    snap = build_config_snapshot(cfg, toolkit=TOOLKIT, subagents=v.subagents, dynamic={"enabled": False}, streaming=STREAMING)
    prompts = snap.get("prompts")
    if isinstance(prompts, dict):
        prompts["system_prompt"] = VariantPrompts(v.extra_prompt, v.first_used or datetime.now()).system_prompt
        rules = prompts.get("rules")
        if isinstance(rules, list):
            if v.edit_rule is not None and v.edit_rule < len(rules):
                r = dict(rules[v.edit_rule])
                r["text"] = str(r.get("text", "")) + "\n- (v3) Prefira respostas de até 5 linhas.\n"
                r["chars"], r["sha256"] = len(r["text"]), hashlib.sha256(r["text"].encode()).hexdigest()[:16]
                rules[v.edit_rule] = r
            if v.drop_rule is not None and v.drop_rule < len(rules):
                dropped = rules.pop(v.drop_rule)
                files = prompts.get("memory_files")
                if isinstance(files, list):
                    prompts["memory_files"] = [f for f in files if not str(f).endswith(str(dropped.get("path", "?")).split("/")[-1])]
    if v.limits and isinstance(snap.get("limits"), dict):
        snap["limits"].update(v.limits)
    return snap


# ------------------------------------------------------------------------------------------------- cenários
@dataclass
class Scenario:
    idx: int
    session: int
    config: str
    kind: str                    # simple | search | multi | research1 | research2 | writer | error_model | error_tool | cancel
    prompt: str
    answer: str = ""
    queries: list[str] = field(default_factory=list)
    angles: list[str] = field(default_factory=list)
    summary: bool = False
    slow_scale: bool = False     # latência inflada (run lento)
    error: str = ""              # tipo de erro do modelo: rate | timeout | overloaded


def _src(*urls: str) -> str:
    return "\n\n**Fontes:**\n" + "\n".join(f"- {u}" for u in urls)


PLAN: list[Scenario] = [
    # --- sessão 1 (CLI, config A, há ~9 dias)
    Scenario(1, 1, "A", "simple", "O que é um agente de IA com ferramentas? Responda em 3 frases.",
             "Um agente de IA com ferramentas é um modelo de linguagem que, além de gerar texto, decide chamar funções externas (busca, arquivos, APIs) para obter dados ou agir. "
             "Ele funciona em ciclos: pensa, chama uma ferramenta, lê o resultado e repete até ter a resposta. "
             "Isso troca a memória estática do modelo por informação atual e verificável."),
    Scenario(2, 1, "A", "search", "Qual a cotação do dólar hoje?",
             "O dólar comercial opera próximo de **R$ 5,27**, com leve alta de 0,3% no dia, segundo os principais portais de economia." + _src("https://www.infomoney.com.br/cotacoes/dolar", "https://www.bloomberg.com/br/dolar"),
             queries=["cotação do dólar hoje real"]),
    Scenario(3, 1, "A", "search", "Quem ganhou o último clássico entre Real Madrid e Barcelona?",
             "O último clássico terminou **Real Madrid 2 x 1 Barcelona**, em Madrid, com gol decisivo nos acréscimos. O resultado reduz a distância entre os dois na tabela." + _src("https://www.espn.com.br/futebol/clasico", "https://www.laliga.com/resultados"),
             queries=["último clásico Real Madrid Barcelona resultado", "El Clásico placar final"]),
    Scenario(4, 1, "A", "multi", "Faça um panorama das novidades do Python 3.14 e diga o que muda para quem usa typing.",
             "## Python 3.14: panorama\n\n- **Anotações adiadas** passam a ser o padrão (PEP 649/749): menos custo de importação e menos aspas em referências futuras.\n"
             "- **Template strings** (`t\"...\"`) permitem processar interpolações antes de formar o texto.\n- **Interpretador com JIT experimental** e melhorias no GC incremental.\n\n"
             "### Para typing\nAnotações viram avaliadas sob demanda; use `annotationlib` para inspecionar. `from __future__ import annotations` continua funcionando, mas deixa de ser necessário." + _src("https://docs.python.org/3.14/whatsnew/3.14.html", "https://peps.python.org/pep-0649/"),
             queries=["python 3.14 novidades", "PEP 649 annotations deferred", "python 3.14 template strings", "python 3.14 jit performance"]),
    Scenario(5, 1, "A", "research1", "Compare Postgres e SQLite para um app local com poucos usuários.",
             "**Recomendação:** SQLite.\n\nPara um app local com poucos usuários, SQLite elimina o servidor, o backup é copiar um arquivo e o desempenho de leitura é excelente. "
             "Postgres compensa se houver muitos escritores concorrentes, extensões (pgvector) ou acesso remoto.\n\n| Critério | SQLite | Postgres |\n|---|---|---|\n| Operação | zero | servidor |\n| Concorrência de escrita | limitada | alta |\n| Backup | copiar arquivo | pg_dump |" + _src("https://www.sqlite.org/whentouse.html"),
             angles=["Quando SQLite basta e quais seus limites de concorrência"]),
    Scenario(6, 1, "A", "writer", "Crie um post de LinkedIn sobre observabilidade de agentes de IA.",
             "Seu agente respondeu errado. Você sabe em qual chamada?\n\nObservabilidade para agentes não é luxo: é ver cada prompt, cada ferramenta e cada centavo gasto. Sem isso, depurar vira adivinhação.\n\n"
             "#IA #Agentes #Observabilidade\n\nFontes:\nhttps://techcrunch.com/observabilidade-agentes\n\nAtenção: números de fontes diferentes não foram conciliados.",
             angles=["Post de LinkedIn sobre observabilidade de agentes de IA"]),
    Scenario(7, 1, "A", "error_tool", "Pesquise as notícias de hoje sobre a Selic.", "", queries=["notícias selic hoje copom"]),
    Scenario(8, 1, "A", "simple", "Obrigado! Pode resumir o que fizemos até aqui?",
             "Claro. Vimos a cotação do dólar, o último clássico, as novidades do Python 3.14 e a comparação entre Postgres e SQLite. "
             "Também deixei um post de LinkedIn pronto. A única pendência é a busca sobre a Selic, que falhou por indisponibilidade do serviço de busca."),
    # --- sessão 2 (web, config B, há ~6 dias)
    Scenario(9, 2, "B", "simple", "Como funciona o prompt caching nos modelos da Anthropic?",
             "O prompt caching reaproveita o prefixo do prompt entre chamadas: você marca pontos de cache (`cache_control`) e o provedor guarda o processamento daquele trecho.\n\n"
             "- A primeira chamada **grava** o cache (custa um pouco mais).\n- As seguintes **leem** o cache (bem mais barato e mais rápido), enquanto o prefixo for idêntico e dentro do tempo de vida.\n"
             "- Mudar qualquer coisa antes do ponto de cache invalida o trecho."),
    Scenario(10, 2, "B", "research2", "Compare os frameworks LangGraph e CrewAI em duas frentes: arquitetura e maturidade.",
             "## LangGraph x CrewAI\n\n**Arquitetura.** LangGraph modela o agente como grafo de estados com controle explícito de fluxo e checkpoints; CrewAI organiza papéis (agentes) e tarefas em um processo mais declarativo.\n\n"
             "**Maturidade.** LangGraph tem ecossistema maior (LangSmith, deploy gerenciado) e releases mais frequentes; CrewAI cresce rápido, com foco em prototipagem.\n\n"
             "**Quando usar:** LangGraph para fluxos longos, com humano no loop e persistência; CrewAI para equipes de agentes simples." + _src("https://github.com/langchain-ai/langgraph", "https://github.com/crewAIInc/crewAI"),
             angles=["Arquitetura do LangGraph e do CrewAI", "Maturidade e ecossistema de LangGraph e CrewAI"]),
    Scenario(11, 2, "B", "search", "Qual o preço do plano Pro do Claude hoje?",
             "O plano **Pro** custa em torno de US$ 20 por mês (ou cerca de US$ 17 no plano anual). Há também planos Max, com limites maiores de uso." + _src("https://www.anthropic.com/pricing"),
             queries=["claude pro preço mensal"], summary=True),
    Scenario(12, 2, "B", "multi", "Monte um plano de estudos de 4 semanas sobre RAG com fontes.",
             "## Plano de 4 semanas: RAG\n\n1. **Semana 1:** fundamentos de embeddings e busca vetorial (chunking, similaridade).\n2. **Semana 2:** pipeline básico com recuperação + geração; avaliação com perguntas de teste.\n"
             "3. **Semana 3:** híbrido (BM25 + vetorial), reranking e filtros por metadados.\n4. **Semana 4:** avaliação contínua, observabilidade e custo/latência.\n\nCada semana termina com um mini projeto e um relatório de erros." + _src("https://arxiv.org/abs/2005.11401", "https://github.com/run-llama/llama_index"),
             queries=["RAG retrieval augmented generation tutorial", "chunking estratégias RAG", "reranking RAG híbrido bm25", "avaliação RAG ragas"]),
    Scenario(13, 2, "B", "cancel", "Escreva um relatório detalhado de 2000 palavras sobre a história da LaLiga.",
             " ".join(["A LaLiga nasceu em 1929, reunindo os principais clubes espanhóis em uma competição nacional de pontos corridos."] * 5)),
    Scenario(14, 2, "B", "error_model", "Liste os lançamentos de filmes de dezembro.", "", queries=["lançamentos de filmes dezembro 2026"], error="rate"),
    # --- sessão 3 (CLI, config B depois C, há ~3 dias)
    Scenario(15, 3, "B", "search", "Qual a previsão do tempo em São Paulo para amanhã?",
             "Amanhã em São Paulo: **máxima de 29 °C**, mínima de 19 °C, com pancadas de chuva à tarde (60% de chance)." + _src("https://www.climatempo.com.br/previsao-do-tempo/cidade/558/saopaulo-sp"),
             queries=["previsão do tempo são paulo amanhã"]),
    Scenario(16, 3, "B", "research1", "Levante o estado atual da regulamentação de IA na União Europeia.",
             "**Resumo:** o AI Act está em vigor e entra em aplicação por etapas. As proibições valem desde 2025; as regras para modelos de uso geral, em 2026; os sistemas de alto risco, em 2027.\n\n"
             "Há discussão em curso para simplificar prazos e reduzir a carga sobre pequenas empresas." + _src("https://artificialintelligenceact.eu/", "https://www.europarl.europa.eu/topics/pt/article/ai-act"),
             angles=["Cronograma de aplicação do AI Act europeu"], slow_scale=True),
    Scenario(17, 3, "B", "writer", "Escreva um post curto sobre a final da Copa Libertadores.",
             "Final da Libertadores: noventa minutos que valem uma geração.\n\nDois clubes, um estádio lotado e a chance de entrar para a história do continente. Quem aguenta a pressão leva a taça.\n\n"
             "#Libertadores #Futebol\n\nFontes:\nhttps://www.espn.com.br/libertadores/final\n\nAtenção: horário e local conforme a última nota da Conmebol.",
             angles=["Post curto sobre a final da Copa Libertadores"]),
    Scenario(18, 3, "C", "multi", "Resuma as 5 maiores notícias de tecnologia desta semana.",
             "1. Nova geração de chips de IA anunciada.\n2. Atualização do Android amplia recursos de privacidade.\n3. Startup de agentes capta rodada de US$ 120 mi.\n4. Debate europeu sobre regras para modelos de uso geral.\n5. Python 3.14 ganha adoção em produção." + _src("https://techcrunch.com/", "https://www.reuters.com/technology/"),
             queries=["maiores notícias tecnologia semana", "lançamento chips IA novembro 2026", "startup agentes rodada captação"]),
    Scenario(19, 3, "C", "research2", "Pesquise a adoção de energia solar no Brasil: custos e regulação.",
             "**Custos:** o preço de sistemas residenciais caiu cerca de 12% em um ano; payback médio de 4 a 6 anos.\n**Regulação:** a Lei 14.300 mantém a compensação, com cobrança gradual do uso da rede (Fio B)." + _src("https://www.gov.br/aneel", "https://www.absolar.org.br/"),
             angles=["Custos de sistemas solares residenciais no Brasil", "Regulação da geração distribuída (Lei 14.300)"]),
    Scenario(20, 3, "C", "simple", "Traduza para inglês: 'o tracing mostra cada chamada do agente'.",
             "Tracing shows every call the agent makes."),
    Scenario(21, 3, "C", "search", "E qual o ranking da LaLiga agora?",
             "1. Barcelona; 2. Real Madrid; 3. Atlético de Madrid; 4. Athletic Club; 5. Real Sociedad." + _src("https://www.laliga.com/clasificacion"),
             queries=["clasificación laliga hoy"], summary=True),
    # --- sessão 4 (web, config A, hoje)
    Scenario(22, 4, "A", "research1", "Quais são as melhores práticas para avaliar agentes (evals) em produção?",
             "**Boas práticas**\n\n1. Comece por um conjunto pequeno de casos reais, com resultado esperado verificável.\n2. Meça por etapa (tool certa? argumentos certos?) e não só a resposta final.\n"
             "3. Rode evals a cada mudança de prompt/modelo e compare por versão.\n4. Monitore custo, latência e taxa de erro em produção, com amostragem para revisão humana." + _src("https://arxiv.org/abs/2307.03109", "https://github.com/openai/evals"),
             angles=["Práticas de avaliação de agentes de IA em produção"]),
    Scenario(23, 4, "A", "multi", "Prepare um briefing sobre a Black Friday no Brasil: tendências e preços.",
             "## Briefing: Black Friday 2026\n\n- Projeção de crescimento de **8%** nas vendas online.\n- Eletrônicos e eletrodomésticos lideram em volume; moda cresce em ticket médio.\n"
             "- Atenção ao histórico de preços: descontos reais ficam em torno de 15 a 25%.\n\n**Recomendação:** compare preços 30 dias antes e use alertas." + _src("https://www.reuters.com/brasil/black-friday", "https://g1.globo.com/economia/black-friday"),
             queries=["black friday 2026 brasil projeção vendas", "black friday preços histórico desconto real", "black friday tendências categorias"], slow_scale=True),
    Scenario(24, 4, "A", "error_model", "Pesquise o último relatório da OpenAI sobre uso de agentes.", "", queries=["openai relatório uso de agentes"], error="timeout"),
    Scenario(25, 4, "A", "simple", "Valeu, era isso.", "De nada! Se precisar, é só chamar."),
]

# ordem de prioridade quando `--runs` < 25 (garante variedade: 2 configs/tipos já nos primeiros)
_RANK = [2, 4, 6, 10, 13, 14, 11, 18, 7, 19, 22, 17, 24, 5, 12, 16, 9, 1, 15, 23, 21, 3, 20, 8, 25]


def _error_for(kind: str) -> BaseException:
    if kind == "timeout":
        return APITimeoutError("Request timed out after 120s")
    if kind == "overloaded":
        return OverloadedError("Overloaded: o provedor está sobrecarregado, tente novamente")
    return RateLimitError("429 Too Many Requests: rate limit de tokens por minuto excedido")


def _script(s: Scenario) -> list:
    answer = AIMessage(s.answer)
    q = s.queries
    if s.kind == "simple":
        return [answer]
    if s.kind == "search":
        return [tool_round(*[search(x) for x in q]), answer]
    if s.kind == "multi":
        todos = [{"content": "Pesquisar fontes", "status": "in_progress"}, {"content": "Escrever a resposta", "status": "pending"}]
        return [tool_round(read_skill(), tool_call("write_todos", {"todos": todos})),
                tool_round(*[search(x) for x in q[:3]]), *([tool_round(search(q[3]))] if len(q) > 3 else []), answer]
    if s.kind == "research1":
        return [tool_round(tool_call("task", {"description": f"Pesquise: {s.angles[0]}", "subagent_type": "pesquisador"})), answer]
    if s.kind == "research2":
        return [tool_round(*[tool_call("task", {"description": f"Pesquise: {a}", "subagent_type": "pesquisador"}) for a in s.angles]), answer]
    if s.kind == "writer":
        return [tool_round(tool_call("task", {"description": f"Escreva: {s.angles[0]}", "subagent_type": "redator"})), answer]
    if s.kind == "error_model":
        return [tool_round(*[search(x) for x in q]), _error_for(s.error)]
    if s.kind == "error_tool":
        return [tool_round(*[search(x) for x in q]), answer]
    return [answer]   # cancel


# ----------------------------------------------------------------------------------------- reescrita de tempo
_ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?\+00:00$")


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="milliseconds")


def _remap(obj: Any, old0: float, new0: float, scale: float, key: str | None = None) -> Any:
    """Move para `new0` e estica por `scale` todo horário (ISO, `ts`, `created_at` epoch) e toda duração (`*_s`)."""
    if isinstance(obj, dict):
        return {k: _remap(v, old0, new0, scale, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_remap(v, old0, new0, scale, key) for v in obj]
    if isinstance(obj, str) and _ISO.match(obj):
        return _iso(new0 + (datetime.fromisoformat(obj).timestamp() - old0) * scale)
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if key and key.endswith("_s"):
            return round(obj * scale, 4)
        if key in ("ts", "created_at") and obj > 1e9:
            return new0 + (obj - old0) * scale
    return obj


def _write(path: Path, doc: Any) -> int:
    data = json.dumps(doc, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    path.write_bytes(data)
    return len(data)


def _rewrite_run(run_dir: Path, *, new_start: datetime, scale: float, session_id: str, turn: int) -> dict[str, Any]:
    docs = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in run_dir.glob("*.json")}
    old0 = datetime.fromisoformat(docs["run.json"]["started_at"]).timestamp()
    new0 = new_start.timestamp()
    docs = {name: _remap(doc, old0, new0, scale) for name, doc in docs.items()}
    run = docs["run.json"]
    run["session_id"], run["turn"] = session_id, turn
    if isinstance(run.get("index_entry"), dict):
        run["index_entry"]["session_id"], run["index_entry"]["turn"] = session_id, turn
    for call in (docs.get("llm_calls.json") or {}).get("calls", []):
        out, lat = (call.get("usage") or {}).get("output_tokens"), call.get("latency_s")
        call["tokens_per_second"] = round(out / lat, 3) if out and lat else None
    sizes = {name: _write(run_dir / name, doc) for name, doc in docs.items() if name != "run.json"}
    run["files"] = {**{name: {"bytes": n} for name, n in sizes.items()}, "run.json": {"bytes": None}}
    _write(run_dir / "run.json", run)
    return run


# -------------------------------------------------------------------------------------------------- geração
def _session_starts(now: datetime) -> dict[int, datetime]:
    base = lambda days, h, m: (now - timedelta(days=days)).replace(hour=h, minute=m, second=7, microsecond=0)  # noqa: E731
    return {1: base(9, 13, 12), 2: base(6, 9, 31), 3: base(3, 16, 5), 4: now - timedelta(minutes=104)}


def _clear(out: Path) -> None:
    for name in ("runs", "configs"):
        shutil.rmtree(out / name, ignore_errors=True)
    for name in ("index.json", "sessions.json", "NOTES.txt"):
        (out / name).unlink(missing_ok=True)


def generate(out: Path, *, runs: int = 25, seed: int = 7, running: bool = True, quiet: bool = True) -> dict[str, Any]:
    """Gera os dados em `out` (recria `runs/`, `configs/`, `index.json`, `sessions.json`). Devolve um resumo."""
    out = Path(out).resolve()
    if out == DEFAULT_DIR.resolve() or DEFAULT_DIR.resolve() in out.parents:
        raise SystemExit("recuso gravar nos dados reais de deep_agents/data/tracing")
    if out.exists() and any(out.iterdir()) and not ((out / "NOTES.txt").exists() or (out / "index.json").exists()):
        raise SystemExit(f"{out} não está vazia e não parece uma pasta de dados do tracing")
    out.mkdir(parents=True, exist_ok=True)
    _clear(out)

    plan = sorted(sorted(PLAN, key=lambda s: _RANK.index(s.idx))[:max(1, min(runs, len(PLAN)))], key=lambda s: s.idx)
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    starts = _session_starts(now)

    # horários de início de cada run (espaçados dentro da sessão; a 1ª run de cada sessão no início dela)
    when: dict[int, datetime] = {}
    cursor: dict[int, datetime] = {}
    for s in plan:
        t = cursor.get(s.session, starts[s.session])
        if s.session in cursor:
            t = t + timedelta(minutes=rng.randint(2, 17), seconds=rng.randint(0, 59))
            if rng.random() < 0.12:
                t += timedelta(minutes=50)
        cursor[s.session] = when[s.idx] = t
    for sid, t in cursor.items():   # a última run da sessão 4 precisa terminar antes de "agora"
        if t > now - timedelta(minutes=6):
            shift = t - (now - timedelta(minutes=6))
            for s in plan:
                if s.session == sid:
                    when[s.idx] -= shift

    for key, v in VARIANTS.items():
        first = next((when[s.idx] for s in plan if s.config == key), None)
        v.first_used = first
    snapshots = {v.spec: _snapshot_for(v) for v in VARIANTS.values() if v.first_used is not None}

    state = {"session": ""}
    tracer = Tracer(TraceOptions(enabled=True, base_dir=out, summary_marker=SUMMARY_MARKER),
                    config_snapshot=lambda cfg: copy.deepcopy(snapshots[cfg.spec]), session_provider=lambda: state["session"])
    session_ids = {sid: t.astimezone().strftime("%Y%m%d-%H%M%S") for sid, t in starts.items()}
    channels = {sid: SideChannel(session_provider=lambda sid=sid: session_ids[sid]) for sid in starts}
    history: dict[int, list[dict]] = {sid: [] for sid in starts}
    records: list[dict[str, Any]] = []

    sink = io.StringIO()
    for s in plan:
        v = VARIANTS[s.config]
        state["session"] = session_ids[s.session]
        group = SeedTavilyFail if s.kind == "error_tool" else SeedTavily
        fake = v.model_cls(model_name=v.model_id, provider=v.provider, seed=seed * 1000 + s.idx, script=_script(s), slow=s.kind == "cancel")
        cfg = ModelConfig.from_spec(v.spec, temperature=v.temperature, thinking=v.thinking, max_tokens=v.max_tokens, timeout=120, max_retries=2)
        messages = list(history[s.session])
        if s.summary:   # contexto grande: o resumo de contexto dispara (limite baixo só nesta montagem)
            messages += [{"role": "user", "content": "Segue o relatório técnico que mencionei antes. " + "contexto da conversa " * 220},
                         {"role": "assistant", "content": "Li o relatório. " + "ok, entendido " * 160}]
        messages.append({"role": "user", "content": s.prompt})
        origin = "cli" if s.session in (1, 3) else "web"
        with contextlib.redirect_stdout(sink), mock.patch.object(build_memory, "SUMMARY_TRIGGER_TOKENS", 200 if s.summary else build_memory.SUMMARY_TRIGGER_TOKENS):
            builder = AgentBuilder(cfg, memory=MemoryBuilder(database="fake_vectorial"),
                                   toolkit=ToolkitBuilder(TOOLKIT, channel=channels[s.session], groups={"tavily": group}),
                                   subagents=SubagentBuilder(v.subagents))
            builder.gateway = LLMGateway(cfg, model=fake, prices=v.prices)
            builder.prompts = VariantPrompts(v.extra_prompt, v.first_used)
            agent, gateway = builder.build()
            handle = AgentStreamer(agent, gateway, options=STREAMING, channel=channels[s.session], tracer=tracer, origin=origin).start(messages)
            n_delta = 0
            for ev in handle:
                if s.kind == "cancel" and ev.kind is EventKind.RESPONSE and ev.phase is Phase.DELTA:
                    n_delta += 1
                    if n_delta == 14:
                        handle.cancel()
            handle.join(30)
        if handle.result.answer and not handle.result.error and not handle.result.cancelled:
            history[s.session] += messages[len(history[s.session]):] + [{"role": "assistant", "content": handle.result.answer}]
        scale = 7.0 if s.kind == "cancel" else rng.uniform(240, 380) if s.slow_scale else rng.uniform(14, 44)
        records.append({"scn": s, "run_id": handle.run_id, "scale": scale})

    # reescrita de horários/durações e índices
    for rec in records:
        s = rec["scn"]
        turn = sum(1 for r in records if r["scn"].session == s.session and r["scn"].idx <= s.idx)
        run = _rewrite_run(out / "runs" / rec["run_id"], new_start=when[s.idx], scale=rec["scale"], session_id=session_ids[s.session], turn=turn)
        rec.update(status=run["status"], started_at=run["started_at"], duration_s=run["duration_s"], config_hash=run["config_hash"],
                   cost=(run.get("totals") or {}).get("cost_usd"))

    running_id = None
    if running:
        s = plan[-1]
        state["session"] = session_ids[4]
        v = VARIANTS["A"]
        cfg = ModelConfig.from_spec(v.spec, timeout=120, max_retries=2)
        running_id = "ffff" + hashlib.md5(str(seed).encode()).hexdigest()[:28]
        tracer.begin_run(running_id, messages=[{"role": "user", "content": "Monte um comparativo longo de provedores de LLM e seus preços."}],
                         origin="web", model_config=cfg, turn=len(history[4]) // 2 + 1)
        run_dir = out / "runs" / running_id
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        old0 = datetime.fromisoformat(run["started_at"]).timestamp()
        run = _remap(run, old0, (now - timedelta(seconds=40)).timestamp(), 1.0)
        run["session_id"] = run["index_entry"]["session_id"] = session_ids[4]
        _write(run_dir / "run.json", run)
        tracer._collectors.pop(running_id, None)   # nunca termina: fica como um processo que morreu no meio

    # índice e sessões refeitos a partir dos run.json (já com os horários novos)
    (out / "sessions.json").unlink(missing_ok=True)
    index = tracer.rebuild_index()
    for entry in index["runs"]:
        tracer.store.update_session(entry, _iso(now.timestamp()))
    for h, first in {r["config_hash"]: min(when[x["scn"].idx] for x in records if x["config_hash"] == r["config_hash"]) for r in records}.items():
        path = out / "configs" / f"{h}.json"
        if path.exists():
            os.utime(path, (first.timestamp(), first.timestamp()))

    summary = {"out": str(out), "n_runs": len(records) + (1 if running_id else 0), "running_run_id": running_id,
               "sessions": {str(k): session_ids[k] for k in sorted({r["scn"].session for r in records})},
               "configs": sorted({r["config_hash"] for r in records}), "records": records}
    _write_notes(out, summary)
    return summary


def _write_notes(out: Path, summary: dict[str, Any]) -> None:
    rows = []
    durs = [r["duration_s"] or 0 for r in summary["records"]]
    for r in sorted(summary["records"], key=lambda r: r["started_at"]):
        s: Scenario = r["scn"]
        cost = f"{r['cost']:.4f}" if r.get("cost") is not None else "-"
        rows.append(f"  {r['started_at'][:19]}  S{s.session} cfg {s.config}  {s.kind:<11} {r['status']:<9} {r['duration_s'] or 0:>6.1f}s  usd {cost:<7} {r['run_id']}  {s.prompt[:48]}")
    text = (
        "Dados SINTETICOS do tracing (gerados por deep_agents.tracing_app.dev_seed; nada a ver com os dados reais).\n"
        f"Pasta: {summary['out']}\n"
        f"Runs: {summary['n_runs']} (incluindo 1 'running' sem arquivos alem do run.json: {summary['running_run_id']})\n"
        f"Sessoes: {', '.join(summary['sessions'].values())}   (S1 e S3 = origem cli, S2 e S4 = web)\n"
        f"Configs (hashes): {', '.join(summary['configs'])}\n"
        "  A = openai:gpt-6.1-sol (sem preco: cost_usd nulo) | B = anthropic:claude-sonnet-5-5 (preco ficticio, thinking low, regra 04 removida)\n"
        "  C = google_genai:gemini-3-flash (preco ficticio, sem redator, limites 14/8, regra 03 alterada). Prompts de sistema diferentes (v1/v2/v3).\n"
        "Tipos de run: simple, search, multi (skill+todos+varias buscas), research1 (1 subagent pesquisador), research2 (2 em paralelo),\n"
        "  writer (subagent redator), error_model (RateLimitError/APITimeoutError), error_tool (busca estoura), cancel (cancelado),\n"
        "  summary (chamada de resumo de contexto: runs 11 e 21). Latencias de ~3 a ~170 s (alguns runs lentos).\n"
        "Uso: python -m deep_agents.tracing_app --data-dir <esta pasta>\n\n"
        "inicio (UTC)         sessao cfg tipo        status    duracao  custo   run_id                            prompt\n" + "\n".join(rows) + "\n"
    )
    (out / "NOTES.txt").write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m deep_agents.tracing_app.dev_seed", description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="pasta de saída (formato de data/tracing/)")
    ap.add_argument("--runs", type=int, default=25, help="nº de runs (1 a 25; com menos, escolhe os mais variados)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-running", action="store_true", help="não cria o run 'em andamento'")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    summary = generate(args.out, runs=args.runs, seed=args.seed, running=not args.no_running)
    print(f"{summary['n_runs']} runs em {summary['out']} ({time.perf_counter() - t0:.0f}s); veja NOTES.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
