"""结构性约束:**技能清单里报出去的每条路径,都得真的存在。**

`CORE_SKILLS` 不是文档,它经 `/api/agent/manifest` 发给智能体和外部 MCP 客户端 —— 那份清单
就是对方唯一知道「这个应用有哪些工具、打哪个地址」的来源。所以一条写错的路径不是笔误,
是**一件功能对智能体不存在**:它照着清单发请求,拿回 404,而应用这边什么都没发生。

发现时有两条是空的:

  · `GET /api/generation/models` —— 真实地址是 `/api/generation/options`。这条尤其要命:
    它是**发现通道**。智能体拿不到模型清单,也就拿不到每个模型的 capabilities,于是只能
    猜供应商、猜模型名、猜参数 —— 而参数猜错会被 validate_against_capabilities 拦下。
    「智能体能不能完整调用生成能力」这个问题,答案卡在这一条上。
  · `POST /api/plugins/{plugin_id}/tools/{tool_name}/invoke` —— 真实地址挂在 instances 下,
    是 `/api/plugins/instances/{instance_id}/tools/{tool_name}/invoke`。

两条都不会有人发现:清单是静态数据,路由改名不会牵动它,而这个应用自己从不按这份清单发请求
(界面直接调各自的接口),只有外面的智能体会。

判据取自 **OpenAPI schema**,不是 `app.routes` —— 后者在导入期只有 39 条(路由挂在
`create_app()` 里,还有 Mount 子应用),照它判会把 16 条全判成不存在。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import re


def _real_paths() -> dict[str, set[str]]:
    from app.main import app

    spec = app.openapi()
    return {path: {method.upper() for method in ops} for path, ops in spec["paths"].items()}


def _exists(real: dict[str, set[str]], path: str, method: str) -> bool:
    if method in real.get(path, ()):
        return True
    # 带路径参数的:`{任意名}` 当通配。声明里的占位符名字和路由里的可以不同
    # (`{plugin_id}` vs `{instance_id}`),但**层级和位置必须一致** —— 那才是地址。
    for declared, methods in real.items():
        if method in methods and re.fullmatch(re.sub(r"\{[^}]+\}", r"\\{[^}]+\\}|[^/]+", declared), path):
            return True
    return False


def test_核心技能声明的路径都存在() -> None:
    from app.domain.agent.skills import CORE_SKILLS

    real = _real_paths()
    missing = [
        f"{skill['id']}.{tool['name']}: {tool['method']} {tool['path']}"
        for skill in CORE_SKILLS
        for tool in skill["tools"]
        if not _exists(real, tool["path"], tool["method"])
    ]
    assert not missing, (
        "这些工具报给智能体的地址是空的 —— 它照着发请求只会拿到 404:\n"
        + "\n".join(f"  {one}" for one in missing)
    )


def test_判据本身是活的() -> None:
    """上面那条要是把「不存在」也判成存在,它就永远绿。这里钉住判据的两端。"""
    real = _real_paths()
    assert _exists(real, "/api/generation/options", "GET"), "真实存在的路径被判成不存在"
    assert not _exists(real, "/api/generation/models", "GET"), "不存在的路径被判成存在"
    assert not _exists(real, "/api/generation/options", "DELETE"), "方法不匹配没被发现"
