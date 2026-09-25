"""沿着八条官方工作流的链路走一遍 —— 它们是绝大多数用户第一次看到的东西。

这一份不测某一个节点做得对不对(那是各自的测试),它问的是**整条链上有没有卡点**:

1. 图本身合法、每一个 `{{引用}}` 都解析得到(包括循环体里的 `{{loop.item}}` / `{{input.x}}`);
2. 在一个**什么都没配**的新工作区里按下运行,用户看到的是**一句能照着做的话**,
   而不是一个跑到一半死掉的任务。

第 2 条抓到过一个真的卡点:**必填检查不下到循环体里**。于是「从主题到完整视频」在没配图像
模型时**能启动** —— 它占一个任务位、把循环之前的步骤全跑完(创意主旨、脚本、视觉圣经、
分镜、搭白模,好几次付费的 AI 调用),然后才死在循环上;而同一处遗漏写在顶层是当场 422、
免费、而且指得准。已修(`validate_graph` 在运行前把内嵌子图连同外层一起整份校验)。
"""

from __future__ import annotations

import json
import re
import time

import pytest

from app.core.db import SessionLocal
from app.db.models import User
from app.domain.workflows import NODE_TYPES, validate_graph
from app.domain.workflows.templates import TEMPLATE_CATALOG, built_in_template_graph
from tests.util import fresh_client

REFERENCE = re.compile(r"\{\{\s*([\w.\-]+?)\s*\}\}")
TEMPLATE_IDS = [str(one["id"]) for one in TEMPLATE_CATALOG]


def _graph(template_id: str) -> dict:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        user = db.query(User).first()
        assert user is not None
        return built_in_template_graph(db, template_id, user_id=user.id, workspace_id=workspace, locale="zh")


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _walk(graph: dict, scope: set[str], where: str, found: list[str]) -> None:
    nodes = {str(one["id"]): one for one in graph.get("nodes", [])}
    here = scope | set(nodes)
    params = set((nodes.get("start", {}).get("config", {}) or {}).get("params", {}) or {})

    for node_id, node in nodes.items():
        config = node.get("config") or {}
        body = config.get("body")
        body_ids = {str(one["id"]) for one in body["nodes"]} if isinstance(body, dict) and body.get("nodes") else set()
        for key, value in config.items():
            if key == "body" and body_ids:
                # 循环体自带 loop / input 两个作用域(见 executors/loops.iterate)
                _walk(value, here | {"loop", "input"}, f"{where}/{node_id}", found)
                continue
            # 循环节点的 `output` 在**体的上下文**里求值,所以它看得见体内的节点。
            visible = (here | body_ids | {"loop", "input"}) if key == "output" and body_ids else here
            for reference in REFERENCE.findall(_text(value)):
                head, _, rest = reference.partition(".")
                tail = rest.split(".")[0] if rest else ""
                if head not in visible:
                    found.append(f"{where}/{node_id}.{key} → {{{{{reference}}}}}:作用域里没有 {head}")
                elif head == "start":
                    if tail and params and tail not in params:
                        found.append(f"{where}/{node_id}.{key} → {{{{{reference}}}}}:start 没有参数 {tail}")
                elif head in nodes and tail:
                    outputs = set((NODE_TYPES.get(nodes[head]["type"]) or {}).get("outputs") or {})
                    if outputs and tail not in outputs:
                        found.append(
                            f"{where}/{node_id}.{key} → {{{{{reference}}}}}:"
                            f"{head}({nodes[head]['type']}) 的输出只有 {sorted(outputs)}"
                        )


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_每条官方工作流的图和引用都站得住(template_id: str) -> None:
    graph = _graph(template_id)
    found = [f"校验:{one}" for one in validate_graph(graph, require_config=False)]
    _walk(graph, {"start"}, template_id, found)
    assert not found, f"{template_id} 这条链上有断点:\n  " + "\n  ".join(found)


def test_模板清单没有缩水() -> None:
    """扫描面自己也要有人看着:清单空了的话上面那条参数化测试一条都不会跑。"""
    assert len(TEMPLATE_IDS) >= 8, f"官方工作流只剩 {TEMPLATE_IDS}"


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_什么都没配时_按下运行给的是一句话而不是一个死掉的任务(template_id: str) -> None:
    """新工作区、没有供应商连接、没有素材 —— 这是每个人第一次点开它的样子。

    要么 **422 + 一句指得准的话**,要么任务真的跑起来。**不能**是"接了任务、跑一半、死在里面"
    —— 那会花掉钱和时间,而用户最后拿到的还是同一句"你少配了个东西"。
    """
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    made = client.post(
        "/api/workflows",
        json={"workspace_id": workspace, "name": template_id, "template_id": template_id},
    )
    assert made.status_code == 200, made.text

    run = client.post(f"/api/workflows/{made.json()['id']}/run", json={"params": {}})
    assert run.status_code in (200, 422), run.text
    if run.status_code == 422:
        detail = run.json()["detail"]
        assert "缺少必填配置" in detail, f"{template_id} 拒了,但没说清缺什么:{detail}"
        # 指得准:要么点名顶层节点,要么点名"某个节点的子图里"的那个节点。
        assert re.search(r"节点 \w+", detail), detail
        return

    # 接了任务,那它就**不许**再死在"少配了个东西"上 —— 那种错该在上面那一步就拦住,
    # 免费、而且指得准。死在别的原因上(没有供应商连接、素材没有音轨)是另一回事。
    job_id = run.json()["id"]
    for _ in range(80):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.15)
    if job["status"] == "failed":
        reason = str(job.get("error") or "")
        assert "缺少必填配置" not in reason, (
            f"{template_id} 接了任务却死在缺必填配置上(进度 {job.get('progress')}):{reason}\n"
            "  这一类该在启动前就拦住 —— 跑到这里意味着前面那些步骤(可能包括付费的 AI 调用)"
            "已经白花了。"
        )


def test_必填检查下得到循环体里() -> None:
    """**这是那个卡点本身。**

    循环体里缺一个必填项时,顶层校验此前返回 `[]` —— 于是工作流能启动、占一个任务位、把循环
    之前的步骤全跑完,然后才死在循环上(体校验只有循环真跑到时才被调)。而同一处遗漏写在顶层
    是当场 422。

    这条测试**只看 `validate_graph` 一个函数**,不走端到端:端到端那条在这台机器上会先死在
    "没有可用的 AI 供应商连接"上,看不见这个差别 —— 而差别就在这儿。
    """
    graph = _graph("highlight_shorts")
    loop = next(one for one in graph["nodes"] if one["id"] == "cut_clips")
    inner = next(one for one in loop["config"]["body"]["nodes"] if one["type"] == "export_sequence")
    # 这一项平时由体内的数据边喂;把边和值一起拿掉,就是"体内缺一个必填项"。
    loop["config"]["body"]["edges"] = [
        edge for edge in loop["config"]["body"]["edges"]
        if not (edge.get("target") == inner["id"] and edge.get("target_input") == "sequence_id")
    ]
    inner["inputs"] = [one for one in (inner.get("inputs") or []) if one != "sequence_id"]
    inner["config"]["sequence_id"] = ""

    errors = validate_graph(graph, require_config=True)
    assert any("sequence_id" in one and inner["id"] in one for one in errors), (
        "顶层校验没看见循环体里缺的必填项 —— 这条工作流会启动、跑掉前半段、再死在循环上:\n  "
        + "\n  ".join(errors or ["(什么都没报)"])
    )
    assert any(loop["id"] in one for one in errors), f"报错没说清它住在哪个循环里:{errors}"


#: 边上有人读的键。多出来的键没有任何代码读它 —— 模板作者以为自己写了一个设定,其实什么都没写。
EDGE_KEYS = {"id", "source", "target", "kind", "source_handle", "source_output", "target_input", "label"}


def _edges(graph: dict, where: str):
    for edge in graph.get("edges") or []:
        yield where, edge
    for node in graph.get("nodes") or []:
        for key, value in (node.get("config") or {}).items():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                yield from _edges(value, f"{where}/{node['id']}.{key}")


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_模板的边只用引擎认得的键(template_id: str) -> None:
    """全片生成模板里五条条件边写的是 `"branch": "true"` —— 没有任何代码读 `branch`。它们能按
    「真」那一支跑,只是因为没写 handle 的条件边缺省就是真;画布上也就没有真 / 假的标记。
    分支走哪一支,只有 `source_handle` 一种写法。"""
    stray = [
        f"{where}: {edge.get('id')} 多了 {sorted(set(edge) - EDGE_KEYS)}"
        for where, edge in _edges(_graph(template_id), template_id)
        if set(edge) - EDGE_KEYS
    ]
    assert not stray, "\n".join(stray)
