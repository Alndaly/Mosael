"""社区详情页标「含运行代码节点」按的是格式包里的 `CODE_NODE_TYPES`;它得和这里的节点注册表对得上。

格式包(packages/mosael-formats)不认识桌面端的节点注册表 —— 它要装进社区服务,而注册表随版本变、
还连着一整个执行引擎。所以「哪些节点会执行一段调用方写的代码」在那边是一张写明的表,两边一致由这条测试
守着:注册表里凡是带 `type: "code"` 配置项的节点(一段要被执行的代码),都必须在那张表里,反过来也一样。
漏一个,社区上一份带脚本的工作流就不会被标出来。
"""

from __future__ import annotations

from mosael_formats.workflow_file import CODE_NODE_TYPES

from app.domain.workflows import NODE_TYPES


def test_运行代码的节点两边是同一批() -> None:
    runs_code = {
        name
        for name, spec in NODE_TYPES.items()
        if any(isinstance(field, dict) and field.get("type") == "code" for field in (spec.get("config") or {}).values())
    }
    assert runs_code == set(CODE_NODE_TYPES)
