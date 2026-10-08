"""一次生成失败,画板格子和 AI 工作台说的是**同一句人话**,原文在「查看原始错误」里(UC-06)。

此前同一个失败(占位 Key)两页两种说法:画板格子贴原文头三行 ——「DashScope 请求失败:Client error '401 Unauthorized'
for url 'https://dashscope.aliyuncs.com/api/v1/services/ai…」;AI 工作台在前端用正则抠,而 httpx 原文里
「For more information check:」前面是换行,按空格切切不掉,连不上时摘要拖着一截英文尾巴。哪一页都没说该去哪改。

现在那一句只在后端产出(domain/failure_summary):笼统的「请求失败」按状态码归到「密钥不对 / 余额不足 / 限流 /
参数不对 / 服务不可用」,上游原文只留服务商自己说的那句,去掉 httpx 的套话、地址和尾巴。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.db import SessionLocal
from app.db.models import Board, GenerationJob, Job
from app.domain.failure_summary import summarize

#: httpx 状态码异常的原话 —— 注意 For more information 前面是**换行**。
HTTPX_401 = (
    "Client error '401 Unauthorized' for url "
    "'https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis?X-Signature=SECRET'\n"
    "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401"
)
BODY = '; body: {"code":"InvalidApiKey","message":"Invalid API-key provided.","request_id":"r1"}'
HTTPX_502 = (
    "Server error '502 Bad Gateway' for url 'http://127.0.0.1:9/compatible-mode/v1/x'\n"
    "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/502"
)


@pytest.mark.parametrize("locale, words", [("zh", "不认这把密钥"), ("en", "rejected the credentials")])
def test_笼统的请求失败按状态码说清该去哪改(locale: str, words: str) -> None:
    said = summarize("raw", "providerErr_requestFailed", {"vendor": "DashScope", "detail": HTTPX_401 + BODY}, locale)
    assert words in said
    assert "Invalid API-key provided." in said, "服务商自己说的那句要留着"
    assert "://" not in said and "SECRET" not in said and "For more information" not in said


def test_换行前面的那截英文尾巴也去掉() -> None:
    said = summarize("raw", "providerErr_requestFailed", {"vendor": "DashScope", "detail": HTTPX_502}, "zh")
    assert "暂时不可用" in said
    assert "For more information" not in said and "127.0.0.1" not in said and "mozilla" not in said
    assert "HTTP 502" in said


def test_没有_key_的原话也只留一句() -> None:
    said = summarize("DashScope 请求失败:" + HTTPX_401, "", {}, "zh")
    assert said == "DashScope 请求失败:HTTP 401 Unauthorized"


def test_本来就是人话的不动() -> None:
    assert summarize("服务商已经生成好了", "", {}, "zh") == "服务商已经生成好了"
    said = summarize("", "genErr_noApiKey", {"provider": "bytedance"}, "zh")
    assert "bytedance" in said and "设置" in said


def _failed_generation(client, *, key: str, params: dict, error: str) -> str:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="failed", payload={}, error=error,
                  error_key=key, error_params=params)
        db.add(job)
        db.flush()
        db.add(GenerationJob(workspace_id=workspace, job_id=job.id, kind="image", provider="alibaba", model="wanx",
                             request={"prompt": "猫", "parameters": {}}, error=error, error_key=key, error_params=params))
        db.commit()
    return workspace


@pytest.mark.parametrize("locale, words", [("zh-CN", "不认这把密钥"), ("en-US", "rejected the credentials")])
def test_生成记录带着那一句_按读的人的语言翻_原文另给(locale: str, words: str) -> None:
    from tests.util import fresh_client

    client = fresh_client()
    params = {"vendor": "DashScope", "detail": HTTPX_401 + BODY}
    workspace = _failed_generation(client, key="providerErr_requestFailed", params=params, error="DashScope 请求失败:x")
    [record] = client.get("/api/generation/jobs", params={"workspace_id": workspace},
                          headers={"Accept-Language": locale}).json()
    assert words in record["error_summary"]
    assert "SECRET" not in record["error_summary"]
    assert "For more information" in record["error"], "原文照旧在 error 里,给「查看原始错误」"


def test_画板格子存那一句和原文(monkeypatch) -> None:
    from tests.util import fresh_client
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board_id = client.post("/api/boards", json={"workspace_id": workspace, "name": "B", "canvas": {
        "items": [{"id": "img", "kind": "image", "x": 0, "y": 0, "run": {"status": "running", "job_id": "job-1"}}],
        "edges": [],
    }}).json()["id"]
    raw = "DashScope 请求失败:" + HTTPX_401 + BODY
    job = SimpleNamespace(id="job-1", status="failed", result=None, error=raw, error_key="providerErr_requestFailed",
                          error_params={"vendor": "DashScope", "detail": HTTPX_401 + BODY}, created_by=None)
    with SessionLocal() as db:
        deliver_generated(db, job, receipt_to_item(board_id, "img"))
    canvas = client.get(f"/api/boards/{board_id}", params={"workspace_id": workspace}).json()["canvas"]
    run = canvas["items"][0]["run"]
    assert run["status"] == "failed"
    assert "不认这把密钥" in run["error"] and "://" not in run["error"]
    #: 原文是上游那句原话(谁失败了 —— 「DashScope 请求失败:」那截壳 —— 格子上的模型已经说了)
    assert run["error_detail"].startswith("Client error '401 Unauthorized'") and "InvalidApiKey" in run["error_detail"]


def test_老画板上的失败格子由迁移改成那一句加原文() -> None:
    from tests.util import fresh_client
    from app.db.migrations import _migrate_board_failures_keep_their_original_error

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    old = ("DashScope 请求失败:" + HTTPX_401)[:300]
    board_id = client.post("/api/boards", json={"workspace_id": workspace, "name": "B", "canvas": {
        "items": [
            {"id": "a", "kind": "image", "x": 0, "y": 0, "run": {"status": "failed", "error": old}},
            {"id": "b", "kind": "image", "x": 300, "y": 0, "run": {"status": "failed", "error": "没有产出"}},
        ],
        "edges": [],
    }}).json()["id"]
    with SessionLocal() as db:
        before = db.get(Board, board_id).revision

    _migrate_board_failures_keep_their_original_error()
    _migrate_board_failures_keep_their_original_error()  # 幂等:第二遍什么都不动

    with SessionLocal() as db:
        board = db.get(Board, board_id)
        canvas = board.canvas if isinstance(board.canvas, dict) else json.loads(board.canvas)
        assert board.revision == before + 1
    first, second = canvas["items"]
    assert first["run"] == {"status": "failed", "error": "DashScope 请求失败:HTTP 401 Unauthorized", "error_detail": old}
    assert second["run"] == {"status": "failed", "error": "没有产出"}, "本来就是一句人话的不动"


# --- 失败卡(维护者 2026-10-08:「生成失败」消息框太丑)----------------------------------------------------------------------

#: ComfyUI 执行出错时插件交回的失败的样子(见插件 run.failure),存进任务参数的样子(见 plugin_connections._stored_hint):
#: 一句人话、原话、认得出的原因和怎么修(句子按语言分着存,命令原样)。
UPGRADE = 'pip install -U "comfy-kitchen>=0.2.37" "comfyui-workflow-templates>=0.11.77"'
COMFY_FAILURE = {
    "name": "ComfyUI · http://192.168.3.15:8188",
    "detail": "ComfyUI 执行失败:KSampler: hostbuf_file_reader_read failed",
    "original": "KSampler: hostbuf_file_reader_read failed",
    "summary": {"__text": {"zh": "ComfyUI 执行到「KSampler」这一步出错", "en": "ComfyUI hit an error at the “KSampler” step"}},
    "hint": {
        "cause": {"__text": {"zh": "那台 ComfyUI 装的 comfy-kitchen 太旧", "en": "That ComfyUI install has an old comfy-kitchen"}},
        "steps": [
            {"text": {"__text": {"zh": "在那台机器上升级:", "en": "On that machine, upgrade:"}}, "command": UPGRADE},
            {"text": {"__text": {"zh": "重启 ComfyUI,再生成一次。", "en": "Restart ComfyUI and generate again."}}},
        ],
    },
    "remote": "failed",
}


def test_插件说了一句人话_失败卡写它_不重复连接名_原文和提示各给() -> None:
    from tests.util import fresh_client

    client = fresh_client()
    workspace = _failed_generation(client, key="providerErr_pluginFailed", params=COMFY_FAILURE,
                                   error="「ComfyUI · http://192.168.3.15:8188」生成失败:ComfyUI 执行失败:KSampler: hostbuf_file_reader_read failed")
    [record] = client.get("/api/generation/jobs", params={"workspace_id": workspace}).json()
    assert record["error_summary"] == "ComfyUI 执行到「KSampler」这一步出错"
    assert record["error_detail"] == "KSampler: hostbuf_file_reader_read failed"
    assert record["error_hint"] == {"cause": "那台 ComfyUI 装的 comfy-kitchen 太旧", "steps": [
        {"text": "在那台机器上升级:", "command": UPGRADE},
        {"text": "重启 ComfyUI,再生成一次。", "command": None},
    ]}, "原因一句、修法一步一句,命令单独一格(失败卡摆成等宽的一块、带复制)"
    assert record["retrievable"] is False and record["repeatable"] is True
    english = client.get("/api/generation/jobs", params={"workspace_id": workspace}, headers={"Accept-Language": "en-US"}).json()[0]
    assert english["error_hint"]["cause"] == "That ComfyUI install has an old comfy-kitchen"
    assert [step["text"] for step in english["error_hint"]["steps"]] == ["On that machine, upgrade:", "Restart ComfyUI and generate again."]
    assert english["error_hint"]["steps"][0]["command"] == UPGRADE, "命令原样,不翻"


def test_画板格子的详情里_原因和怎么修拼成一段_命令单独一行() -> None:
    from app.domain.failure_summary import hint_text

    assert hint_text(COMFY_FAILURE, "zh") == (
        "那台 ComfyUI 装的 comfy-kitchen 太旧\n1. 在那台机器上升级:\n" + UPGRADE + "\n2. 重启 ComfyUI,再生成一次。")
    only = {"hint": {"steps": [{"text": {"__text": {"zh": "换一个完整的 checkpoint。", "en": "Pick a complete checkpoint."}}}]}}
    assert hint_text(only, "en") == "Pick a complete checkpoint.", "只有一步不编号"
    assert hint_text({}, "zh") == "" and hint_text({"hint": "一句话"}, "zh") == "", "不是「原因 + 怎么修」的形状不认"


def test_画板格子跑挂了_原因和怎么修拼好存进格子() -> None:
    from tests.util import fresh_client
    from app.domain.boards import deliver_generated, receipt_to_item

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board_id = client.post("/api/boards", json={"workspace_id": workspace, "name": "B", "canvas": {
        "items": [{"id": "img", "kind": "image", "x": 0, "y": 0, "run": {"status": "running", "job_id": "job-1"}}],
        "edges": [],
    }}).json()["id"]
    job = SimpleNamespace(id="job-1", status="failed", result=None, error="ComfyUI 执行失败:KSampler: hostbuf_file_reader_read failed",
                          error_key="providerErr_pluginFailed", error_params=COMFY_FAILURE, created_by=None)
    with SessionLocal() as db:
        deliver_generated(db, job, receipt_to_item(board_id, "img"))
    run = client.get(f"/api/boards/{board_id}", params={"workspace_id": workspace}).json()["canvas"]["items"][0]["run"]
    assert run["error"] == "ComfyUI 执行到「KSampler」这一步出错"
    assert run["error_hint"].startswith("那台 ComfyUI 装的 comfy-kitchen 太旧\n1. ") and UPGRADE in run["error_hint"]


def test_插件说的失败的样子_原因和步骤收成规整的形状() -> None:
    from app.domain.plugins.runtime import failure_shape

    shape = failure_shape({"remote": "failed", "hint": {
        "cause": {"zh": " 太旧了 ", "en": "Too old", "fr": ""},
        "steps": [{"text": {"zh": "升级:"}, "command": f"  {UPGRADE}  "}, {"text": ""}, "乱写的", {"command": "comfy restart"}],
    }})
    assert shape["hint"] == {"cause": {"zh": "太旧了", "en": "Too old"},
                             "steps": [{"text": {"zh": "升级:"}, "command": UPGRADE}, {"command": "comfy restart"}]}
    assert "hint" not in failure_shape({"hint": "一整句话,命令埋在里面"}), "一句话不是「原因 + 怎么修」:不认"
    assert "hint" not in failure_shape({"hint": {"cause": " ", "steps": [{"text": ""}]}}), "一格都没有就是没有"
    many = failure_shape({"hint": {"steps": [{"text": f"第 {n} 步"} for n in range(20)]}})
    assert len(many["hint"]["steps"]) == 6, "步骤有上限"


def test_老的一整句提示挪进原因_重跑不变() -> None:
    """1.22.0 插件交的 hint 是一整句话:迁移把它原样挪进 `cause`(任务和生成记录两处),新形状不动。"""
    from sqlalchemy import text as sql

    from app.core.db import engine
    from app.db.migrations import _migrate_failure_hints_say_cause_and_steps
    from tests.util import fresh_client

    client = fresh_client()
    old_hint = {"__text": {"zh": "这是那台 ComfyUI 上的问题:…… pip install -U comfy-kitchen ……", "en": "This is …"}}
    old = {**COMFY_FAILURE, "hint": old_hint}
    workspace = _failed_generation(client, key="providerErr_pluginFailed", params=old, error="x")
    _failed_generation(client, key="providerErr_pluginFailed", params=COMFY_FAILURE, error="y")
    _failed_generation(client, key="providerErr_pluginFailed", params={**COMFY_FAILURE, "hint": ""}, error="z")

    _migrate_failure_hints_say_cause_and_steps()
    _migrate_failure_hints_say_cause_and_steps()

    with engine.begin() as conn:
        rows = [*conn.execute(sql("SELECT error, error_params FROM jobs")), *conn.execute(sql("SELECT error, error_params FROM generation_jobs"))]
    hints: dict[str, list] = {}
    for error, raw in rows:
        params = json.loads(raw) if isinstance(raw, str) else raw
        hints.setdefault(error, []).append(params.get("hint", "—"))
    assert hints["x"] == [{"cause": old_hint}, {"cause": old_hint}], "任务和生成记录两处都挪了"
    assert hints["y"] == [COMFY_FAILURE["hint"], COMFY_FAILURE["hint"]], "新形状不动"
    assert hints["z"] == ["—", "—"], "空的提示去掉"
    [record] = client.get("/api/generation/jobs", params={"workspace_id": workspace}).json()
    assert record["error_hint"] == {"cause": old_hint["__text"]["zh"], "steps": []}


def test_插件没说人话的_只留原因_原文和它一样就没有详情() -> None:
    from tests.util import fresh_client

    client = fresh_client()
    params = {"name": "ComfyUI · http://192.168.3.15:8188", "detail": "ComfyUI 里这个任务被中断了"}
    workspace = _failed_generation(client, key="providerErr_pluginFailed", params=params,
                                   error="「ComfyUI · http://192.168.3.15:8188」生成失败:ComfyUI 里这个任务被中断了")
    [record] = client.get("/api/generation/jobs", params={"workspace_id": workspace}).json()
    assert record["error_summary"] == "ComfyUI 里这个任务被中断了", "「「连接名」生成失败:」那截前缀不进那一句"
    assert record["error_detail"] is None, "原文和那一句说的是同一件事:不摆详情"
    assert record["error_hint"] is None


def test_原文比那一句多出信息时才给详情() -> None:
    from app.domain.failure_summary import detail_of

    params = {"vendor": "DashScope", "detail": HTTPX_401 + BODY}
    assert detail_of("x", "providerErr_requestFailed", params, "zh").startswith("Client error '401 Unauthorized'")
    assert detail_of("服务商已经生成好了。", "", {}, "zh") is None
