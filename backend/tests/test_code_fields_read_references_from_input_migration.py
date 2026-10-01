"""代码字段(「执行脚本」的 expression、「代码」节点的 code)不再插值:代码里已有的 `{{…}}` 挪进入参,代码改成读入参。"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.migrations import _migrate_code_fields_read_references_from_input
from app.domain.workflows.code_references import JS_AS_TEXT, PY_AS_TEXT
from app.domain.workflows.code_references import references_become_input as _code_references_become_input
from app.db.models import Workflow
from tests.util import fresh_client


def _client_and_workspaces(count: int):
    client = fresh_client()
    return client, [client.post("/api/workspaces", json={"name": f"W{i}"}).json()["id"] for i in range(count)]


def _workflow(client, ws: str, graph: dict) -> str:
    return client.post("/api/workflows", json={"workspace_id": ws, "name": "流程", "graph": graph}).json()["id"]


def _graph_of(workflow_id: str) -> dict:
    with SessionLocal() as db:
        return db.get(Workflow, workflow_id).graph


def _config(graph: dict, node_id: str) -> dict:
    for node in graph["nodes"]:
        if node["id"] == node_id:
            return node["config"]
        for value in node["config"].values():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                try:
                    return _config(value, node_id)
                except KeyError:
                    pass
    raise KeyError(node_id)


def test_执行脚本里的引用挪进入参_脚本读入参() -> None:
    client, (ws,) = _client_and_workspaces(1)
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "llm-1", "type": "template", "config": {"template": "#app"}},
            {"id": "n", "type": "template", "config": {"template": "x"}},
            {"id": "js", "type": "browser_evaluate", "config": {
                "session": "s",
                "expression": 'document.querySelector("{{llm-1.text}}").value + {{n.count}}',
                "input": {"keep": "1"},
            }},
            {"id": "py", "type": "code", "config": {"code": 'output = "hi {{n.name}}" + str({{n.count}})'}},
            {"id": "plain", "type": "code", "config": {"code": "output = 1"}},
            #: 根指不到东西的 `{{…}}` 是字面量(比如在拼一段 Mustache 模板),不改。
            {"id": "mustache", "type": "code", "config": {"code": 'output = "{{name}} / {{n.name}}"'}},
        ],
        "edges": [],
    }
    workflow_id = _workflow(client, ws, graph)

    _migrate_code_fields_read_references_from_input()

    after = _graph_of(workflow_id)
    js = _config(after, "js")
    assert js["expression"] == f'document.querySelector("" + {JS_AS_TEXT}(input.llm_1_text) + "").value + input.n_count'
    assert js["input"] == {"keep": "1", "llm_1_text": "{{llm-1.text}}", "n_count": "{{n.count}}"}
    py = _config(after, "py")
    assert py["code"] == f'output = "hi " + {PY_AS_TEXT}(inputs["n_name"]) + "" + str(inputs["n_count"])'
    assert py["input"] == {"n_name": "{{n.name}}", "n_count": "{{n.count}}"}
    assert _config(after, "plain") == {"code": "output = 1"}
    mustache = _config(after, "mustache")
    assert mustache["code"] == f'output = "{{{{name}}}} / " + {PY_AS_TEXT}(inputs["n_name"]) + ""'
    assert mustache["input"] == {"n_name": "{{n.name}}"}


def test_入参里已有同名的键_加序号_同一个引用只占一个键() -> None:
    keys: dict[str, str] = {"n_x": "别的值"}

    def key_of(path: str) -> str:
        reference = "{{" + path + "}}"
        for key, value in keys.items():
            if value == reference:
                return key
        key, n = path.replace(".", "_"), 2
        while key in keys:
            key, n = f"{path.replace('.', '_')}_{n}", n + 1
        keys[key] = reference
        return key

    code = _code_references_become_input("{{n.x}} + {{n.x}} // {{n.x}}", "js", key_of)
    assert code == "input.n_x_2 + input.n_x_2 // input.n_x_2"
    assert keys == {"n_x": "别的值", "n_x_2": "{{n.x}}"}


def test_JS模板字符串和转义引号_按上下文改() -> None:
    same = lambda path: path.replace(".", "_")  # noqa: E731
    assert _code_references_become_input("`a ${x} {{n.t}}`", "js", same) == "`a ${x} ${" + JS_AS_TEXT + "(input.n_t)}`"
    assert _code_references_become_input("'it\\'s {{n.t}}'", "js", same) == f"'it\\'s ' + {JS_AS_TEXT}(input.n_t) + ''"
    #: 模板字符串 `${…}` 里是代码:按代码处改。
    assert _code_references_become_input("`a ${ {{n.t}} * 2 }`", "js", same) == "`a ${ input.n_t * 2 }`"


def test_Python的f字符串断开后接回同样的前缀() -> None:
    same = lambda path: path.replace(".", "_")  # noqa: E731
    assert (
        _code_references_become_input('f"{a} {{n.t}}!"', "python", same)
        == f'f"{{a}} " + {PY_AS_TEXT}(inputs["n_t"]) + f"!"'
    )
