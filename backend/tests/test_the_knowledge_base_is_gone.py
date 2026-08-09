"""知识库整块删掉了。

它一直只有关键词那一层在跑:向量层因为一个被降级吃掉的 NameError 从来没建过索引(见提交
4ddd9fc),而修好之后又撞上分层错位 —— 部署级的嵌入配置指着一条归某个人的连接,除连接主人外
所有人的向量层都静默失效。要修得选一条路(本地免密钥模型 / 把连接共享进工作区 / 只留 FTS),
而这个功能本身的价值撑不起那次选择:四篇文档、三个库,用的人只在用关键词搜。

**删就删干净**:表、路由、领域模块、智能体工具、工作流节点、界面入口、依赖,连同它带来的两个
可选外部依赖(milvus-lite 向量库、neo4j 图谱层)。留一半的功能比没有更坏 —— 它会让下一个人
以为这里还有东西,并且照着它建新的耦合。

跨会话记忆(domain/agent/memory)**不受影响**:它和知识库从来是两件事 —— 记忆是不检索也生效的
约定,知识库是要检索才读得到的资料。
"""

from __future__ import annotations

import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def test_the_tables_are_gone() -> None:
    from app.db.models import Base

    leftovers = [name for name in Base.metadata.tables if name.startswith("kb_")]

    assert not leftovers, f"还留着表:{leftovers}"


def test_the_domain_package_is_gone() -> None:
    assert not (BACKEND / "app/domain/kb").exists()
    assert not (BACKEND / "app/api/routes/kb.py").exists()


def test_the_routes_are_gone() -> None:
    from app.main import app

    kb_routes = [r.path for r in app.routes if "/kb" in getattr(r, "path", "")]

    assert not kb_routes, f"还挂着路由:{kb_routes}"


def test_the_agent_tools_are_gone() -> None:
    """智能体的工具表里不该再有它 —— 留着的话模型会去调一个 404。"""
    import mcp_server

    for name in ("search_kb", "read_kb_document", "create_kb_note"):
        assert not hasattr(mcp_server, name), f"{name} 还在"


def test_the_workflow_node_is_gone() -> None:
    from app.domain.workflows import NODE_TYPES

    assert "kb_search" not in NODE_TYPES


def test_nothing_still_imports_it() -> None:
    """形状棘轮:import 一个不存在的模块只会在**跑到那一行**时才炸,而那可能是几周之后。"""
    import re

    offenders = []
    for path in (BACKEND / "app").rglob("*.py"):
        for index, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"^\s*(from|import)\s.*\bkb\b", line) and "kb_" not in line.split("#")[0]:
                offenders.append(f"{path.relative_to(BACKEND)}:{index} {line.strip()}")
            elif re.search(r"\bKb[A-Z]\w+", line.split("#")[0]):
                offenders.append(f"{path.relative_to(BACKEND)}:{index} {line.strip()}")

    assert not offenders, "还有人引用它:\n  " + "\n  ".join(offenders)


def test_the_optional_dependencies_went_with_it() -> None:
    """向量库和图谱库是它一个人的依赖 —— 功能没了,依赖不该还在打包里。"""
    text = (BACKEND / "pyproject.toml").read_text()

    for dependency in ("pymilvus", "neo4j", "markitdown"):
        assert dependency not in text, f"{dependency} 还在依赖里"


def test_agent_memory_survives() -> None:
    """记忆和知识库是两件事,别一起删掉。"""
    from app.domain.agent import memory

    assert hasattr(memory, "memory_prompt")
