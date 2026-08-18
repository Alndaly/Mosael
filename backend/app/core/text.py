"""给人看的文字上的小工具。叶子模块 —— 不 import 任何 app 内部的东西。"""

from __future__ import annotations

import re

#: CSI 序列(颜色、光标移动)以及 OSC 序列(设置标题之类)。
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def strip_ansi(text: str) -> str:
    """去掉终端转义序列。

    子进程(pip、huggingface_hub、rich 的彩色 traceback)默认当自己在终端里,输出带颜色码。
    这些文字的去处常常是**浏览器**:任务的 error 字段、下载失败的提示、日志页。转义序列在
    那里不会变成颜色,只会变成 `[1;35m` 这样的乱码画在句子中间 —— 用户截图里就是这样。

    所以凡是"子进程说的话 → 界面"这条路上,都要先过这里一次。
    """
    return _ANSI.sub("", text)


#: 长得像异常的那一行:`ModuleNotFoundError: No module named 'natsort'`。
_EXCEPTION_LINE = re.compile(r"\b\w*(Error|Exception)\b\s*:")

#: 进度行。**它们写在 stderr 上**,所以"取 stderr 最后一行当错误原因"撞上的往往就是它们。
#:
#: 两种形态都要认:tqdm / rich 的
#: `Downloading: 100%|██████| 1/1 [00:00<00:00, 1.39file/s]`,以及 ffmpeg 的
#: `frame=  100 fps= 25 q=28.0 size=  256kB time=00:00:04.00 bitrate= 524.3kbits/s speed=1.02x`
#: —— 后者出现在音频提取、参考音频处理这几条路上,而它们同样在拿 stderr 的尾巴报错。
_PROGRESS_LINE = re.compile(
    r"\d+%\s*\|"                                   # tqdm 的百分比 + 条
    r"|\|\s*\d+/\d+\s*\["                          # `| 1/1 [`
    r"|\d+(\.\d+)?\s*(it|file|[kMG]?i?[Bb])/s"      # 1.39file/s、12.3MB/s、524.3kbits/s
    r"|^frame=\s*\d+.*\bspeed=",                    # ffmpeg 的进度行
    re.M,
)

#: 说不出原因的行。挑"最后一行"时撞上的就是这些。
_NOISE_LINE = re.compile(
    r"^(?:"
    r"[\^~]+"                                  # 终端里指向出错列的记号,到了浏览器只是噪声
    r"|[-=_]{3,}"                              # 分隔线
    r"|note:.*|hint:.*"
    r"|\[end of [^\]]*\]\.?"                   # `[end of libtorchcodec loading traceback].`
    r"|File \".*\", line \d+.*"                # traceback 的位置行
    r"|Traceback \(most recent call last\):"
    r"|During handling of the above exception.*"
    r"|The above exception was the direct cause.*"
    r")$",
    re.I,
)


def blame_line(output: str, *, fallback: str = "") -> str:
    """从子进程的输出里挑出**说明失败原因**的那一行。

    **不是最后一行。** 这一条已经踩过三次,每次都是同一个形状:

    - 合成失败时取到 `[end of libtorchcodec loading traceback].` —— 一条分隔线;
    - 装依赖失败时取到 ``note: run with `RUST_BACKTRACE=1` ...`` —— 一句纯提示;
    - 下载权重失败时取到 `Downloading: 100%|██████| 1/1 [00:00<00:00, 1.39file/s]` ——
      一根**进度条**(huggingface_hub 的 tqdm 写在 stderr 上,下完就停在那儿)。

    三次都让用户对着一句和病因毫无关系的话发愣。所以判据放在一处:先从后往前找长得像异常的
    那一行,找不到再从后往前找第一行**不是噪声也不是进度条**的。都没有就用 `fallback` ——
    编一个原因比说不知道更糟。

    完整输出仍然进日志。界面要的是一句话,排查要的是全文,两者不是同一个东西。
    """
    text = strip_ansi(output or "")
    # `splitlines()` 把 `\r` 也当行分隔符,所以 tqdm 在同一行里重画的那十几帧本来就被拆开了 ——
    # 不需要再拆一次(试过,是段死代码)。
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return fallback
    exception = next((line for line in reversed(lines) if _EXCEPTION_LINE.search(line)), None)
    if exception:
        return exception
    meaningful = next(
        (line for line in reversed(lines) if not _NOISE_LINE.match(line) and not _PROGRESS_LINE.search(line)),
        None,
    )
    return meaningful or fallback
