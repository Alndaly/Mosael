"""一个引擎"是什么样"的声明,只在一张表里。

今天所有 bug 的共同根是**同一件事被两处各自回答**。而克隆这条路上,"引擎的属性"曾经散在
五个地方:

    TtsEngine 数据类          pip 依赖、ModelScope 仓库、权重体积…
    ENGINE_IMPORTS            合成要 import 什么          ← 另一个字典
    voices.ENGINES_NEEDING_REFERENCE_TEXT   要不要参考文本  ← 另一个模块里的集合
    tts_worker.F5_*/FISH_*    附加模型、仓库路径           ← worker 里的常量

散着的代价是具体的:加 ModelScope 源时漏了 F5 的 modelscope 客户端(声明在 A,依赖在 B);
探测写成顶层包名而合成 import 子模块(声明在 A,真实路径在 C)。**每一次"漏了一处"都是
因为那一处不在你正在看的地方。**

这条测试盯两件事:声明都在表上;新加引擎时**每一项都得填**(不能靠默认值悄悄跳过)。
"""

from __future__ import annotations

import ast
import pathlib

from app.ai.runtime import tts_models


def test_every_engine_declares_every_capability() -> None:
    """默认值会让"忘了填"看起来像"不需要" —— 每个引擎都得明确回答每一项。"""
    for engine in tts_models.CATALOG:
        assert engine.imports, f"{engine.id} 没声明合成要 import 什么"
        assert engine.pip_requirements, f"{engine.id} 没声明运行依赖"
        assert engine.cache_dirs, f"{engine.id} 没声明缓存目录"
        assert engine.expected_bytes > 0, f"{engine.id} 没声明权重体积"
        assert isinstance(engine.needs_reference_text, bool), f"{engine.id} 没声明要不要参考文本"


def test_the_imports_are_submodules_not_top_level_packages() -> None:
    """`import fish_speech` 命中的是一个空的 __init__,永远成功 —— 探测因此比真实路径浅。"""
    for engine in tts_models.CATALOG:
        assert all("." in module for module in engine.imports), engine


def test_the_reference_text_rule_comes_from_the_table() -> None:
    """voices 那边不再自己维护一份名单。"""
    from app.domain.voices import voices

    assert voices.engines_needing_reference_text() == {
        engine.id for engine in tts_models.CATALOG if engine.needs_reference_text
    }
    assert not hasattr(voices, "ENGINES_NEEDING_REFERENCE_TEXT"), "旧的那份名单还在"


def test_no_engine_id_is_hardcoded_outside_the_catalog() -> None:
    """引擎 id 的字面量只该出现在两个地方:声明它的表,和按引擎分派的 worker。

    别处出现一个 `== "fish-speech"`,就是又长出了一处"关于这个引擎的知识"。
    """
    allowed = {"app/ai/runtime/tts_models.py", "app/ai/runtime/workers/tts.py"}
    engine_ids = {"fish-speech", "f5-tts"}
    offenders: list[str] = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        if path.as_posix() in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # 盯的是**判断**,不是默认值:`engine: str = "f5-tts"` 只是"默认用哪个",
            # 而 `if engine == "fish-speech"` 是"关于这个引擎的知识"—— 后者才会漂移。
            if not isinstance(node, ast.Compare):
                continue
            parts = [node.left, *node.comparators]
            for part in parts:
                literals = [part] if isinstance(part, ast.Constant) else list(getattr(part, "elts", []))
                if any(isinstance(x, ast.Constant) and x.value in engine_ids for x in literals):
                    offenders.append(f"{path}:{node.lineno}")
    assert not offenders, "引擎 id 散到了目录之外:\n  " + "\n  ".join(offenders)
