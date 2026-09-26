"""自定义动画的代码:渲染之前先看一眼。

## 这是什么、不是什么

自定义动画执行的是**任意 Python**,以当前用户的身份跑在这台电脑上。这里做三件事:

1. **语法**:先用 `ast` 解析。写错了当场说「第几行第几列」,不必起一次 Manim(光 import 就要好几秒)。
2. **场景**:找出代码里的场景类(继承自 `…Scene` 的类),对上调用方给的名字。有几个又没指定时不猜,列出来让他挑。
3. **护栏**:默认只准 import 画动画用得到的那些模块(manim、math、numpy、random …),不准用 `open` /
   `exec` / `__import__` 这类读写文件、动态执行的入口,也不准碰 `os.system`、`np.save` 这类属性。

**护栏不是沙箱。** Python 里绕过静态检查的办法很多,它挡的是「随手写 / 被一段网页诱导写出」的那种
明显越界的代码,而不是一个存心要逃出去的人。真正的边界是:这个工具**默认不开放**(插件页里要你自己勾上),
而且插件的权限里写明了它会在本机执行代码。需要别的库(scipy、networkx 之外的)时,在插件配置里打开
「不限制代码」,后果自负。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from plugin_kit import PluginError, line

MAX_CODE_CHARS = 100_000

#: 公式里不准用的 LaTeX 命令:读写文件、执行外部程序、改 TeX 本身的规则。讲解视频的公式整条查;自定义代码里
#: 查每一个字符串常量 —— `MathTex(r"\input{/etc/passwd}")` 不经 open 就把一个本机文件排进了画面。
FORBIDDEN_TEX = re.compile(
    r"\\(input|include|includeonly|write|write18|immediate|openin|openout|read|readline|closein|closeout|"
    r"catcode|def|edef|gdef|xdef|let|futurelet|newcommand|renewcommand|providecommand|DeclareRobustCommand|"
    r"usepackage|RequirePackage|documentclass|special|csname|endcsname|makeatletter|expandafter|directlua|"
    r"luaexec|latelua|ShellEscape|pdfshellescape|verbatiminput|lstinputlisting|jobname|message|typeout|"
    r"errmessage|scantokens|begin\s*\{\s*(filecontents|verbatim)\s*\})(?![A-Za-z])"
)


#: 默认准 import 的模块(取第一段:`from manim.utils import x` 看的是 manim)。
ALLOWED_MODULES = frozenset({
    "manim", "mosael", "math", "cmath", "random", "itertools", "functools",
    "operator", "collections", "dataclasses", "enum", "typing", "__future__", "fractions", "decimal",
    "statistics", "string", "textwrap", "colorsys", "numpy", "scipy", "networkx", "re", "json", "copy",
})
#: 读写文件、动态执行、改解释器状态的入口。
FORBIDDEN_NAMES = frozenset({
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "__builtins__", "memoryview", "exit", "quit", "help",
})
#: 不准碰的属性:进程、文件、网络,以及 numpy 的读写文件。
FORBIDDEN_ATTRIBUTES = frozenset({
    # 不列 remove / replace:`self.remove(mob)`、`str.replace` 在动画代码里天天用
    "system", "popen", "spawn", "spawnl", "spawnv", "fork", "execv", "execve", "execl", "unlink",
    "rmtree", "rmdir", "chmod", "chown", "makedirs", "mkdir", "write_text", "write_bytes",
    "read_text", "read_bytes", "save", "savez", "savez_compressed", "savetxt", "load", "loadtxt", "fromfile",
    "tofile", "genfromtxt", "memmap", "urlopen", "socket", "subprocess", "environ", "putenv", "modules",
    "loader", "f_globals", "f_locals", "f_back", "gi_frame", "co_code",
    # numpy / scipy / networkx 里不叫 save / load 的读写文件入口
    "open_memmap", "fromregex", "loadmat", "savemat", "wavfile", "write", "writelines",
})
#: 这些前缀的属性都是读写文件(networkx 的 read_gml / write_edgelist …)。
FORBIDDEN_ATTRIBUTE_PREFIXES = ("read_", "write_")
#: 不经 open 就能把本机文件读进画面的 Manim 入口:SVG、图片按路径读,`Code(code_file=…)` 读源码文件。
#: 自定义动画拿不到用户的素材(工具不收素材),所以代码里出现的路径只可能是这台电脑上的别的文件。
FORBIDDEN_CALLS = frozenset({"SVGMobject", "ImageMobject"})
FORBIDDEN_KEYWORDS = frozenset({"code_file", "file_name"})
#: 下划线开头又结尾的属性只放行这几个(`super().__init__()`、`type(self).__name__`)。
ALLOWED_DUNDERS = frozenset({"__init__", "__name__", "__doc__", "__len__", "__iter__", "__call__", "__qualname__"})


@dataclass(frozen=True)
class CheckedCode:
    scene: str
    scenes: list[str]


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def scene_classes(tree: ast.Module) -> list[str]:
    """代码里的场景类:直接或间接继承自 `…Scene` 的类(按出现顺序)。"""
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [_base_name(base) for base in node.bases]
        if any(base.endswith("Scene") or base in names for base in bases):
            names.append(node.name)
    return names


def violations(tree: ast.Module) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        where = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_MODULES:
                    found.append((where, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if node.level or module not in ALLOWED_MODULES:
                found.append((where, f"from {'.' * node.level}{node.module or ''} import …"))
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append((where, node.id))
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if (attr in FORBIDDEN_ATTRIBUTES or attr.startswith(FORBIDDEN_ATTRIBUTE_PREFIXES)
                    or attr in FORBIDDEN_CALLS
                    or (attr.startswith("__") and attr.endswith("__") and attr not in ALLOWED_DUNDERS)):
                found.append((where, f".{attr}"))
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_CALLS:
            found.append((where, node.id))
        elif isinstance(node, ast.keyword) and node.arg in FORBIDDEN_KEYWORDS:
            found.append((where, f"{node.arg}="))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and (bad := FORBIDDEN_TEX.search(node.value)):
            found.append((where, bad.group(0)))
    return sorted(set(found))


def check(code: str, scene: str, locale: str, *, unrestricted: bool = False) -> CheckedCode:
    """校验一段自定义动画代码,返回要渲染的场景名。不合格抛 PluginError(说得出第几行)。"""
    if not code.strip():
        raise PluginError(line(locale, "代码是空的。", "The code is empty."))
    if len(code) > MAX_CODE_CHARS:
        raise PluginError(line(locale, f"代码太长(最多 {MAX_CODE_CHARS} 字符)。", f"The code is too long (max {MAX_CODE_CHARS} characters)."))
    try:
        tree = ast.parse(code, filename="scene.py")
    except SyntaxError as exc:
        source = (exc.text or "").rstrip("\n")
        pointer = f"\n    {source}" if source.strip() else ""
        raise PluginError(line(
            locale,
            f"第 {exc.lineno} 行第 {exc.offset or 0} 列语法错误:{exc.msg}{pointer}",
            f"Syntax error at line {exc.lineno}, column {exc.offset or 0}: {exc.msg}{pointer}",
        )) from exc
    scenes = scene_classes(tree)
    if not scenes:
        raise PluginError(line(
            locale,
            "代码里没有场景类。写一个 `class 名字(Scene):`,在 `construct(self)` 里做动画。",
            "No scene class found. Define `class Name(Scene):` and animate in `construct(self)`.",
        ))
    wanted = scene.strip()
    if wanted and wanted not in scenes:
        raise PluginError(line(locale, f"找不到场景「{wanted}」。代码里有:{'、'.join(scenes)}",
                               f"Scene \"{wanted}\" not found. The code defines: {', '.join(scenes)}"))
    if not wanted:
        if len(scenes) > 1:
            raise PluginError(line(locale, f"代码里有 {len(scenes)} 个场景({'、'.join(scenes)}),用 scene 指定渲染哪一个。",
                                   f"The code defines {len(scenes)} scenes ({', '.join(scenes)}); pass scene to pick one."))
        wanted = scenes[0]
    if not unrestricted:
        found = violations(tree)
        if found:
            listed = "\n".join(f"- {line(locale, f'第 {lineno} 行:{what}', f'line {lineno}: {what}')}" for lineno, what in found[:12])
            raise PluginError(line(
                locale,
                "代码用到了不准用的东西(自定义动画默认只准画画,不准读写文件、起进程、动态执行):\n" + listed
                + f"\n能 import 的:{'、'.join(sorted(ALLOWED_MODULES))}。"
                "确实需要的话,在插件配置里打开「不限制代码」。",
                "The code uses things that are not allowed (custom animations may draw, not read or write files, start processes or run dynamic code):\n"
                + listed + f"\nAllowed imports: {', '.join(sorted(ALLOWED_MODULES))}. "
                "If you really need more, turn on \"Unrestricted code\" in the plugin settings.",
            ))
    return CheckedCode(scene=wanted, scenes=scenes)
