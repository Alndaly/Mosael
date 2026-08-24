"""`app/core` 是最底层:**谁都可以 import 它,它不 import 任何人**。

此前它反向依赖着上层:

    app/core/db.py:964  from app.ai.runtime import asr_models
    app/core/db.py:965  from app.ai.runtime import config as tts_config

而且是**写在函数体里**的 import —— 那不是技巧,是"层分错了"的自白:写在文件顶上会立刻成环
(core.db → domain.tts_config → core.config → …),挪进函数里只是把环推迟到运行时。

根因是 `core/db.py` 同时是两个东西:**引擎与会话**(最底层,二十几处 import 它)和
**迁移编排器**(最顶层,它要认识每一个领域)。两个方向相反的职责挤在一个模块里,就只能靠
函数内 import 硬撑。拆开之后,迁移住到 `app/db/migrations.py` —— 它在依赖序的顶端,
爱 import 谁 import 谁。
"""

from __future__ import annotations

import ast
import pathlib

#: 「这个包不许认识哪些包」。**只声明真正成立的**:
#:
#: - `core` 是底座,被二十几处 import,不许认识任何上层(db 除外 —— models/迁移建立在 Base
#:   之上,方向是对的);
#: - `media` 是 ffmpeg 适配器,只该会干活,不许认识业务(domain / api)。
#:
#: **`ai` 与 `audio` 故意不在这里。** 它们在这套代码库里并不是纯适配器 —— 智能体宿主、声音
#: 克隆里都有实打实的业务判断,现在各有二十多处 import domain。给它们声明一条立刻需要几十条
#: 豁免的规则,等于写一条没人当真的规则;要不要拆是另一个决定,得先做那个决定。
PURE_PACKAGES: dict[str, set[str]] = {
    "core": {"domain", "audio", "media", "ai", "api", "integrations", "workers"},
    "media": {"domain", "api"},
}


def _upward_imports(package: str = "core") -> list[str]:
    UPPER_LAYERS = PURE_PACKAGES[package]
    offenders: list[str] = []
    for path in sorted(pathlib.Path(f"app/{package}").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[:1] == ["app"] and len(parts) > 1 and parts[1] in UPPER_LAYERS:
                    offenders.append(f"{path}:{node.lineno} → {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[:1] == ["app"] and len(parts) > 1 and parts[1] in UPPER_LAYERS:
                        offenders.append(f"{path}:{node.lineno} → {alias.name}")
    return offenders


def test_core_imports_nothing_from_above() -> None:
    offenders = _upward_imports("core")

    assert offenders == [], (
        "最底层反过来依赖上层了。写在函数里也算 —— 那只是把环推迟到运行时:\n  "
        + "\n  ".join(offenders)
    )


def test_core_does_not_authorise_over_business_tables() -> None:
    """鉴权不该住在底座里。

    `core/permissions.py` 曾经对 WorkspaceMember / Asset / Sequence 做鉴权 —— 一个被二十几处
    import 的底座,却认识业务表;同一个文件里还挤着 FastAPI 的认证插头。现在拆成两半:
    授权规则在 `domain/permissions`(要能被飞书回调这类非 HTTP 入口调用),HTTP 插头在
    `api/deps/auth`。

    这里盯的是**别搬回去**:core 里不许再出现对这几张业务表的引用。`core/security` 仍然会
    引 AuthSession —— 那是登录会话本身,属于认证基础设施,不是业务。
    """
    business = {"WorkspaceMember", "Asset", "Sequence", "Project", "Job"}
    offenders: list[str] = []
    for path in sorted(pathlib.Path("app/core").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.db.models":
                for alias in node.names:
                    if alias.name in business:
                        offenders.append(f"{path}:{node.lineno} → {alias.name}")

    assert offenders == [], (
        "底座又开始认识业务表了 —— 鉴权/业务判断该住在 domain:\n  " + "\n  ".join(offenders)
    )


def test_media_is_an_adapter_not_a_domain() -> None:
    """`media` 只会转码/取帧/算路径。**它不该知道"任务"这回事。**

    此前 `media/proxy.py` 自己建任务、发任务事件、改素材状态(`from app.domain.jobs import
    create_job, emit_job_event, run_job_guarded`)。方向反了的直接代价是这个包用不了:想在
    一个离线脚本里只调一次 `build_proxy`,会把整个任务系统和 DB 会话一起拖进来。

    业务侧现在住在 `domain/assets/proxies.py`,转码留在这边。
    """
    offenders = _upward_imports("media")

    assert offenders == [], (
        "media 是适配器,不该认识业务(谁该转码、算不算一次任务、素材状态怎么改):\n  "
        + "\n  ".join(offenders)
    )


def test_core_db_is_only_engine_and_session() -> None:
    """`core/db.py` 只负责引擎/会话/Base。迁移逻辑一旦回流,上一条迟早跟着红。"""
    source = pathlib.Path("app/core/db.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    migrations = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (node.name.startswith("_migrate") or node.name.startswith("_backfill") or node.name.startswith("_drop"))
    ]

    assert migrations == [], (
        "迁移函数又长回 core/db.py 了 —— 它们要认识领域层,而这个模块是被所有人 import 的底座:\n  "
        + "\n  ".join(migrations)
    )
