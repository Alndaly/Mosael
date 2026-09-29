"""插件接进来的连接,vendor 怎么写。

一条纯命名约定,却被供应商连接(列出连接时标出它来自哪个插件包)和生成域(把插件模型接进选择器)
两边都要用。此前它住在 generation.plugin_connections 里,于是 providers.connections 为了一个字符串
前缀在顶层 import 了生成域 —— 而生成域本来就依赖供应商,两个包就此成环。命名约定放在更底下的这一侧。
"""

from __future__ import annotations

#: 插件连接的 vendor 前缀。vendor 绑**包**不绑实例:画板、工作流会被导出到别的机器,实例是本机事实
#: —— 和工作流节点类型 `plugin.<包id>.<工具>` 是同一个理由(ADR 0005)。
VENDOR_PREFIX = "plugin:"


def vendor_for(package_id: str) -> str:
    return f"{VENDOR_PREFIX}{package_id}"


def package_of(vendor: str) -> str:
    """`plugin:<包 id>` → 包 id;不是插件 vendor 回空串。"""
    return vendor[len(VENDOR_PREFIX):] if vendor.startswith(VENDOR_PREFIX) else ""
