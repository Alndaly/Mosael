"""讲解视频里「画一条函数曲线」用的表达式:**只认算式,不执行代码**。

讲解视频是「给内容就出片、不写代码」的那条路 —— 所以 `sin(x) + x^2/4` 这样一句话**绝不能**交给
`eval`:那等于让任何一段文字都能在用户的电脑上跑 Python。这里用 `ast` 解析,只放行数字、`x`、
四则运算与乘方、以及白名单里的数学函数和常数,求值也是自己走语法树,不经 `eval`。

插件(宿主那一侧,校验与估算 y 范围)和场景(Manim 那一侧,真正画线)用的是同一份文件 ——
渲染时它被拷进这次渲染的工作目录。所以这里**只用标准库**。
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Callable

#: 能调的函数。`log(x)` 是自然对数,`log(x, b)` 以 b 为底。
FUNCTIONS: dict[str, Callable[..., float]] = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "arcsin": math.asin, "arccos": math.acos, "arctan": math.atan,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "exp": math.exp, "log": math.log, "ln": math.log, "log10": math.log10, "log2": math.log2,
    "sqrt": math.sqrt, "abs": abs, "floor": math.floor, "ceil": math.ceil,
    "min": min, "max": max,
    "sign": lambda v: math.copysign(1.0, v) if v else 0.0,
}
#: 每个函数收几个参数(下限, 上限)。
ARITY: dict[str, tuple[int, int]] = {name: (1, 1) for name in FUNCTIONS}
ARITY.update({"log": (1, 2), "min": (2, 4), "max": (2, 4)})
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "π": math.pi}
VARIABLE = "x"
MAX_LENGTH = 200

_BINARY = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
           ast.Div: lambda a, b: a / b, ast.Pow: lambda a, b: a ** b, ast.Mod: lambda a, b: a % b}
_UNARY = {ast.UAdd: lambda a: +a, ast.USub: lambda a: -a}


class ExpressionError(ValueError):
    """写法不对。文字是给人看的(中英两份由调用方挑),`detail` 是出错的那一截。"""

    def __init__(self, zh: str, en: str) -> None:
        super().__init__(zh)
        self.zh, self.en = zh, en


def normalize(text: str) -> str:
    """把人常写的样子换成 Python 的算式:`y = 2x^2` → `2*x**2`。"""
    raw = str(text or "").strip()
    raw = re.sub(r"^\s*(?:y|f\s*\(\s*x\s*\))\s*=", "", raw)
    for old, new in (("^", "**"), ("×", "*"), ("·", "*"), ("÷", "/"), ("−", "-"), ("π", "pi")):
        raw = raw.replace(old, new)
    # 省略的乘号:`2x`、`3(x+1)`、`2pi`、`)(`、`)x`。数字前面是字母时不补(`log10(x)`、`log2`)。
    raw = re.sub(r"(?<![A-Za-z_\d.])(\d+(?:\.\d+)?)\s*([A-Za-z(])", r"\1*\2", raw)
    raw = re.sub(r"\)\s*([A-Za-z(\d])", r")*\1", raw)
    return raw.strip()


def parse(text: str) -> ast.Expression:
    """解析并校验;不合规就抛 ExpressionError(说得出是哪一截)。"""
    source = normalize(text)
    if not source:
        raise ExpressionError("函数表达式是空的。", "The function expression is empty.")
    if len(source) > MAX_LENGTH:
        raise ExpressionError(f"函数表达式太长(最多 {MAX_LENGTH} 字)。", f"The expression is too long (max {MAX_LENGTH}).")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"函数表达式写法有误:{text}", f"Invalid function expression: {text}") from exc
    for node in ast.walk(tree):
        _check(node, text)
    return tree


def _check(node: ast.AST, text: str) -> None:
    if isinstance(node, (ast.Expression, ast.Load)) or type(node) in _BINARY or type(node) in _UNARY:
        return
    if isinstance(node, (ast.BinOp, ast.UnaryOp)):
        op = node.op
        if type(op) in _BINARY or type(op) in _UNARY:
            return
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return
        raise ExpressionError(f"表达式里只能有数字:{node.value!r}", f"Only numbers are allowed: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id == VARIABLE or node.id in CONSTANTS or node.id in FUNCTIONS:
            return
        raise ExpressionError(
            f"不认识「{node.id}」。自变量写 x,能用的函数:{', '.join(sorted(FUNCTIONS))};常数:pi、e。",
            f"Unknown name \"{node.id}\". Use x as the variable; functions: {', '.join(sorted(FUNCTIONS))}; constants: pi, e.",
        )
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
            name = node.func.id if isinstance(node.func, ast.Name) else "?"
            raise ExpressionError(f"不能调用「{name}」。", f"\"{name}\" cannot be called.")
        low, high = ARITY[node.func.id]
        if not low <= len(node.args) <= high:
            raise ExpressionError(f"{node.func.id} 的参数个数不对。", f"Wrong number of arguments for {node.func.id}.")
        return
    raise ExpressionError(f"表达式里不能有这种写法:{text}", f"This is not allowed in an expression: {text}")


def _eval(node: ast.AST, x: float) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body, x)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return x if node.id == VARIABLE else CONSTANTS[node.id]
    if isinstance(node, ast.BinOp):
        return float(_BINARY[type(node.op)](_eval(node.left, x), _eval(node.right, x)))
    if isinstance(node, ast.UnaryOp):
        return float(_UNARY[type(node.op)](_eval(node.operand, x)))
    if isinstance(node, ast.Call):
        return float(FUNCTIONS[node.func.id](*(_eval(arg, x) for arg in node.args)))  # type: ignore[union-attr]
    raise ValueError("unreachable")


def compile_function(text: str) -> Callable[[float], float | None]:
    """表达式 → 函数。定义域外(log 负数、除以零、溢出)返回 None,而不是抛出来打断整张图。"""
    tree = parse(text)

    def f(x: float) -> float | None:
        try:
            value = _eval(tree, float(x))
        except (ArithmeticError, ValueError, TypeError):
            return None
        return value if isinstance(value, float) and math.isfinite(value) else None

    return f


def sample(f: Callable[[float], float | None], x_min: float, x_max: float, count: int = 400) -> list[tuple[float, float | None]]:
    count = max(2, int(count))
    step = (x_max - x_min) / (count - 1)
    return [(x_min + i * step, f(x_min + i * step)) for i in range(count)]


def auto_y_range(points: list[tuple[float, float | None]]) -> tuple[float, float]:
    """按采样点给一个看得清的 y 范围。

    取 2%–98% 分位而不是最值:`tan(x)` 在渐近线旁的一个点就能把范围撑到 10^16,整条曲线被压成一根横线。
    """
    ys = sorted(y for _, y in points if y is not None)
    if not ys:
        return (-1.0, 1.0)
    lo = ys[int(len(ys) * 0.02)]
    hi = ys[min(len(ys) - 1, int(len(ys) * 0.98))]
    if hi - lo < 1e-9:
        return (lo - 1.0, hi + 1.0)
    pad = (hi - lo) * 0.1
    return (lo - pad, hi + pad)


def segments(points: list[tuple[float, float | None]], y_min: float, y_max: float) -> list[list[tuple[float, float]]]:
    """把采样点切成**连续的几段**:定义域外的点、跑出画面太远的点、渐近线两侧的跳变都是断点。

    Manim 画一条线要的是连续的点;把 `1/x` 在 0 两侧的点连起来,画面上就多出一根竖线。
    """
    span = y_max - y_min
    lo, hi = y_min - span, y_max + span
    out: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    previous: float | None = None
    for x, y in points:
        broken = y is None or not lo <= y <= hi or (previous is not None and abs(y - previous) > span)
        if broken:
            if len(current) >= 2:
                out.append(current)
            current = []
            previous = None
            if y is not None and lo <= y <= hi:
                current = [(x, y)]
                previous = y
            continue
        current.append((x, y))  # type: ignore[arg-type]
        previous = y
    if len(current) >= 2:
        out.append(current)
    return out


def nice_step(low: float, high: float, target: int = 6) -> float:
    """刻度间隔取 1 / 2 / 5 × 10^k,让大约 `target` 个刻度落在范围里。"""
    span = abs(high - low)
    if span <= 0 or not math.isfinite(span):
        return 1.0
    raw = span / max(1, target)
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 5, 10):
        if raw <= factor * magnitude:
            return float(factor * magnitude)
    return float(10 * magnitude)


def ticks(low: float, high: float, step: float) -> list[float]:
    """范围里落在 step 整数倍上的刻度值(不含 0 以外的浮点噪声)。"""
    first = math.ceil(low / step - 1e-9)
    last = math.floor(high / step + 1e-9)
    return [round(i * step, 10) for i in range(first, last + 1)]


def format_tick(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"
