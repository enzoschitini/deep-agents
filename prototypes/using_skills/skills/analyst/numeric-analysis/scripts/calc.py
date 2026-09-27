"""Safe arithmetic evaluator (same logic backing the `calculate` tool)."""
import ast
import operator as op

OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
       ast.Pow: op.pow, ast.Mod: op.mod, ast.USub: op.neg, ast.UAdd: op.pos}


def safe_eval(expr: str) -> float:
    def _ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](_ev(node.left), _ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
            return OPS[type(node.op)](_ev(node.operand))
        raise ValueError(f"Unsupported expression: {ast.dump(node)}")
    return _ev(ast.parse(expr, mode="eval").body)


if __name__ == "__main__":
    import sys
    print(safe_eval(" ".join(sys.argv[1:])))
