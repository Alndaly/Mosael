"""**由另一个解释器当脚本跑的**那几个文件。

它们不在后端进程里 import,而是被引擎自己的 venv 起成子进程(`python workers/tts.py …`)。
所以这里有一条硬规则:

    **这个目录下的文件不许 import app.***

那个解释器的 sys.path 上没有本仓库,import 会在运行时炸,而单测里它们从来不被 import,
所以炸不出来 —— 用户那边表现为"点了下载/合成,转半天然后一句看不懂的报错"。

单独成目录就是为了让这条规则有个地方可写。此前它们和 tts_models / asr_models(应用进程里
跑的模型管理)平铺在一起,一眼分不出哪些是"我们自己的代码"、哪些是"要交给别人跑的脚本"。

路径由 `workers.tts_script()` / `workers.asr_script()` 给出 —— **不要在别处用
`__file__.with_name()` 拼**:打包检查(test_frozen_build_is_not_a_python_interpreter)正是
顺着 with_name 去发现"哪些脚本要被当文件打开"的,在别的目录里拼一份会让它去找不存在的路径。
"""

from pathlib import Path

_HERE = Path(__file__).resolve().parent


def tts_script() -> Path:
    """语音合成 worker。由引擎 venv 的解释器跑。"""
    return _HERE / "tts.py"


def asr_script() -> Path:
    """语音识别 worker。同上。"""
    return _HERE / "asr.py"
