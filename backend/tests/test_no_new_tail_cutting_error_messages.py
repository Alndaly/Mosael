"""报错不许再按位置裁子进程的输出。

这个毛病在这个仓库里发作过**四次**,每次都在上一次修复没覆盖到的地方:

1. 合成失败 → 取到 `[end of libtorchcodec loading traceback]`(一条分隔线);
2. 装依赖失败 → 取到 ``note: run with `RUST_BACKTRACE=1` ``(一句纯提示);
3. 下权重失败 → 取到 `Downloading: 100%|██████| 1/1 [00:00<00:00, 1.39file/s]`(一根进度条);
4. 转写 / 音频提取 / 建 venv / 拉源码 / 插件崩溃 → 同样是 `stderr[-N:]`,而 funasr 和
   whisperx 同样用 tqdm、ffmpeg 同样刷进度行,撞上只是时间问题。

判据因此收在 `core/text.blame_line` 一处。这条钉的是**没有人再绕开它** ——
逐个打补丁的话,第五次还会出现在某个今天没想到的地方。
"""
from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: 一条 raise/错误消息里出现 `xxx[-123:]` 就是按位置裁。
_TAIL_SLICE = re.compile(r"\[-\d{2,4}:\]")

#: 允许保留的几处,连同理由。**只减不增**。
ALLOWED: dict[str, str] = {
    # 认不出病因时的兜底:这时候"原文的最后一段"就是唯一能给的东西,而它明说了自己是原文。
    "core/pip_install.py": "explain() 的兜底分支,前面已经说了「pip 没有说明原因」",
    # 日志不是给用户看的那句话:它要的是上下文,而完整输出另有 run_log 落盘。
    "core/child_process.py": "写日志,不是错误消息;完整输出走 core/run_log",
    # JSON 解析失败要看的是**原文**,不是"哪一行像异常" —— 那不是一段人写的错误输出,
    # 而一段截断的 JSON 里一行都不像错误,挑出来只会说成"没有原因"。
    "domain/plugins/runtime.py": "插件输出不是合法 JSON 时回显原文尾部",
    "domain/voices/transcription.py": "转写输出不是合法 JSON 时回显原文尾部(同上)",
}


def _offenders() -> list[str]:
    found = []
    for path in sorted(APP.rglob("*.py")):
        rel = str(path.relative_to(APP))
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if not _TAIL_SLICE.search(line):
                continue
            if line.lstrip().startswith("#") or line.lstrip().startswith("*"):
                continue  # 注释里讲这段历史是好事
            if "logger." in line:
                continue  # 日志要的是上下文,不是那一句话;完整输出另有 core/run_log 落盘
            if rel in ALLOWED:
                continue
            found.append(f"{rel}:{number}  {line.strip()[:80]}")
    return found


def test_no_new_tail_cutting() -> None:
    offenders = _offenders()
    assert offenders == [], (
        "又有地方按位置裁子进程输出了。用 core/text.blame_line —— 它挑的是**说明原因的那一行**,\n"
        "而不是恰好排在最后的那一行(进度条、分隔线、收尾提示都排在最后)。\n  "
        + "\n  ".join(offenders)
    )


def test_the_allow_list_has_no_stale_entries() -> None:
    """名单里的文件得真的还在裁 —— 否则这条豁免只是历史包袱。"""
    stale = []
    for rel in ALLOWED:
        path = APP / rel
        if not path.is_file() or not _TAIL_SLICE.search(path.read_text(encoding="utf-8")):
            stale.append(rel)
    assert stale == [], f"这些豁免已经用不上了,删掉:{stale}"
