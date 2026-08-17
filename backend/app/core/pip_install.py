"""装引擎依赖:声音克隆和转写共用的那一步。

两处此前各写一遍(`audio/tts_models.ensure_engine_runtime`、`audio/asr_models.ensure_runtime`),
逐行几乎相同 —— 而**只有克隆那边带了 pip 镜像**。转写引擎于是一直在直连 PyPI 拉 torch,
在国内常常慢到超时,尽管设置页那一项写着「装引擎依赖时用的 pip 索引」。同一段逻辑抄两遍,
差异就是这么来的。

更要紧的是失败之后。两处原本都是 ``(stderr or stdout)[-300:]``:按**最后 300 个字符**裁。
而 pip 失败时最后一行几乎永远是收尾提示,于是用户看到的是

    安装 f5-tts 运行依赖失败:note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace

—— 一句不含任何信息的话。真正的原因(哪个包、为什么)在它上面几十行,被裁掉了;而完整输出
没有任何地方留着(`run_logged` 的失败日志同样只留 800 字符)。结果是这个报错**根本无法诊断**,
只能请用户再跑一遍并录屏。

所以这里做两件事:**完整输出落盘**,以及错误信息按「挑出关键行」而不是「取尾巴」来生成。
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Sequence

from app.core.child_process import run_logged
from app.core.config import settings

logger = logging.getLogger(__name__)


class PipInstallError(RuntimeError):
    """装依赖失败。消息已经是给人看的:病因 + pip 自己的结论行 + 完整日志在哪。"""


#: 已知病因 → 说人话 + 下一步该干什么。按「越具体越靠前」排,取第一个命中的。
#:
#: 这张表的价值不在于覆盖全，而在于**把最常见的几种失败从「一段英文栈」翻译成一句能照做的话**。
#: 认不出来也不要紧:下面还会附上 pip 自己的结论行和完整日志路径。
_CAUSES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"MemoryError|Unable to allocate|Cannot allocate memory", re.I),
        "内存不足 —— 这些依赖要一次解开几百 MB。关掉占内存的程序后重试即可,"
        "已经下好的部分不会重下。若 Windows 上关掉了虚拟内存(页面文件),把它打开会更稳。",
    ),
    (
        re.compile(r"No space left|\[Errno 28\]|\[WinError 112\]|not enough space", re.I),
        "磁盘空间不足 —— 这些依赖要 3–4 GB。清出空间后重试。",
    ),
    (
        re.compile(r"RUST_BACKTRACE|the Rust package manager|can't find Rust compiler|rustc", re.I),
        "有依赖没有现成的安装包,要在本机用 Rust 现编译,而这一步失败了。"
        "多半是当前 Python 版本或系统还没有对应的预编译包。",
    ),
    (
        re.compile(r"Microsoft Visual C\+\+.{0,40}required|command .{0,40}cl\.exe.{0,20}failed", re.I),
        "有依赖要在本机用 C++ 编译,而这台机器没装编译工具。",
    ),
    (
        re.compile(r"No matching distribution found", re.I),
        "找不到能装的版本 —— 这个包没有适配当前 Python 版本或当前系统的发行版。",
    ),
    (
        re.compile(r"ResolutionImpossible|conflict is caused by", re.I),
        "依赖之间版本冲突,凑不出一个都满足的组合。",
    ),
    (
        re.compile(
            r"Read timed out|ConnectionError|Connection broken|Max retries exceeded"
            r"|Temporary failure in name resolution|SSLError",
            re.I,
        ),
        "下载超时或断流。可以在设置里换一个 pip 镜像再试。",
    ),
)

#: 从输出里挑「结论行」的几套办法,从最可信到最兜底。**顺序就是可信度**:
#: pip 自己以 ``ERROR:`` 开头的那几行是它对这次失败的总结,比任何位置启发式都准。
_VERDICT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^ERROR:\s*(.+)$"),
    re.compile(r"^\s*error:\s*(.+)$", re.I),
    # 裸 traceback 收尾的那句(`MemoryError: Unable to allocate output buffer.`)。
    # pip 自己崩掉时不会有 ERROR: 行,只有这句说得出发生了什么。
    re.compile(r"^([A-Za-z_][A-Za-z_0-9.]*(?:Error|Exception|Interrupt):.*)$"),
)

#: 这些行匹配得上「结论行」的形状,却什么都没说 —— 挑出来只会挤掉真正有用的那几行。
_NOISE = re.compile(
    r"^(ERROR:\s*)?("
    r"note:"
    r"|hint:"
    r"|for more information"
    r"|this error originates from"
    r"|full command:"
    r"|cwd:"
    r"|\[end of output\]"
    r")",
    re.I,
)

#: 说了点什么、但不如别的具体的行。**排后面,不是滤掉** ——
#: "Failed building wheel for X" 通常后面就跟着更完整的 "Could not build wheels for X",
#: 可万一没跟,把它也滤了就等于一行都不报。第一版正是这么写的,被测试逮住。
_WEAK = re.compile(r"^(ERROR:\s*)?(failed building wheel|could not install packages)", re.I)

#: 一条错误消息里最多放几行结论。多于此就不是"读一眼知道怎么办",而是把日志搬进弹窗。
_MAX_VERDICT_LINES = 4


def verdict_lines(output: str) -> list[str]:
    """从 pip 输出里挑出说明失败原因的那几行。

    **不取尾巴**:pip 的输出以 ``note: run with RUST_BACKTRACE=1``、``[end of output]``
    这类收尾提示结束是常态,而结论在它们上面。这和 `audio/voices.explain_worker_failure`
    里修过的是同一个毛病 —— 那次是把 ``[end of libtorchcodec loading traceback]``
    这条分隔线当成了错误原因。
    """
    picked: list[str] = []
    for raw in (output or "").splitlines():
        line = raw.strip()
        if not line or line in picked or _NOISE.match(line):
            continue
        if any(pattern.match(line) for pattern in _VERDICT_PATTERNS):
            picked.append(line)
    # 稳定排序:含糊的排后面,其余保持它们在输出里的先后 —— pip 是按发生顺序说话的,
    # 打乱顺序会让"因为 A 所以 B"读成两件不相干的事。
    picked.sort(key=lambda line: bool(_WEAK.match(line)))
    return picked[:_MAX_VERDICT_LINES]


def explain(output: str, *, log_path: Path | None = None) -> str:
    """把一次 pip 失败讲成一段人能照做的话。"""
    text = output or ""
    parts: list[str] = []
    hint = next((message for pattern, message in _CAUSES if pattern.search(text)), "")
    if hint:
        parts.append(hint)
    lines = verdict_lines(text)
    if lines:
        parts.append(" / ".join(lines)[:400])
    if not parts:
        # 一句都认不出来 —— 那就老实说没头绪,并把最后一段原文附上,而不是假装解释了什么。
        tail = text.strip()[-300:]
        parts.append(f"pip 没有说明原因。最后的输出:{tail}" if tail else "pip 没有任何输出。")
    if log_path is not None:
        parts.append(f"完整日志:{log_path}")
    return "\n".join(parts)


def _log_path(what: str) -> Path:
    """这次安装的完整输出写到哪。按时间命名 —— 重试时上一次的还在,能对比。"""
    directory = settings.data_dir / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", what).strip("-") or "pip"
    return directory / f"pip-{slug}-{time.strftime('%Y%m%d-%H%M%S')}.log"


#: 只留最近这么多份 pip 日志。一份几十 KB,留太多是往用户的数据目录里堆垃圾;
#: 而只留一份的话,「上次成功、这次失败,差在哪」就没得比。
_KEEP_LOGS = 20


def _prune_logs(directory: Path) -> None:
    try:
        logs = sorted(directory.glob("pip-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in logs[_KEEP_LOGS:]:
            stale.unlink(missing_ok=True)
    except OSError:  # 清理失败不该让安装失败 —— 它只是在打扫
        logger.debug("清理 pip 日志失败", exc_info=True)


def _common_args(index_url: str) -> list[str]:
    return [
        "--no-input",                    # 装依赖是后台任务,没有人能回答它的提问
        "--disable-pip-version-check",   # "有新版 pip" 不是这次失败的原因,别混进结论行里
        # 默认的 15 秒对着一个 2.5GB 的下载太短:国内经镜像拉 torch,握手慢一点就被判超时,
        # 而报出来的是一句语焉不详的 ConnectionError。
        "--timeout", "60",
        "--retries", "10",
        *(["--index-url", index_url] if index_url else []),
    ]


def _upgrade_pip(python: Path | str, *, index_url: str, env: dict[str, str] | None) -> None:
    """先把这个 venv 里的 pip 升上去,再让它去装几个 GB。

    venv 里的 pip 来自 ensurepip,是**打包 CPython 时冻结的那个**(3.12.11 里是 25.0.1)——
    随着应用发布得越久,它只会越旧。而它恰恰是负责下载和解压这几个 GB 的程序:断点续传、
    解压时的内存占用、失败时说人话的程度,全在后来的版本里改过。让一个越来越旧的 pip
    去干最重的那件活,没有道理。

    **失败不致命**:自带的 pip 也能装,只是少了这些改进。为了升级 pip 而让整次安装失败,
    是把辅助手段当成了前提。
    """
    try:
        result = run_logged(
            [str(python), "-m", "pip", "install", "--upgrade", *_common_args(index_url), "pip"],
            capture_output=True, text=True, timeout=600, env=env,
            what="升级 pip", level=logging.DEBUG,
        )
        if result.returncode != 0:
            logger.info("pip 自升级没成功,继续用自带的那个:%s", verdict_lines(result.stderr or "")[:1])
    except Exception:  # noqa: BLE001 — 超时 / 起不来都不该拦住接下来的安装
        logger.info("pip 自升级没跑成,继续用自带的那个", exc_info=True)


def install(
    python: Path | str,
    requirements: Sequence[str],
    *,
    what: str,
    index_url: str = "",
    timeout: int = 7200,
    env: dict[str, str] | None = None,
) -> Path:
    """把 `requirements` 装进 `python` 所在的环境。失败抛 `PipInstallError`。

    返回完整日志的路径 —— 成功时也留着,因为「上次装成了什么版本」是排查下一次失败的前提。

    `--upgrade` 让重试能修好装了一半的环境。

    `--prefer-binary` 不是保险起见,是**对症**:f5-tts 依赖 `rjieba`(Rust 写的结巴分词),
    而 rjieba 每个版本都发源码包、Windows + Python 3.12 的预编译轮子却不是每版都有。
    pip 默认按版本号挑,挑到没轮子的那版就现场编译 Rust —— 打包环境里没有 Rust 工具链,
    于是失败,而它留下的唯一一句话是
    `note: run with RUST_BACKTRACE=1 environment variable to display a backtrace`。
    `--prefer-binary` 让它优先选有现成轮子的版本,宁可版本号老一点。

    **不用 `--only-binary=:all:`**:实测 f5-tts 的依赖里 `transformers_stream_generator`
    在 PyPI 上只有源码包,一刀切会让它彻底装不上。要挡的是"为了新版本号去编译",
    不是"编译"本身。
    """
    _upgrade_pip(python, index_url=index_url, env=env)
    args = [
        str(python), "-m", "pip", "install",
        "--upgrade",
        "--prefer-binary",
        *_common_args(index_url),
        *requirements,
    ]

    result = run_logged(
        args, capture_output=True, text=True, timeout=timeout, env=env, what=what,
    )
    output = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
    path = _log_path(what)
    try:
        header = f"$ {' '.join(args)}\n退出码 {result.returncode}\n\n"
        path.write_text(header + output + "\n", encoding="utf-8")
        _prune_logs(path.parent)
    except OSError:
        logger.warning("写 pip 日志失败:%s", path, exc_info=True)
        path = None  # type: ignore[assignment]  # 写不下就别在错误里指一个不存在的文件
    if result.returncode != 0:
        raise PipInstallError(explain(output, log_path=path))
    return path
