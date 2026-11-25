"""Monta o HTML único da interface: template + todos os css/*.css + todos os js/*.js (ordem alfabética)."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"


def _read_all(folder: str, suffix: str) -> list[tuple[str, str]]:
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted((SRC / folder).glob(f"*{suffix}"))]


def build_html() -> str:
    """HTML completo (CSS e JS inline). Lido do disco a cada chamada: editar os fontes e recarregar a página basta."""
    template = (SRC / "index.template.html").read_text(encoding="utf-8")
    css = "\n".join(f"/* ---- {name} ---- */\n{text}" for name, text in _read_all("css", ".css"))
    js = "\n".join(f"/* ---- {name} ---- */\n{text}" for name, text in _read_all("js", ".js"))
    js = js.replace("</script", "<\\/script")
    return template.replace("/*__CSS__*/", css).replace("/*__JS__*/", js)


def check_syntax() -> list[str]:
    """Valida a sintaxe de cada arquivo JS com o QuickJS embutido (`quickjs_rs`, dependência do projeto).
    Devolve a lista de erros (vazia = tudo certo). Não executa o código: só o compila dentro de uma função."""
    import quickjs_rs

    errors: list[str] = []
    ctx = quickjs_rs.Runtime().new_context()
    try:
        for name, text in _read_all("js", ".js"):
            try:
                ctx.eval("(function(){\n" + text + "\n}); 0")   # `; 0`: o resultado (uma função) não passa para o Python
            except Exception as e:   # JSError: mensagem traz linha/coluna (linha 1 do wrapper = linha 0 do arquivo)
                errors.append(f"{name}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
        for name, text in _read_all("css", ".css"):
            if text.count("{") != text.count("}"):
                errors.append(f"{name}: chaves desbalanceadas ({text.count('{')} '{{' x {text.count('}')} '}}')")
    finally:
        ctx.close() if hasattr(ctx, "close") else None
    return errors
