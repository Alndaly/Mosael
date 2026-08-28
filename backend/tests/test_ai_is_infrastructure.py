"""结构性约束:**`ai/` 是基础设施,不许认识业务**。

它只回答两个问题 —— 「怎么跟这家外部服务说话」(providers / sidecar)和「怎么在这台机器上
把模型跑起来」(runtime)。这两件事都和「这个部署里谁配了什么、这次要给谁记账」无关。

反过来才对:`domain` 需要什么就去调 `ai`,而 `ai` 需要什么就**声明出来、等着被喂**
(ai/runtime/config.use_source、ai/sidecar/adapters.use_proxy_source),由组合层
(app/main.py 的启动装配)接上。

这条约束此前**不成立**:ai → domain 有 33 条边,domain → ai 有 17 条,两个包互相依赖。
那个环没被现有的无环测试拦住,因为它是按**模块**粒度判的,而环在**包**这一层。它的代价是
真实的:一个纯路径计算的模块(venv 在哪、解释器是哪个)被一张数据库表拴住,于是单跑一个
worker 子进程都得先有数据库。

拆的时候顺带发现:`ai/agent/host.py` 碰库 56 次 —— 那是领域逻辑放错了树,现已归到
`domain/agent/` 和它的兄弟们(autopilot / confirmations / memory / plan)作伴。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: `ai/` 不许 import 的包。db 也在里面 —— 基础设施不该认识表结构。
FORBIDDEN = ("app.domain", "app.db")


def _imports(path: pathlib.Path) -> list[tuple[int, str]]:
    """这个模块 import 了哪些 app.* —— **顶层和函数内一视同仁**。

    函数内延迟导入常被当成"绕开循环依赖的技巧",可它绕开的只是 import 时机,依赖本身还在:
    改动照样会传导过来,而下一个读代码的人还会以为这两个包是独立的。
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
    return found


def test_ai_不认识业务层() -> None:
    offenders = []
    for path in sorted((BACKEND / "app" / "ai").rglob("*.py")):
        for lineno, module in _imports(path):
            if module.startswith(FORBIDDEN):
                rel = path.relative_to(BACKEND)
                offenders.append(f"{rel}:{lineno}  {module}")

    assert offenders == [], (
        "ai/ 是基础设施,不该认识 domain / db —— 它需要什么就声明出来等着被喂"
        "(见 ai/runtime/config.use_source 的写法),由 app/main.py 的启动装配接上:\n  "
        + "\n  ".join(offenders)
    )


def test_注入点确实存在_而不是靠自觉() -> None:
    """把"不许 import"变成"有地方可以被喂"。只禁不给出路的话,下一个人只能违反它。"""
    from app.ai.runtime import config
    from app.ai.sidecar import adapters

    assert callable(config.use_source), "运行时没有配置注入点"
    assert callable(adapters.use_proxy_source), "sidecar 没有代理注入点"

    # 没装的时候也要能工作 —— 单跑一个 worker 子进程时没人会去装配。
    assert config._from_env().engine, "没装配置来源时拿不到可用的默认值"


def test_接缝在导入期就接上了_不是等到_lifespan() -> None:
    """光有注入点不够 —— **还得真的被接上,而且是在导入期接上**。

    这两条曾经装在 `lifespan` 里。于是任何不跑 lifespan 的入口(TestClient、脚本)拿到的是
    一个半装配的系统:`config.get()` 悄悄回落到环境变量那份默认值,用户存进库的引擎/下载源/
    fish 目录被顶掉。症状离原因很远 —— 设置页 PUT 成功、回读还是旧的 f5-tts,一句错都不报,
    而单跑 tests/test_voices.py::test_tts_config_get_and_update 就红、跟着整套跑却绿。

    「谁实现这道缝」是静态的组装事实,该在 `app.main` 被 import 的那一刻就成立。
    """
    import app.main  # noqa: F401  —— 组装根,import 它就等于装配完成

    from app.ai.runtime import config
    from app.ai.sidecar import adapters
    from app.domain.network import subprocess_env_for_child
    from app.domain.voices import tts_settings

    assert config._source is tts_settings.load, "TTS 配置来源没接上:读到的会是环境变量默认值,不是用户存的那份"
    assert adapters._proxy_source is subprocess_env_for_child, "sidecar 代理来源没接上:子进程会不带代理起来"
