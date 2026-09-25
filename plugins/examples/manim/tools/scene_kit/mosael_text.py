"""讲解视频里的文字:折行、朗读时长、没有 LaTeX 时公式怎么显示。

和 mosael_expr 一样,插件与场景共用这一份(只用标准库)。
"""

from __future__ import annotations

import re
import unicodedata

#: 行首不该出现的标点(中文排版的「避头」):折行时把它们留在上一行末尾。
_NO_LINE_START = set("，。、！？；：）」』】》,.!?;:)]}%")


def char_units(ch: str) -> int:
    """一个字符占几个「半角宽」:中日韩全角字符算 2,其余算 1。"""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    return sum(char_units(ch) for ch in text)


def _tokens(paragraph: str) -> list[str]:
    """切成「不可再拆」的小块:一个 CJK 字一块,一个拉丁词(连同后面的空格)一块。"""
    return re.findall(r"[A-Za-z0-9_\-+'./%$#@&*=<>^~|\\]+\s*|\s+|.", paragraph)


def wrap(text: str, max_units: int) -> list[str]:
    """按显示宽度折行。显式的换行保留;拉丁词不从中间断(太长的词才硬切)。"""
    max_units = max(4, int(max_units))
    lines: list[str] = []
    for paragraph in str(text or "").split("\n"):
        current = ""
        for token in _tokens(paragraph):
            if display_width(current + token.rstrip()) <= max_units:
                current += token
                continue
            if token.strip() and token[0] in _NO_LINE_START and current:
                current += token
                continue
            if current.strip():
                lines.append(current.rstrip())
            current = token.lstrip()
            while display_width(current) > max_units:  # 一个词比一整行还宽:硬切
                cut = 0
                width = 0
                for index, ch in enumerate(current):
                    width += char_units(ch)
                    if width > max_units:
                        cut = index
                        break
                lines.append(current[:cut])
                current = current[cut:]
        lines.append(current.rstrip())
    while lines and not lines[-1]:
        lines.pop()
    return lines or [""]


def reading_seconds(text: str) -> float:
    """念完这段话大约要几秒:中文每秒约 4.5 字,英文每分钟约 150 词。"""
    text = str(text or "")
    cjk = sum(1 for ch in text if char_units(ch) == 2)
    words = len(re.findall(r"[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*", text))
    return cjk / 4.5 + words / 2.5


# ---------------------------------------------------------------- 没有 LaTeX 时的公式

_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν",
    "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ",
    "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥",
    "ne": "≠", "neq": "≠", "approx": "≈", "equiv": "≡", "sim": "∼", "propto": "∝", "infty": "∞",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒", "Leftarrow": "⇐", "iff": "⇔",
    "Leftrightarrow": "⇔", "mapsto": "↦", "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆",
    "cup": "∪", "cap": "∩", "emptyset": "∅", "forall": "∀", "exists": "∃", "partial": "∂", "nabla": "∇",
    "sum": "Σ", "prod": "Π", "int": "∫", "oint": "∮", "ldots": "…", "cdots": "⋯", "dots": "…",
    "angle": "∠", "perp": "⊥", "parallel": "∥", "circ": "∘", "degree": "°", "neg": "¬", "land": "∧", "lor": "∨",
    "sin": "sin", "cos": "cos", "tan": "tan", "log": "log", "ln": "ln", "exp": "exp", "lim": "lim",
    "max": "max", "min": "min", "det": "det",
    "quad": "  ", "qquad": "    ", ",": " ", ";": " ", "!": "", " ": " ",
    "{": "{", "}": "}", "%": "%", "&": "&", "_": "_", "#": "#", "$": "$",
}
_SUPERSCRIPT = str.maketrans("0123456789+-=()niax", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵃˣ")
_SUBSCRIPT = str.maketrans("0123456789+-=()aeiouxhklmnpst", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒᵤₓₕₖₗₘₙₚₛₜ")


def _group(text: str, start: int) -> tuple[str, int]:
    """从 start 起取一个「参数」:`{...}`(配平括号)或者一个字符 / 一个命令。返回 (内容, 结束位置)。"""
    while start < len(text) and text[start] == " ":
        start += 1
    if start >= len(text):
        return "", start
    if text[start] == "{":
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    return text[start + 1:index], index + 1
        return text[start + 1:], len(text)
    if text[start] == "\\":
        match = re.match(r"\\([A-Za-z]+|.)", text[start:])
        if match:
            return match.group(0), start + len(match.group(0))
    return text[start], start + 1


def latex_to_plain(latex: str) -> str:
    """把一条 LaTeX 公式尽量写成一行 Unicode:`\\frac{a}{b}` → `(a)/(b)`,`x^2` → `x²`,`\\alpha` → `α`。

    **只在没装 LaTeX 时用**。它不是排版引擎:分式、根号、上下标能读懂,矩阵之类只能退成原文。
    讲解视频照样出得来,返回值里会写明「公式按纯文字显示」。
    """
    text = str(latex or "")
    out: list[str] = []
    index = 0
    while index < len(text):
        ch = text[index]
        if ch == "\\":
            match = re.match(r"\\([A-Za-z]+|.)", text[index:])
            name = match.group(1) if match else ""
            index += len(match.group(0)) if match else 1
            if name in ("frac", "dfrac", "tfrac"):
                num, index = _group(text, index)
                den, index = _group(text, index)
                a, b = latex_to_plain(num), latex_to_plain(den)
                a = a if len(a) == 1 else f"({a})"
                b = b if len(b) == 1 else f"({b})"
                out.append(f"{a}/{b}")
            elif name == "sqrt":
                degree = ""
                if index < len(text) and text[index] == "[":
                    end = text.find("]", index)
                    degree, index = text[index + 1:end], end + 1
                body, index = _group(text, index)
                inner = latex_to_plain(body)
                root = {"3": "∛", "4": "∜"}.get(degree.strip(), "√")
                out.append(f"{root}{inner}" if len(inner) == 1 else f"{root}({inner})")
            elif name in ("text", "mathrm", "mathbf", "mathit", "mathsf", "operatorname", "textbf", "textit", "boldsymbol", "vec", "hat", "bar", "overline", "mathbb", "mathcal"):
                body, index = _group(text, index)
                inner = latex_to_plain(body)
                if name == "vec":
                    inner += "⃗"
                elif name == "hat":
                    inner += "̂"
                elif name in ("bar", "overline"):
                    inner += "̅"
                elif name == "mathbb":
                    inner = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ"}.get(inner, inner)
                out.append(inner)
            elif name in ("left", "right", "big", "Big", "bigg", "Bigg", "displaystyle", "limits", "nolimits"):
                continue
            elif name == "\\":
                out.append("; ")
            else:
                out.append(_SYMBOLS.get(name, name))
        elif ch in "^_":
            inner, index = _group(text, index + 1)
            plain = latex_to_plain(inner)
            table = _SUPERSCRIPT if ch == "^" else _SUBSCRIPT
            converted = plain.translate(table)
            # 每个字符都有上 / 下标字形才换(`x²`);有一个没有就整段写成 `^(…)`,不出半截上标。
            if plain and all(conv != c for c, conv in zip(plain, converted)):
                out.append(converted)
            else:
                out.append(f"{ch}{plain}" if len(plain) == 1 else f"{ch}({plain})")
        elif ch in "{}":
            index += 1
        elif ch == "&":
            index += 1
        elif ch == "~":
            out.append(" ")
            index += 1
        else:
            out.append(ch)
            index += 1
    return re.sub(r"[ \t]{2,}", "  ", "".join(out)).strip()
