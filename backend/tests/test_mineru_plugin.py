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

    def fake_request(locale, url, *, method="GET", headers=None, body=None, timeout=60, bare_upload=False):
        calls.append((method, url))
        if url.endswith("/api/v4/file-urls/batch"):
            sent = json.loads(body)
            assert headers["Authorization"] == "Bearer secret-token"
            assert sent["files"][0]["name"] == "报告.pdf" and sent["model_version"] == "vlm" and sent["files"][0]["is_ocr"] is False
            return json.dumps({"code": 0, "data": {"batch_id": "b1", "file_urls": ["https://upload/signed"]}}).encode()
        if url == "https://upload/signed":
            assert method == "PUT" and bare_upload and "Content-Type" not in (headers or {}), "签过名的上传地址不能带 Content-Type"
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

    def rejected(locale, url, **_kwargs):
        raise urllib.error.HTTPError(url, 401, "no", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(module, "_request", rejected)
    monkeypatch.setenv("MINERU_TOKEN", "bad")
    source = tmp_path / "a.pdf"
    source.write_bytes(b"x")
    with pytest.raises(module.ParseError, match="Token"):
        module.parse({"file": str(source)}, "zh", module.Reporter())


def test_上传到预签名地址_真的不带_Content_Type() -> None:
    """urllib 只要请求带正文就自动补 `application/x-www-form-urlencoded` —— 签名里没有它,对象存储回 403。
    断言要落在 opener 真正发出去的那组头上:桩掉 `_request` 的话,这个头是在桩的下面才加的,测试看不见(之前就这么漏过)。"""
    import urllib.request

    module = _plugin_module()
    opener = module._opener("zh")
    handler = next(one for one in opener.handlers if isinstance(one, urllib.request.HTTPSHandler))

    def sent_headers(bare: bool) -> dict:
        request = urllib.request.Request("https://upload.example/signed", data=b"%PDF", method="PUT")
        request.bare_upload = bare
        return handler.https_request(request).unredirected_hdrs

    assert "Content-type" not in sent_headers(True)
    assert sent_headers(False)["Content-type"] == "application/x-www-form-urlencoded", "urllib 的默认行为变了,这层处理可以删"


def test_网络_照宿主注入的环境走_跟随_直连_指定代理(monkeypatch) -> None:
    """走哪条路是宿主替这个连接定的(domain/plugins/egress),插件只用 urllib 默认的 ProxyHandler 读环境变量。
    这里把三种决定各自给出的那份环境放进进程,看插件真正建出来的 opener 走不走代理。"""
    import urllib.request

    from app.domain.plugins.egress import Egress

    module = _plugin_module()

    def under(egress: Egress) -> dict:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            monkeypatch.delenv(key, raising=False)
            monkeypatch.delenv(key.lower(), raising=False)
        for key, value in egress.child_env().items():
            monkeypatch.setenv(key, value)
        handler = next(one for one in module._opener("zh").handlers if isinstance(one, urllib.request.ProxyHandler))
        return handler.proxies

    assert under(Egress("http://127.0.0.1:7890", "localhost,127.0.0.1"))["https"] == "http://127.0.0.1:7890"
    #: 直连是明说的 NO_PROXY=*:什么都不给的话,urllib 会退到系统代理。
    direct = under(Egress(no_proxy="*"))
    assert "https" not in direct and urllib.request.proxy_bypass_environment("mineru.net", direct)
    with pytest.raises(module.ParseError, match="SOCKS"):
        under(Egress("socks5://127.0.0.1:1080", "localhost"))


def test_上传被拒_提示区域和代理设置(tmp_path, monkeypatch) -> None:
    import urllib.error

    module = _plugin_module()

    def fake_request(locale, url, *, method="GET", **_kwargs):
        if url.endswith("/api/v4/file-urls/batch"):
            return json.dumps({"code": 0, "data": {"batch_id": "b1", "file_urls": ["https://upload/signed"]}}).encode()
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b"<Code>AccessDenied</Code>"))

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setenv("MINERU_TOKEN", "t")
    source = tmp_path / "a.pdf"
    source.write_bytes(b"x")
    with pytest.raises(module.ParseError) as caught:
        module.parse({"file": str(source)}, "zh", module.Reporter())
    assert "403" in str(caught.value) and "AccessDenied" in str(caught.value) and "中国大陆" in str(caught.value)


def test_清单里没有自己的网络字段_那是宿主给每个连接的() -> None:
    """代理曾是 MinerU 自己发明的一对配置(MINERU_NETWORK / MINERU_PROXY),跟的是系统代理,不知道 Mosael 的设置。
    现在它是宿主给每个插件连接的「网络」(见 domain/plugins/egress);清单里再出现就是两套规矩。"""
    from app.domain.plugins.manifest import parse

    manifest = parse(json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8")), PLUGIN)
    assert not [field.key for field in manifest.config if "NETWORK" in field.key or "PROXY" in field.key]


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

    #: 插件页:只给宿主调的那个工具也列出来(写着它替 Mosael 做什么),不再是一片空白(用户截图)。
    package = next(one for one in client.get("/api/plugins").json() if one["id"] == FAKE_PARSER["id"])
    instance = package["instances"][0]
    assert instance["tools"] == [] and [tool["provides"] for tool in instance["host_tools"]] == [["document_parse"]]

    #: 工作流「文档转 Markdown」能点名用哪一家:选项里有它;点名插件就用插件那一份,点名本地就用本地那一份。
    options = client.get("/api/workflows/field-options",
                         params={"workspace_id": ws, "source": "providers.document_parse"}).json()
    assert {"builtin:local", plugin["id"]} <= {one["value"] for one in options}
    from app.domain.workflows.executors import get_executor
    from tests.test_document_reading import _scope

    run = get_executor("document_to_markdown")
    with SessionLocal() as db:
        by_plugin = run(db, _scope(ws), {"asset_id": made["id"], "parser": plugin["id"]})
        by_local = run(db, _scope(ws), {"asset_id": made["id"], "parser": "builtin:local"})
    assert "封面" in by_plugin["markdown"] and "封面" not in by_local["markdown"] and "Cover" in by_local["markdown"]

    #: 智能体:reparse_document 按名字认解析方式,认不出说清楚有哪几家;起的是一次解析任务。
    from types import SimpleNamespace

    from app.domain.agent.confirmable.registry import tool_spec
    from app.domain.agent.errors import ConfirmationError
    from app.db.models import User

    spec = tool_spec("reparse_document")
    with SessionLocal() as db:
        owner = db.query(User).first().id
        with pytest.raises(ConfirmationError) as unknown:
            spec.validate(db, ws, {"asset_id": made["id"], "parser": "不存在的"}, owner)
        assert unknown.value.key == "confirmErr_unknownProvider" and "假解析" in str(unknown.value)
        spec.validate(db, ws, {"asset_id": made["id"], "parser": "假解析"}, owner)
        started = spec.execute(db, SimpleNamespace(payload={"asset_id": made["id"], "parser": "假解析"}, workspace_id=ws), owner)
    assert started["parser"] == "假解析" and settled(started["extraction_id"])["status"] == "succeeded"
