"""
Chat em loop para testar Dynamic Subagents do Deep Agents (LangChain) com OpenAI.

Como funciona:
  - O agente principal tem o CodeInterpreterMiddleware (ferramenta `eval`, um REPL JavaScript).
  - Dentro do `eval`, o modelo escreve JS e chama `task({description, subagentType, responseSchema?})`
    para despachar subagents em loops / em paralelo (Promise.all).
  - Escrever a palavra "workflow" no pedido é o gatilho para o agente orquestrar via código.

Uso:
  pip install deepagents langchain-quickjs langchain-openai
  export OPENAI_API_KEY=sk-...
  python dynamic_subagents_chat.py

Variáveis opcionais:
  OPENAI_MODEL   modelo do agente principal e dos subagents (padrão: openai:gpt-5)
  SHOW_CODE=0    esconde o código JS que o agente escreve no eval (padrão: mostra)
"""

import json
import os
import sys
import uuid
from dotenv import load_dotenv

from deepagents import create_deep_agent
from langchain_quickjs import CodeInterpreterMiddleware
from langgraph.checkpoint.memory import InMemorySaver

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "openai:gpt-5")
SHOW_CODE = os.getenv("SHOW_CODE", "1") != "0"

# ---------------------------------------------------------------------------
# Subagents disponíveis para o task() dentro do interpretador.
# O name e a description são o que o agente principal usa para escolher o papel.
# ---------------------------------------------------------------------------
SUBAGENTS = [
    {
        "name": "analista",
        "description": "Analisa um item isolado (texto, ideia, trecho de código, ticket) e devolve pontos fortes, "
        "riscos e uma nota de 0 a 10.",
        "system_prompt": "Você é um analista objetivo. Analise apenas o item recebido. "
        "Seja direto, cite evidências do próprio item e dê uma nota de 0 a 10.",
    },
    {
        "name": "classificador",
        "description": "Classifica um item em uma categoria dada (ex.: bug, feature, pergunta) e justifica em 1 frase.",
        "system_prompt": "Você classifica itens. Responda só com a categoria escolhida e uma justificativa de 1 frase.",
    },
    {
        "name": "criador",
        "description": "Gera uma proposta/solução independente para um problema (útil para gerar várias opções).",
        "system_prompt": "Você propõe soluções criativas e concretas. Entregue uma proposta curta e específica.",
    },
    {
        "name": "juiz",
        "description": "Compara duas ou mais opções e escolhe a melhor segundo um critério, explicando em 2 frases.",
        "system_prompt": "Você é um juiz imparcial. Compare as opções pelo critério dado, escolha UMA e justifique em 2 frases.",
    },
    {
        "name": "verificador",
        "description": "Verifica de forma independente se uma afirmação ou achado é verdadeiro/procedente. "
        "Responde com veredito (confirmado/refutado) e motivo.",
        "system_prompt": "Você é um verificador cético. Tente refutar a afirmação. "
        "Dê veredito 'confirmado' ou 'refutado' e o motivo em 1-2 frases.",
    },
]

SYSTEM_PROMPT = (
    "Você é um assistente que responde em português do Brasil. "
    "Quando o pedido contiver a palavra 'workflow', orquestre o trabalho pelo interpretador (`eval`), "
    "despachando subagents com task() a partir de código JS (loops, Promise.all, votação etc.) "
    "e sintetize o resultado no final. Para pedidos simples, responda direto, sem subagents."
)

EXEMPLOS = [
    "Rode um workflow que classifique estes tickets e depois analise cada um com o subagent certo: "
    "'app fecha ao abrir câmera', 'queria modo escuro', 'como exporto em PDF?', 'login dá erro 500'.",
    "Rode um workflow que gere 4 nomes para um app de finanças pessoais, faça um torneio com o juiz e mostre o vencedor.",
    "Rode um workflow de verificação adversarial: liste 5 afirmações sobre Python e confirme cada uma com 3 verificadores em paralelo, "
    "mantendo só as que a maioria confirmar.",
]


def build_agent():
    return create_deep_agent(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        subagents=SUBAGENTS,
        # subagents=True (padrão) expõe o task() global dentro do eval.
        # mode="thread" (padrão) mantém as variáveis JS entre as mensagens do chat.
        middleware=[CodeInterpreterMiddleware(subagents=True, max_subagent_concurrency=8)],
        checkpointer=InMemorySaver(),
    )


# ---------------------------------------------------------------------------
# Helpers para mostrar o que acontece por dentro (agente principal x subagents)
# ---------------------------------------------------------------------------
def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def _clip(s: str, n: int = 600) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n] + f"... [+{len(s) - n} chars]"

    
def _who(ns: tuple) -> str:
    return "agente" if not ns else "subagent[" + "/".join(p.split(":")[0] for p in ns) + "]"


def _messages_from_update(update):
    if not isinstance(update, dict):
        return []
    msgs = update.get("messages")
    if msgs is None:
        return []
    # Pode vir embrulhado (ex.: Overwrite) em alguns middlewares
    msgs = getattr(msgs, "value", msgs)
    return msgs if isinstance(msgs, list) else [msgs]


def _show_subagent_event(event: dict, active: dict) -> None:
    """Mostra o ciclo de vida de um subagent despachado de dentro do eval (stream `custom`).

    O `id` é chave de idempotência: se o eval for reexecutado, o `start` repete o mesmo id.
    """
    sid, phase = event.get("id"), event.get("phase")
    if phase == "start":
        if sid in active:
            return
        active[sid] = {"type": event.get("subagent_type", "?"), "label": event.get("label", "")}
        print(
            f"\n  ▶ criando/chamando subagent '{active[sid]['type']}' "
            f"({len(active)} em andamento)\n"
            f"      tarefa: {_clip(event.get('description', ''), 160)}"
        )
    elif phase in {"complete", "error"}:
        info = active.pop(sid, {"type": "?", "label": ""})
        secs = event.get("duration_ms", 0) / 1000
        if phase == "complete":
            print(f"  ✔ subagent '{info['type']}' terminou em {secs:.1f}s ({len(active)} em andamento)")
        else:
            print(f"  ✖ subagent '{info['type']}' falhou em {secs:.1f}s: {_clip(event.get('error', ''), 200)}")


def run_turn(agent, user_text: str, thread_id: str) -> str:
    """Executa um turno e imprime o fluxo. Retorna a resposta final do agente principal."""
    final = ""
    active: dict[str, dict] = {}  # subagents dinâmicos em execução, por id
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
    inputs = {"messages": [{"role": "user", "content": user_text}]}

    print("\n⏳ processando o pedido...")
    stream = agent.stream(inputs, config, stream_mode=["updates", "custom"], subgraphs=True)
    for ns, mode, chunk in stream:
        if mode == "custom":
            if isinstance(chunk, dict) and chunk.get("type") == "subagent":
                _show_subagent_event(chunk, active)
            continue

        for _node, update in chunk.items():
            for msg in _messages_from_update(update):
                mtype = getattr(msg, "type", "")
                who = _who(ns)

                if mtype == "ai":
                    for call in getattr(msg, "tool_calls", []) or []:
                        name, args = call["name"], call.get("args", {})
                        if name == "eval":
                            code = args.get("code") or json.dumps(args, ensure_ascii=False)
                            print(f"\n[{who}] -> eval (JS): orquestrando via código, subagents serão despachados com task()")
                            if SHOW_CODE:
                                print("    " + _clip(code, 1800).replace("\n", "\n    "))
                        elif name == "task":
                            print(f"\n[{who}] -> task: {args.get('subagent_type')} | {_clip(str(args.get('description', '')), 160)}")
                        else:
                            print(f"\n[{who}] -> {name}")
                    text = _text(msg.content).strip()
                    if text and not getattr(msg, "tool_calls", None):
                        if ns:  # resposta final de um subagent
                            print(f"[{who}] resposta: {_clip(text, 300)}")
                        else:
                            final = text

                elif mtype == "tool":
                    print(f"[{who}] <- {msg.name}: {_clip(_text(msg.content), 500)}")

    return final


def main():
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("Defina a variável OPENAI_API_KEY antes de rodar (export OPENAI_API_KEY=sk-...).")

    agent = build_agent()
    thread_id = str(uuid.uuid4())  # mesma thread = variáveis JS persistem entre mensagens

    print(f"Dynamic Subagents chat | modelo: {MODEL}")
    print("Subagents:", ", ".join(s["name"] for s in SUBAGENTS))
    print("Dica: use a palavra 'workflow' para ativar a orquestração por código.")
    print("Comandos: /exemplos  /novo (nova conversa)  /sair\n")

    while True:
        try:
            user = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user in {"/sair", "/exit", "sair"}:
            break
        if user == "/novo":
            thread_id = str(uuid.uuid4())
            print("(nova conversa)\n")
            continue
        if user == "/exemplos":
            for i, ex in enumerate(EXEMPLOS, 1):
                print(f"  {i}. {ex}")
            print("  (copie e cole um deles)\n")
            continue

        try:
            answer = run_turn(agent, user, thread_id)
        except Exception as e:  # noqa: BLE001 - é um script de teste, mostramos o erro e seguimos
            print(f"\n[erro] {type(e).__name__}: {e}\n")
            continue
        print(f"\nagente> {answer}\n")


if __name__ == "__main__":
    main()