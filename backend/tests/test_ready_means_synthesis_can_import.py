"""「引擎已就绪」要用**合成真正 import 的东西**来判,不是用一个顶层包名。

用户点了生成配音,拿到的是这个:

    ModuleNotFoundError: No module named 'natsort'
      File ".../fish_speech/utils/__init__.py", line 3, in <module>
        from .file import get_latest_checkpoint

而设置页那一刻写着「引擎已就绪,合成为真实音色」。两句话都出自这个仓库,而它们查的不是
同一件事:

    探测:  import fish_speech                    ← 一个空的包 __init__,永远成功
    合成:  from fish_speech.utils.schema import …
           from tools.server.inference import …   ← 这些才会真的去拉依赖

**探测查得比真实路径浅,就等于没查。** 这一整轮反复出现的同一个形状:一个乐观的检查替真正
的操作背书,然后操作在用户面前失败。

实测补齐这台机器需要的包时,依次撞出 natsort → pytorch_lightning → lightning → audiotools
→ dac 五轮 —— 而其中 `descript-audiotools` / `descript-audio-codec` **连 fish 自己的
pyproject 都没声明**。也就是说"照它的清单装"同样不够。唯一站得住的判据是:把合成要 import
的那几行,原样在探测里跑一遍。
"""

from __future__ import annotations

from app.audio import tts_models


def test_the_probe_imports_what_synthesis_imports(monkeypatch) -> None:
    """探测语句里要出现合成真正用到的模块,而不是只有顶层包。

    这里把"检出和权重都在"喂进去,而不是指望跑测试的机器上正好装着 —— 一条要看机器脸色的
    测试,红了绿了都说明不了问题。
    """
    from app.domain import tts_config

    monkeypatch.setattr(
        tts_config, "get",
        lambda: tts_config.TtsRuntimeConfig(
            engine="fish-speech", python_path="", source="hf",
            fish_repo_dir="/tmp/fish-src", fish_model_dir="/tmp/fish-model",
        ),
    )
    monkeypatch.setattr(tts_config.TtsRuntimeConfig, "resolved_fish_repo", property(lambda self: "/tmp/fish-src"))
    monkeypatch.setattr(tts_config.TtsRuntimeConfig, "resolved_fish_model", property(lambda self: "/tmp/fish-model"))

    code = tts_models._probe_code("fish-speech")

    assert code is not None, "检出和权重都在时,不该判成「谈不上就绪」"
    assert "tools.server.inference" in code, code
    assert "fish_speech.utils" in code, code


def test_f5_probes_the_class_it_actually_constructs() -> None:
    """F5 合成走 `from f5_tts.api import F5TTS` —— 探测就该走同一行。

    `import f5_tts` 只证明包在,证明不了 api 子模块的依赖齐了。
    """
    code = tts_models._probe_code("f5-tts")

    assert "f5_tts.api" in code, code


def test_every_engine_declares_what_synthesis_imports() -> None:
    """新加引擎时,这张表必须跟着写 —— 否则它的探测又会退化成"包在不在"。"""
    for engine in tts_models.CATALOG:
        imports = tts_models.ENGINE_IMPORTS.get(engine.id)
        assert imports, f"{engine.id} 没声明合成要 import 什么"
        assert all("." in module for module in imports), (
            f"{engine.id} 只写了顶层包名({imports}) —— 那正是这条测试要挡的东西"
        )


def test_the_requirements_cover_what_the_probe_needs() -> None:
    """实测补出来的那几个包要落在依赖表里,否则下次装一台新机器又是同样五轮。

    其中两个连 fish 上游的 pyproject 都没声明,所以这张表不能只从 pyproject 生成。
    """
    fish = tts_models._BY_ID["fish-speech"]

    for package in ("natsort", "descript-audiotools", "descript-audio-codec", "pytorch-lightning"):
        assert package in fish.pip_requirements, f"{package} 不在依赖表里"
