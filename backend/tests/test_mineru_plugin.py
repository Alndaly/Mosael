"""MinerU 文档解析插件(ADR 0031 第五步)和宿主那一侧的 `document_parse` 协议。

- 插件:向 MinerU 要上传地址 → PUT 字节 → 轮询 → 取 zip → 按 content_list 的 page_idx 整理成带页标记的
  Markdown、插图搬到 images/。MinerU 那边用假的 HTTP 代替(不打真接口)。
- 宿主:点名一个认领了 document_parse 的插件解析 —— 副本交给插件、正文按页标记切段、HTML 表格转成
  Markdown 表格、插图搬进解析目录、页面图照原件渲(和本地解析一样)。
"""

from __future__ import annotations

import importlib.util
import io
import json
import textwrap
import time
import zipfile
from pathlib import Path

import pytest

from tests.document_samples import pdf_bytes, png_bytes

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "mineru"


def _plugin_module():
    spec = importlib.util.spec_from_file_location("mineru_main", PLUGIN / "tools" / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result_zip() -> bytes:
    blocks = [
        {"type": "text", "text": "年度报告", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "营收增长 20%。", "page_idx": 0},
        {"type": "table", "table_body": "<table><tr><td>月份</td><td>数量</td></tr><tr><td>1月</td><td>10</td></tr></table>",
         "table_caption": ["表 1 销量"], "page_idx": 1},
        {"type": "image", "img_path": "images/chart.png", "image_caption": ["图 1"], "page_idx": 1},
        {"type": "equation", "text": "$$E=mc^2$$", "page_idx": 1},
    ]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("abc/full.md", "# 年度报告\n")
        archive.writestr("abc/abc_content_list.json", json.dumps(blocks, ensure_ascii=False))
        archive.writestr("abc/images/chart.png", png_bytes())
        archive.writestr("../escape.txt", "no")
    return out.getvalue()


def test_插件_上传_轮询_取回_按页整理(tmp_path, monkeypatch, capsys) -> None:
    module = _plugin_module()
    calls: list[tuple[str, str]] = []
    polls = iter([
        {"code": 0, "data": {"extract_result": [{"data_id": "?", "state": "running", "extract_progress": {"extracted_pages": 1, "total_pages": 2}}]}},
        {"code": 0, "data": {"extract_result": [{"data_id": "?", "state": "done", "full_zip_url": "https://cdn/x.zip"}]}},
    ])

    def fake_request(url, *, method="GET", headers=None, body=None, timeout=60):
        calls.append((method, url))
        if url.endswith("/api/v4/file-urls/batch"):
            sent = json.loads(body)
            assert headers["Authorization"] == "Bearer secret-token"
            assert sent["files"][0]["name"] == "报告.pdf" and sent["model_version"] == "vlm" and sent["files"][0]["is_ocr"] is False
            return json.dumps({"code": 0, "data": {"batch_id": "b1", "file_urls": ["https://upload/signed"]}}).encode()
        if url == "https://upload/signed":
            assert method == "PUT" and "Content-Type" not in (headers or {}), "签过名的上传地址不能带 Content-Type"
            return b""
        if "/extract-results/batch/b1" in url:
            return json.dumps(next(polls)).encode()
        if url == "https://cdn/x.zip":
            return _result_zip()
        raise AssertionError(url)

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "POLL_SECONDS", 0)
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    monkeypatch.setenv("MOSAEL_PLUGIN_OUTPUT_DIR", str(tmp_path))
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF fake")

    output = module.parse({"file": str(source), "filename": "报告.pdf"}, "zh", module.Reporter())
    assert output["markdown"] == "document.md" and output["pages"] == 2
    markdown = (tmp_path / "document.md").read_text(encoding="utf-8")
    assert markdown.startswith("<!-- page: 1 -->\n# 年度报告\n\n营收增长 20%。")
    assert "<!-- page: 2 -->\n表 1 销量\n\n<table>" in markdown and "![图 1](images/chart.png)" in markdown and "$$E=mc^2$$" in markdown
    assert (tmp_path / "images" / "chart.png").is_file()
    assert not (tmp_path.parent / "escape.txt").exists(), "zip 里的路径不能走出解包目录"
    progress = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any("1/2" in one["message"] for one in progress)


def test_插件_Token_不对说清楚去哪儿改(tmp_path, monkeypatch) -> None:
    import urllib.error

    module = _plugin_module()

    def rejected(url, **_kwargs):
        raise urllib.error.HTTPError(url, 401, "no", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(module, "_request", rejected)
    monkeypatch.setenv("MINERU_TOKEN", "bad")
    source = tmp_path / "a.pdf"
    source.write_bytes(b"x")
    with pytest.raises(module.ParseError, match="Token"):
        module.parse({"file": str(source)}, "zh", module.Reporter())


def test_清单_只给宿主调_认领文档解析() -> None:
    from app.domain.plugins.manifest import parse

    manifest = parse(json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8")), str(PLUGIN))
    assert manifest.provides == ["document_parse"] and manifest.tool_providing("document_parse") == "mineru_parse"
    assert [one.key for one in manifest.credentials] == ["MINERU_TOKEN"]


# ── 宿主那一侧 ──────────────────────────────────────────────────────────────


FAKE_PARSER = {
    "id": "dev.test.fakeparser", "manifest_version": 1, "name": "假解析", "version": "1",
    "provides": ["document_parse"], "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {"declare": [{"name": "parse", "provides": ["document_parse"], "stream": True, "timeout_seconds": 60}]},
}
FAKE_ENTRY = textwrap.dedent('''
    import json, os, sys, base64
    request = json.loads(sys.stdin.read())
    payload = request["input"]
    out = os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"]
    assert os.path.isfile(payload["file"]) and payload["filename"] == "brief.pdf"
    print(json.dumps({"event": "progress", "progress": 0.5, "message": "解析中"}), flush=True)
    os.makedirs(os.path.join(out, "images"), exist_ok=True)
    open(os.path.join(out, "images", "fig.png"), "wb").write(base64.b64decode(%r))
    body = "<!-- page: 1 -->\\n# 封面\\n![](images/fig.png)\\n\\n<!-- page: 2 -->\\n<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>"
    open(os.path.join(out, "doc.md"), "w", encoding="utf-8").write(body)
    print(json.dumps({"ok": True, "output": {"markdown": "doc.md"}}))
''')


def test_宿主_点名插件解析_按页切段_表格转成_Markdown_插图搬过来_页面图照原件渲(monkeypatch) -> None:
    import base64

    from app.domain.documents import office
    from tests.test_plugins import install

    monkeypatch.setattr(office, "find_soffice", lambda: None)
    from app.core.db import SessionLocal
    from app.db.models import PluginInstance

    client = install(FAKE_PARSER, entry=FAKE_ENTRY % base64.b64encode(png_bytes()).decode())
    with SessionLocal() as db:
        #: 装上之后的连接默认是停用的 —— 用户在插件页启用它。
        for instance in db.query(PluginInstance).filter_by(package_id=FAKE_PARSER["id"]):
            instance.enabled = True
        db.commit()
    ws = client.get("/api/workspaces").json()[0]["id"]
    parser = next(one for one in client.get("/api/settings/capabilities").json() if one["capability"] == "document_parse")
    plugin = next(one for one in parser["options"] if not one["builtin"])
    made = client.post("/api/assets/import", data={"workspace_id": ws},
                       files={"file": ("brief.pdf", pdf_bytes(["Cover", "Table page"]), "application/pdf")}).json()

    def settled(extraction_id: str) -> dict:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            one = next(row for row in client.get(f"/api/assets/{made['id']}/extractions").json() if row["id"] == extraction_id)
            if one["status"] in ("succeeded", "failed"):
                return one
            time.sleep(0.1)
        raise AssertionError("没解析完")

    started = client.post(f"/api/assets/{made['id']}/extractions", json={"provider_id": plugin["id"]})
    assert started.status_code == 200, started.text
    done = settled(started.json()["id"])
    assert done["status"] == "succeeded", done
    assert done["parser"] == plugin["id"] and done["unit"] == "page" and done["sections"] == 2
    assert done["page_images"] == ["pages/001.png", "pages/002.png"], "页面图照原件渲,哪一家解析的都一样"
    sections = client.get(f"/api/assets/{made['id']}/extractions/{done['id']}/sections").json()["sections"]
    assert sections[0]["title"] == "封面" and "![](images/fig.png)" in sections[0]["markdown"]
    assert "| a | b |" in sections[1]["markdown"] and "<table" not in sections[1]["markdown"]
    image = client.get(f"/api/assets/{made['id']}/extractions/{done['id']}/files/images/fig.png")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    #: 读的时候用最新成功的那一份 —— 智能体读到的就是插件解析的。
    assert client.get(f"/api/assets/{made['id']}/document").json()["parser"] == "假解析"
