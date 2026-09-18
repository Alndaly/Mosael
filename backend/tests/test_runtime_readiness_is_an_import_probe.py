"""「这个本机引擎跑不跑得起来」只有一种回答方式:**起子进程 import 一次**。

这条是付过账才写下的。分离引擎此前的判据是 `venv/bin/python` 这个文件在不在,于是一个 pip
装到一半断掉的环境 —— 解释器建好了、依赖没齐 —— 在设置页上写着「已安装」,而 `ensure_runtime`
看到"已安装"就早返回、永远不去修它。用户看到三个字「已安装」,配一句
「这个运行环境里没有 demucs:No module named 'numpy'」:两句话都没说谎,只是在回答不同的问题。

转写那边(`asr_models.runtime_ready`)早就是 import 探测,克隆那边也是。这条棘轮守的就是
**不许再出现第四种判据**,以及探测实现不许再分叉 —— asr 那份注释里「全项目唯一的探测实现」
这句话,此前正是被 `transcription.resolve_transcription_runtime` 那第二份实现悄悄变成假话的。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

#: 允许起子进程做引擎探测的地方。每一个都是那条运行时自己的**唯一**探测实现:
#: asr_models.probe / _resolve_python、tts_models(克隆引擎)、config(用户自带的解释器)、
#: separation_models.probe_runtime。加第五个之前先问:它是不是该并进已有的那一份。
PROBE_MODULES = frozenset({
    "ai/runtime/asr_models.py",
    "ai/runtime/tts_models.py",
    "ai/runtime/config.py",
    "ai/runtime/separation_models.py",
})

#: `python -c "import x"` 这种探测的形状。
_PROBE = re.compile(r'"-c",\s*(f?"import |code\b)')

#: 「解释器这个文件在不在」当判据的形状。
_FILE_AS_VERDICT = re.compile(r"managed_venv_python\([^)]*\)\.is_file\(\)")


def _sources() -> list[tuple[str, str]]:
    return [(str(path.relative_to(APP)), path.read_text(encoding="utf-8")) for path in APP.rglob("*.py")]


def test_引擎探测不许再分叉() -> None:
    offenders = sorted(name for name, text in _sources() if _PROBE.search(text) and name not in PROBE_MODULES)
    assert not offenders, (
        "这些地方自己起子进程探引擎,而每条运行时的探测应当只有一份(缓存、候选名单、失败原因都在那一份里)。"
        f"并进对应的 runtime 模块:{offenders}"
    )


def test_跑不跑得起来不许拿文件在不在回答() -> None:
    """`managed_venv_python(...).is_file()` 只回答得了"解释器在不在",而问题是"跑不跑得起来"。

    分离模块里留着一处:它回答的是**另一个**问题 —— 探测说跑不起来、而解释器确实在,那就是
    "环境半装",界面据此说「运行环境不完整,点安装补上」而不是光秃秃一句「未安装」。
    """
    offenders = sorted(
        name for name, text in _sources()
        if _FILE_AS_VERDICT.search(text) and name != "ai/runtime/separation_models.py"
    )
    assert not offenders, f"装没装的判据是 import 得进来,不是这个文件在不在:{offenders}"


def test_分离的探测就是那一处() -> None:
    """`probe_runtime` 之外不许有第二个人问同一个问题 —— 两份实现就是两个答案。"""
    source = (APP / "ai/runtime/separation_models.py").read_text(encoding="utf-8")
    assert len(_PROBE.findall(source)) == 1, "分离引擎的探测只该有一处(probe_runtime)"

    from app.ai.providers.adapters.local.demucs_separation import DemucsSeparationAdapter

    adapter_source = Path(
        str(APP / "ai/providers/adapters/local/demucs_separation.py")
    ).read_text(encoding="utf-8")
    assert "separation_models.runtime_ready" in adapter_source, (
        "Adapter 要把这个问题转给 separation_models,而不是自己判一遍"
    )
    assert DemucsSeparationAdapter.engine_id in (spec.id for spec in _specs()), "Adapter 的引擎 id 要在目录里"


def _specs():
    from app.ai.runtime.separation_models import ENGINES

    return ENGINES.values()
