"""本地解析(ADR 0031 第三步):每种文档切成段、写出 Markdown;导入时自动解析一遍,结果按段读得到。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.domain.documents import local, office
from tests.document_samples import docx_bytes, epub_bytes, pdf_bytes, pptx_bytes, write, xlsx_bytes
from tests.util import fresh_client


@pytest.fixture(autouse=True)
def no_libreoffice(monkeypatch):
    """默认当本机没装 LibreOffice —— 测试不依赖机器上碰巧装了什么。要它的测试自己换掉。"""
    monkeypatch.setattr(office, "find_soffice", lambda: None)


def _parse(tmp_path: Path, name: str, data):
    return local.parse_local(write(tmp_path, name, data), tmp_path / "out")


def test_PDF_按页切_每页有文字和页面图(tmp_path) -> None:
    parsed = _parse(tmp_path, "a.pdf", pdf_bytes(["Opening page", "Second page body"]))
    assert parsed.unit == "page"
    assert [one.markdown for one in parsed.sections] == ["Opening page", "Second page body"]
    assert parsed.sections[0].title == "Opening page"
    assert [one.image for one in parsed.sections] == ["pages/001.png", "pages/002.png"]
    assert (tmp_path / "out" / "pages" / "002.png").stat().st_size > 0
    assert "<!-- page: 2 -->\nSecond page body" in parsed.markdown


def test_几乎没有字的_PDF_提醒可能是扫描件(tmp_path) -> None:
    parsed = _parse(tmp_path, "scan.pdf", pdf_bytes(["x", "y"]))
    assert "docNote_littleText" in parsed.notes


def test_PPT_按幻灯片切_标题_要点_备注(tmp_path) -> None:
    parsed = _parse(tmp_path, "deck.pptx", pptx_bytes([("季度汇报", ["营收增长 20%", "新增用户 3 万"], "先讲营收"),
                                                        ("下一步", ["上线新功能"], "")]))
    assert parsed.unit == "slide" and len(parsed.sections) == 2
    first = parsed.sections[0]
    assert first.title == "季度汇报"
    assert first.markdown.startswith("# 季度汇报")
    assert "- 营收增长 20%" in first.markdown and "- 新增用户 3 万" in first.markdown
    assert "> 先讲营收" in first.markdown
    #: 没装 LibreOffice:没有页面图,如实说。
    assert first.image is None and "docNote_noPageImages" in parsed.notes


def test_Word_按标题切章(tmp_path) -> None:
    parsed = _parse(tmp_path, "plan.docx", docx_bytes([("Heading1", "背景"), ("", "市场在变。"),
                                                       ("Heading1", "方案"), ("", "做三件事。")]))
    assert parsed.unit == "section"
    assert [one.title for one in parsed.sections] == ["背景", "方案"]
    assert "市场在变。" in parsed.sections[0].markdown and "做三件事。" in parsed.sections[1].markdown


def test_Excel_一张表一段_表格截断会说(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(local, "MAX_TABLE_ROWS", 3)
    parsed = _parse(tmp_path, "data.xlsx", xlsx_bytes({"销量": [["月份", "数量"], ["1月", 10], ["2月", 12], ["3月", 9], ["4月", 30]],
                                                       "备注": [["说明"], ["内部数据"]]}))
    assert parsed.unit == "sheet" and [one.title for one in parsed.sections] == ["销量", "备注"]
    assert "| 月份 | 数量 |" in parsed.sections[0].markdown and "| 1月 | 10 |" in parsed.sections[0].markdown
    assert "4月" not in parsed.sections[0].markdown and "docNote_tableTruncated" in parsed.notes


def test_CSV_认得_GB18030_编码(tmp_path) -> None:
    parsed = _parse(tmp_path, "名单.csv", "姓名,城市\n张三,北京\n".encode("gb18030"))
    assert "| 姓名 | 城市 |" in parsed.sections[0].markdown and "| 张三 | 北京 |" in parsed.sections[0].markdown


def test_Markdown_文本_网页_电子书(tmp_path) -> None:
    md = _parse(tmp_path, "a.md", "# 一\n内容一\n\n# 二\n内容二\n")
    assert [one.title for one in md.sections] == ["一", "二"]
    html = _parse(tmp_path, "b.html", "<html><body><h1>标题</h1><p>正文<b>加粗</b></p><script>x()</script></body></html>")
    assert "# 标题" in html.markdown and "**加粗**" in html.markdown and "x()" not in html.markdown
    book = _parse(tmp_path, "c.epub", epub_bytes([("第一章", "从前"), ("第二章", "后来")]))
    assert [one.title for one in book.sections] == ["第一章", "第二章"] and "后来" in book.markdown


def test_老格式没装_LibreOffice_说清楚要装(tmp_path) -> None:
    with pytest.raises(local.DocumentParseError) as raised:
        _parse(tmp_path, "old.doc", b"\xd0\xcf\x11\xe0 legacy")
    assert raised.value.key == "docErr_legacyNeedsLibreOffice"


def test_坏文件说读不了(tmp_path) -> None:
    with pytest.raises(local.DocumentParseError) as raised:
        _parse(tmp_path, "broken.pptx", b"PK\x03\x04 not a deck")
    assert raised.value.key == "docErr_unreadable"


def test_装了_LibreOffice_PPT_每张幻灯片有页面图(tmp_path, monkeypatch) -> None:
    """LibreOffice 本身不在测试机上:换成一个把 PDF 交出来的假转换,只验「转出 PDF 后按页配到幻灯片上」。"""
    def fake_convert(source: Path, fmt: str, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{source.stem}.pdf"
        target.write_bytes(pdf_bytes(["one", "two"]))
        return target

    monkeypatch.setattr(office, "convert", fake_convert)
    parsed = _parse(tmp_path, "deck.pptx", pptx_bytes([("A", ["a"], ""), ("B", ["b"], "")]))
    assert [one.image for one in parsed.sections] == ["pages/001.png", "pages/002.png"]
    assert "docNote_noPageImages" not in parsed.notes


# ── 端到端:导入 → 自动解析 → 按段读 ─────────────────────────────────────────


def _wait(client, asset_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        listed = client.get(f"/api/assets/{asset_id}/extractions").json()
        if listed and listed[0]["status"] in ("succeeded", "failed"):
            return listed[0]
        time.sleep(0.1)
    raise AssertionError("解析一直没结束")


def test_导入文档就用本地解析解一遍_全文和页面图读得到_封面换成第一页() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    made = client.post("/api/assets/import", data={"workspace_id": ws},
                       files={"file": ("brief.pdf", pdf_bytes(["Cover", "Details"]), "application/pdf")}).json()
    done = _wait(client, made["id"])
    assert done["status"] == "succeeded", done
    assert done["parser"] == "builtin:local" and done["parser_name"] == "本地解析"
    assert done["unit"] == "page" and done["sections"] == 2
    assert [one["title"] for one in done["outline"]] == ["Cover", "Details"]

    second = client.get(f"/api/assets/{made['id']}/extractions/{done['id']}/sections", params={"first": 2}).json()
    assert second["total"] == 2 and second["unit"] == "page"
    assert [(one["index"], one["markdown"], one["image"]) for one in second["sections"]] == [(2, "Details", "pages/002.png")]
    page = client.get(f"/api/assets/{made['id']}/extractions/{done['id']}/files/pages/001.png")
    assert page.status_code == 200 and page.content.startswith(b"\x89PNG")
    #: 解析目录之外的文件不给(路径是从 Markdown 里来的)。
    escaped = client.get(f"/api/assets/{made['id']}/extractions/{done['id']}/files/../../brief.pdf")
    assert escaped.status_code == 404
    asset = client.get(f"/api/assets/{made['id']}").json()
    assert asset["media_info"]["pages"] == 2 and asset["media_info"]["has_thumbnail"] is True
    assert client.get(f"/api/assets/{made['id']}/thumbnail").status_code == 200


def test_重新解析_失败的也留一行说原因() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    made = client.post("/api/assets/import", data={"workspace_id": ws},
                       files={"file": ("broken.pptx", b"PK\x03\x04 nope", "application/octet-stream")}).json()
    failed = _wait(client, made["id"])
    assert failed["status"] == "failed" and "读不了" in failed["error"]
    again = client.post(f"/api/assets/{made['id']}/extractions", json={})
    assert again.status_code == 200 and again.json()["parser"] == "builtin:local"
    assert len(client.get(f"/api/assets/{made['id']}/extractions").json()) == 2


def test_存成笔记_插图这时才进素材库_分页隔开_来源记着原文档() -> None:
    from tests.document_samples import pptx_bytes

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    made = client.post("/api/assets/import", data={"workspace_id": ws}, files={"file": (
        "季度汇报.pptx", pptx_bytes([("营收", ["增长 20%"], ""), ("计划", ["上线会员"], "")], picture_on=1), "application/octet-stream")}).json()
    done = _wait(client, made["id"])
    assert done["status"] == "succeeded", done
    before = {one["id"] for one in client.get("/api/assets", params={"workspace_id": ws}).json()["items"]}
    assert before == {made["id"]}, "解析出的插图不进素材库"

    saved = client.post(f"/api/assets/{made['id']}/note")
    assert saved.status_code == 200, saved.text
    note = client.get(f"/api/notes/{saved.json()['note_id']}", params={"workspace_id": ws}).json()
    assert note["title"] == "季度汇报"
    assert "# 营收" in note["markdown"] and "\n\n---\n\n# 计划" in note["markdown"]
    assert "<!--" not in note["markdown"], "页码标记不进笔记"
    assert note["sources"][0]["kind"] == "asset" and note["sources"][0]["id"] == made["id"]
    images = [one for one in client.get("/api/assets", params={"workspace_id": ws}).json()["items"] if one["id"] != made["id"]]
    assert len(images) == 1 and images[0]["kind"] == "image"
    assert f"mosael-asset:{images[0]['id']}" in note["markdown"]
    detail = client.get(f"/api/assets/{images[0]['id']}").json()
    assert detail["derived_from"] == [{"asset_id": made["id"], "op": "extract"}], "插图记着是从哪份文档里取出来的"


def test_还没解析好的不能存成笔记() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    made = client.post("/api/assets/import", data={"workspace_id": ws},
                       files={"file": ("broken.pptx", b"PK\x03\x04 nope", "application/octet-stream")}).json()
    _wait(client, made["id"])
    refused = client.post(f"/api/assets/{made['id']}/note")
    assert refused.status_code == 409 and "还没解析好" in refused.json()["detail"]


def test_迁移_早先建的解析表补上页面图列_从各段抄过来() -> None:
    import json as _json

    from sqlalchemy import inspect as sa_inspect, text

    from app.core.db import engine
    from app.db.migrations import _migrate_asset_extractions_remember_page_images, migration_plan

    assert "migrate-asset-extractions-remember-page-images" in {step.name for step in migration_plan().steps}
    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE asset_extractions"))
        conn.execute(text("CREATE TABLE asset_extractions (id VARCHAR(64) PRIMARY KEY, asset_id VARCHAR(64), workspace_id VARCHAR(64), "
                          "parser VARCHAR(64), parser_name VARCHAR(200), status VARCHAR(16), error TEXT, job_id VARCHAR(64), unit VARCHAR(16), "
                          "sections INTEGER, chars INTEGER, outline JSON, notes JSON, created_at DATETIME, finished_at DATETIME)"))
        conn.execute(text("INSERT INTO asset_extractions (id, outline) VALUES ('x', :outline)"),
                     {"outline": _json.dumps([{"index": 1, "image": "pages/001.png"}, {"index": 2, "image": None}])})
    _migrate_asset_extractions_remember_page_images()
    _migrate_asset_extractions_remember_page_images()
    assert "page_images" in {one["name"] for one in sa_inspect(engine).get_columns("asset_extractions")}
    with engine.connect() as conn:
        assert _json.loads(conn.execute(text("SELECT page_images FROM asset_extractions WHERE id = 'x'")).scalar()) == ["pages/001.png"]
    fresh_client()  # 把表按当前模型重建回来,别的测试照常


def test_几份_PDF_同时解析不把进程打挂(tmp_path) -> None:
    """pdfium 不是线程安全的:两个解析任务在两个线程里同时渲页面图,整个进程 abort(Fatal Python error)。
    每一次碰 pdfium 都在同一把锁里(local._PDFIUM)。这条测试没有那把锁时会直接把 pytest 进程打死。"""
    import threading

    sources = [write(tmp_path, f"doc{n}.pdf", pdf_bytes([f"Page {i} of {n}" for i in range(12)])) for n in range(4)]
    results: dict[int, object] = {}

    def parse(n: int) -> None:
        try:
            results[n] = local.parse_local(sources[n], tmp_path / f"out{n}")
        except Exception as exc:  # noqa: BLE001 —— 收起来断言,不让线程吞掉
            results[n] = exc

    threads = [threading.Thread(target=parse, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(not isinstance(one, Exception) for one in results.values()), results
    assert [len(results[n].sections) for n in range(4)] == [12, 12, 12, 12]


def test_解析中停下_记成已停止_任务不被改成失败(monkeypatch) -> None:
    """一份几百页的 PDF 开始解析就只能等它跑完(用户截图)。停下后解析那一行是 cancelled、没有原因;
    任务仍是「已取消」,读文档的地方说「被停下了」而不是「还在解析」。"""
    from app.core.db import SessionLocal
    from app.db.models import Job
    from app.domain.documents import extraction
    from app.domain.jobs import cancel_job

    def slow_parse(source, target, on_progress=None):
        with SessionLocal() as db:
            job = db.scalars(select(Job).where(Job.kind == "document_parse").order_by(Job.created_at.desc())).first()
            cancel_job(db, job)
            db.commit()  # 测试是入口:cancel_job 不提交
        on_progress(0.3, "docProgress_readPages")
        raise AssertionError("停下之后不该再往下读")

    monkeypatch.setattr(extraction, "parse_local", slow_parse)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    made = client.post("/api/assets/import", data={"workspace_id": ws},
                       files={"file": ("long.pdf", pdf_bytes(["One"]), "application/pdf")}).json()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        listed = client.get(f"/api/assets/{made['id']}/extractions").json()
        if listed and listed[0]["status"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert listed[0]["status"] == "cancelled" and listed[0]["error"] == "", listed[0]["error"]
    from app.domain.jobs import was_cancelled

    with SessionLocal() as db:
        assert was_cancelled(db.get(Job, listed[0]["job_id"])), "任务仍是「被取消」,没被解析那一侧改成一条失败"
    text = client.get(f"/api/assets/{made['id']}/document/text", params={"workspace_id": ws})
    assert text.status_code == 200 and text.json()["status"] == "failed", "停下的不能一直显示「解析中」"
