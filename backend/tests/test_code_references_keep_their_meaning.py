"""代码字段里的引用改成读入参之后,代码**算出来的东西和插值时代一样**。

## 现场

1.8.1 的迁移把字符串里的引用改成 `str(inputs["k"])` / `String(input.k)`,而插值把值写成文字走的是
`as_text`(对象 / 列表 / 布尔写成 JSON、None 写成空串)。实测:

- `json.loads('{{llm.obj}}')` 迁移后拿到 Python 的 repr,当场崩;
- `'{{c.result}}' == 'true'` 迁移后永远是假(`str(True)` 是 `True`);
- JS 模板字符串 `${ {{a.n}} * 2 }` 迁移后是 `${ ${input.a_n} * 2 }`,语法错误。

这里把**同一段老代码**两条路各跑一遍:插值时代(graph_rules.interpolate 把值拼进代码),和改写后(值从入参进)。
Python 用沙箱里那段包装(`sandbox._WRAPPER`)在本机起一个解释器跑 —— 本机没有 docker 沙箱,但包装和入参的
JSON 往返是同一份;JS 用 electron 的 `scriptWithInput` 同一种包法交给 node。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from app.domain.sandbox import _WRAPPER
from app.domain.workflows import interpolate
from app.domain.workflows.code_references import references_become_input, string_reads_keep_their_text

CONTEXT = {
    "llm": {"obj": {"a": [1, None], "名": "值"}, "text": 'say "hi"\n'},
    "c": {"result": True},
    "a": {"n": 3, "none": None},
}


def _key(path: str) -> str:
    return path.replace(".", "_")


def _inputs(code: str) -> dict:
    """改写后入参里的值:引用按插值规矩取(整串引用保留原类型)。"""
    from app.domain.workflows.code_references import REFERENCE

    return {_key(match.group(1)): interpolate("{{" + match.group(1) + "}}", CONTEXT) for match in REFERENCE.finditer(code)}


def _run_python(code: str, inputs: dict) -> object:
    done = subprocess.run(
        [sys.executable, "-c", _WRAPPER], input=json.dumps({"code": code, "inputs": inputs}).encode(),
        capture_output=True, check=False,
    )
    assert done.returncode == 0, done.stderr.decode()
    return json.loads(done.stdout.decode())["output"]


def _run_js(expression: str, inputs: dict | None) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("这台机器上没有 node")
    # 和 electron/publish/browserActions.ts 的 scriptWithInput 同一种包法:一个块,块里先声明 input。
    script = expression if inputs is None else "{ const input = " + json.dumps(inputs) + ";\n" + expression + "\n}"
    done = subprocess.run(
        [node, "-e", f"process.stdout.write(JSON.stringify(eval({json.dumps(script)})))"],
        capture_output=True, check=False,
    )
    assert done.returncode == 0, done.stderr.decode()
    return json.loads(done.stdout.decode())


PYTHON_CASES = [
    "import json\noutput = json.loads('{{llm.obj}}')",
    "output = '{{c.result}}' == 'true'",
    "output = 'n=' + '{{a.n}}' + ', none=[{{a.none}}]'",
    'output = f"{1 + 1}:{{a.n}}"',
    "output = {{a.n}} * 2  # {{a.n}} 在注释里",
]


@pytest.mark.parametrize("code", PYTHON_CASES)
def test_Python_改写后和插值时代算出同一个值(code: str) -> None:
    before = _run_python(interpolate(code, CONTEXT), {})
    after = _run_python(references_become_input(code, "python", _key), _inputs(code))
    assert after == before


JS_CASES = [
    "JSON.parse('{{llm.obj}}')",
    "'{{c.result}}' === 'true'",
    "`n=${ {{a.n}} * 2 } none=[{{a.none}}] ok={{c.result}}`",
    "'[{{a.none}}]' + {{a.n}}",
]


@pytest.mark.parametrize("code", JS_CASES)
def test_JS_改写后和插值时代算出同一个值(code: str) -> None:
    before = _run_js(interpolate(code, CONTEXT), None)
    after = _run_js(references_become_input(code, "js", _key), _inputs(code))
    assert after == before


#: 1.8.1 那版改写的产出(手写成那一版的样子)→ 修正之后,和插值时代一样。
LEGACY = [
    ("python", "import json\noutput = json.loads('' + str(inputs[\"llm_obj\"]) + '')", "import json\noutput = json.loads('{{llm.obj}}')"),
    ("python", "output = '' + str(inputs[\"c_result\"]) + '' == 'true'", "output = '{{c.result}}' == 'true'"),
    ("js", "`n=${ ${input.a_n} * 2 } none=[${input.a_none}]`", "`n=${ {{a.n}} * 2 } none=[{{a.none}}]`"),
    ("js", "JSON.parse('' + String(input.llm_obj) + '')", "JSON.parse('{{llm.obj}}')"),
]


@pytest.mark.parametrize(("language", "migrated", "original"), LEGACY)
def test_1_8_1_改写过的读法修正之后_和插值时代一样_重跑不动(language: str, migrated: str, original: str) -> None:
    keys = set(_inputs(original))
    fixed = string_reads_keep_their_text(migrated, language, keys)
    assert string_reads_keep_their_text(fixed, language, keys) == fixed
    if language == "python":
        assert _run_python(fixed, _inputs(original)) == _run_python(interpolate(original, CONTEXT), {})
    else:
        assert _run_js(fixed, _inputs(original)) == _run_js(interpolate(original, CONTEXT), None)


def test_修正只认那次改写起的键_用户自己写的读法不动() -> None:
    code = "'' + String(input.mine) + ''"
    assert string_reads_keep_their_text(code, "js", {"other"}) == code


def test_修正迁移只改1_8_1改写过的工作流_落一版带作者的修订_重跑不动() -> None:
    from app.core.db import SessionLocal
    from app.db.migrations import _CODE_FIELDS_NOTE, _migrate_code_string_reads_keep_their_text
    from app.db.models import User, Workflow, WorkflowRevision
    from app.domain.workflows.revisions import commit_graph_revision, current_workflow_revision
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    migrated = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "py", "type": "code", "config": {
                "code": "output = '' + str(inputs[\"c_result\"]) + '' == 'true'",
                "input": {"c_result": "{{start.flag}}"},
            }},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "py"}],
    }
    ids = [client.post("/api/workflows", json={"workspace_id": ws, "name": name}).json()["id"] for name in ("迁过的", "自己写的")]
    with SessionLocal() as db:
        author = db.query(User).filter(User.username == "tester").one().id
        for workflow_id, note in zip(ids, (_CODE_FIELDS_NOTE, "自己改的"), strict=True):
            commit_graph_revision(db, db.get(Workflow, workflow_id), lambda _graph: migrated,
                                  source="migration" if note == _CODE_FIELDS_NOTE else "edit", created_by=author, note=note)
        db.commit()

    _migrate_code_string_reads_keep_their_text()
    _migrate_code_string_reads_keep_their_text()

    with SessionLocal() as db:
        fixed = current_workflow_revision(db, db.get(Workflow, ids[0]))
        code = fixed.graph["nodes"][1]["config"]["code"]
        assert "str(inputs" not in code and '__import__("json")' in code
        assert fixed.created_by == author and fixed.revision == 3
        assert db.query(WorkflowRevision).filter_by(workflow_id=ids[0]).count() == 3
        untouched = db.get(Workflow, ids[1])
        assert untouched.graph["nodes"][1]["config"]["code"] == migrated["nodes"][1]["config"]["code"]
    assert _run_python(code, {"c_result": True}) is True
