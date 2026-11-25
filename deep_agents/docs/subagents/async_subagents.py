"""
Chat em loop para testar ASYNC SUBAGENTS do Deep Agents (LangChain) com OpenAI.

Async subagents rodam em um servidor Agent Protocol (aqui: `langgraph dev`, local).
O supervisor dispara tarefas em background (start_async_task) e volta a conversar com
você na hora; depois pode checar (check_async_task), mandar instruções novas
(update_async_task), cancelar (cancel_async_task) ou listar (list_async_tasks).
No Agent Server, quando o subagent termina ele avisa o supervisor sozinho.

Este arquivo tem DUAS funções:
  1) Define os grafos (supervisor, researcher, writer) que o langgraph.json expõe no servidor.
  2) Quando executado (python async_subagents_chat.py), sobe o servidor `langgraph dev`
     (se ainda não estiver no ar) e abre o chat em loop como cliente.

Uso:
  pip install "langgraph-cli[inmem]" deepagents langchain-openai langgraph-sdk python-dotenv
  export OPENAI_API_KEY=sk-...
  python async_subagents_chat.py

Variáveis opcionais:
  OPENAI_MODEL        modelo (padrão: openai:gpt-5)
  LANGGRAPH_URL       servidor já em execução (padrão: http://127.0.0.1:2024 e sobe sozinho)
"""

import asyncio
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

from deepagents import AsyncSubAgent, create_deep_agent  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

MODEL = os.getenv("OPENAI_MODEL", "openai:gpt-5")
SERVER_URL = os.getenv("LANGGRAPH_URL", "http://127.0.0.1:2024")

load_dotenv()
# ===========================================================================
# PARTE 1 - Grafos servidos pelo `langgraph dev`
# ===========================================================================
@tool
async def coletar_fontes(topico: str) -> str:
    """Coleta fontes sobre um tópico. (SIMULADA: espera 10s para imitar uma busca lenta e
    devolve texto de exemplo, não dados reais.)"""
    await asyncio.sleep(10)
    return (
        f"[SIMULADO] Fontes coletadas sobre '{topico}': 3 artigos, 1 relatório, 2 posts técnicos. "
        "Use seu próprio conhecimento para o conteúdo e diga que a coleta foi simulada."
    )


researcher = create_deep_agent(
    model=MODEL,
    tools=[coletar_fontes],
    system_prompt=(
        "Você é um pesquisador. Chame coletar_fontes uma vez, depois escreva um resumo de "
        "até 8 tópicos em português do Brasil sobre o assunto pedido."
    ),
)

writer = create_deep_agent(
    model=MODEL,
    system_prompt=(
        "Você é um redator. Escreva textos claros em português do Brasil, no formato pedido. "
        "Seja objetivo e entregue o texto final."
    ),
)

# Cada AsyncSubAgent aponta para um graph_id registrado no langgraph.json.
# Sem `url` => transporte ASGI (no mesmo servidor, sem rede). Com `url` => HTTP remoto.
ASYNC_SUBAGENTS = [
    AsyncSubAgent(
        name="researcher",
        description="Pesquisa um tema em profundidade e devolve um resumo. Tarefa demorada: use em background.",
        graph_id="researcher",
    ),
    AsyncSubAgent(
        name="writer",
        description="Redige textos (artigo, e-mail, post) a partir de um briefing. Use em background.",
        graph_id="writer",
        mode="isolated",  # só recebe a descrição da tarefa; "fork" também receberia a conversa
    ),
]

supervisor = create_deep_agent(
    model=MODEL,
    subagents=ASYNC_SUBAGENTS,
    system_prompt=(
        "Você é um supervisor que responde em português do Brasil. Para tarefas demoradas de "
        "pesquisa ou redação, delegue aos subagents assíncronos com start_async_task e "
        "AVISE o usuário o task_id completo. Depois de iniciar, SEMPRE devolva o controle ao usuário: "
        "nunca chame check_async_task logo após o lançamento. Quando o usuário pedir status, chame "
        "check_async_task ou list_async_tasks antes de responder. Mostre o task_id inteiro, sem abreviar. "
        "Perguntas simples você responde direto."
    ),
)


# ===========================================================================
# PARTE 2 - Cliente de chat em loop
# ===========================================================================
def _server_up() -> bool:
    try:
        with urllib.request.urlopen(f"{SERVER_URL}/ok", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def start_server() -> subprocess.Popen | None:
    if _server_up():
        print(f"(servidor já está no ar em {SERVER_URL})")
        return None
    port = SERVER_URL.rsplit(":", 1)[-1]
    print("Subindo `langgraph dev`... (a primeira vez demora um pouco)")
    proc = subprocess.Popen(
        [str(Path(sys.executable).with_name("langgraph")), "dev", "--no-browser", "--port", port, "--n-jobs-per-worker", "10"],
        cwd=HERE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(90):
        if _server_up():
            return proc
        if proc.poll() is not None:
            sys.exit("`langgraph dev` encerrou. Rode-o manualmente nesta pasta para ver o erro.")
        time.sleep(1)
    proc.terminate()
    sys.exit("Timeout esperando o servidor subir.")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else (b if isinstance(b, str) else "")
            for b in content
        )
    return str(content)


def _clip(s: str, n: int = 500) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n] + f"... [+{len(s) - n} chars]"


def render(msg: dict) -> str | None:
    """Converte uma mensagem do estado do supervisor em uma linha legível."""
    mtype = msg.get("type")
    if mtype == "ai":
        lines = []
        for call in msg.get("tool_calls") or []:
            args = call.get("args", {})
            resumo = ", ".join(f"{k}={_clip(str(v), 80)}" for k, v in args.items())
            lines.append(f"  [supervisor] -> {call['name']}({resumo})")
        text = _text(msg.get("content", "")).strip()
        if text:
            lines.append(f"\nagente> {text}")
        return "\n".join(lines) or None
    if mtype == "tool":
        return f"  [supervisor] <- {msg.get('name')}: {_clip(_text(msg.get('content', '')), 400)}"
    if mtype == "human":
        # Notificações de subagents chegam ao supervisor como HumanMessage (metadata source=async_subagent)
        meta = (msg.get("additional_kwargs") or {}).get("notification") or {}
        if meta or _text(msg.get("content", "")).lstrip().startswith("<"):
            return f"  [notificação do subagent] {_clip(_text(msg.get('content', '')), 400)}"
    return None


async def main():
    from langgraph_sdk import get_client

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("Defina OPENAI_API_KEY (export ou arquivo .env nesta pasta).")

    proc = start_server()
    client = get_client(url=SERVER_URL)
    thread = await client.threads.create()
    thread_id = thread["thread_id"]
    seen: set[str] = set()
    busy = asyncio.Event()  # preenchido enquanto um turno em primeiro plano está rodando

    def show_new(messages: list[dict]):
        for m in messages:
            mid = m.get("id") or str(uuid.uuid4())
            if mid in seen:
                continue
            seen.add(mid)
            out = render(m)
            if out:
                print(out)

    async def watcher():
        """Mostra mensagens que surgem fora do seu turno (ex.: subagent terminou e acordou o supervisor)."""
        while True:
            await asyncio.sleep(2)
            if busy.is_set():
                continue
            try:
                state = await client.threads.get_state(thread_id)
            except Exception:  # noqa: BLE001
                continue
            msgs = (state.get("values") or {}).get("messages", [])
            before = len(seen)
            show_new(msgs)
            if len(seen) > before:
                print("\nvocê> ", end="", flush=True)

    # Marca como "vistas" as mensagens que já existirem (thread nova: nenhuma)
    watch_task = asyncio.create_task(watcher())

    print(f"\nAsync Subagents chat | modelo: {MODEL} | servidor: {SERVER_URL}")
    print("Subagents assíncronos: researcher, writer")
    print("Peça algo demorado (ex.: 'pesquise sobre RAG e, em paralelo, escreva um post sobre agentes')")
    print("e continue conversando enquanto roda. Comandos: /tarefas  /novo  /sair\n")

    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                user = (await loop.run_in_executor(None, input, "você> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user:
                continue
            if user in {"/sair", "/exit", "sair"}:
                break
            if user == "/novo":
                thread_id = (await client.threads.create())["thread_id"]
                seen.clear()
                print("(nova conversa)\n")
                continue
            if user == "/tarefas":
                user = "Liste as tarefas assíncronas com list_async_tasks e mostre os task_ids completos e o status."

            busy.set()
            try:
                async for part in client.runs.stream(
                    thread_id,
                    "supervisor",
                    input={"messages": [{"role": "user", "content": user}]},
                    stream_mode="values",
                ):
                    if part.event == "values" and isinstance(part.data, dict):
                        show_new(part.data.get("messages", []))
            except Exception as e:  # noqa: BLE001
                print(f"\n[erro] {type(e).__name__}: {e}")
            finally:
                busy.clear()
            print()
    finally:
        watch_task.cancel()
        if proc is not None:
            proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())