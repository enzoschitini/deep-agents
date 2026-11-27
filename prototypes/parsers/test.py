
import json
import sys
from pathlib import Path

from prototypes.parsers.parse import Parser

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

if __name__ == "__main__":
    texto = " ".join(sys.argv[1:]) or (
        "Comprei o fone na Black Friday. O som é incrível e a bateria dura o dia todo, "
        "mas a entrega atrasou uma semana e o suporte nunca respondeu meu e-mail. "
        "Se acontecer de novo, não compro mais com vocês."
    )
    print(json.dumps(Parser().parse(texto).model_dump(), ensure_ascii=False, indent=2))