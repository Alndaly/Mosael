"""MinerU 文档解析 —— 把一份文档交给 MinerU(mineru.net)转成 Markdown,交回给 Mosael(ADR 0031)。

## 为什么要它

Mosael 自带的本地解析只读文档里**已经有的文字**:原生的 Word / PPT / PDF 没问题,扫描件、图片版 PDF、
复杂排版(多栏、表格、公式)就不行了。MinerU 做版面分析、OCR、表格和公式识别,这些正是它的长处。

## 协议(宿主 → 插件)

宿主在文档解析任务里调 `mineru_parse`(它认领了 `document_parse`,只给宿主调):

- 入:`{"file": <原件副本的本地路径>, "filename": <原文件名>}`;
- 进度:stdout 的 NDJSON 进度行;宿主建了取消文件就停下来退出;
- 出:`{"markdown": "document.md"}` —— 写在 `MOSAEL_PLUGIN_OUTPUT_DIR` 里,每一页前一个 `<!-- page: N -->`,
  插图在同一目录的 `images/` 下、正文里用相对路径引用。

## 云端 API(mineru.net 的「API 管理」页,2026-09 对过)

本地文件不需要公网链接:`POST /api/v4/file-urls/batch` 要一条上传地址,`PUT` 字节上去(不带 Content-Type),
MinerU 自动开始解析;再轮询 `GET /api/v4/extract-results/batch/{batch_id}`,`state` 为 `done` 时取
`full_zip_url` —— zip 里有 `full.md`、`*_content_list.json`(每个块带 `page_idx`)和 `images/`。
`code` 为 0 才算成功。单个文件 200MB、200 页封顶。

**只用标准库**:插件进程和后端不共用依赖。
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

API = "https://mineru.net"
CANCEL_ENV = "MOSAEL_PLUGIN_CANCEL_FILE"
OUTPUT_ENV = "MOSAEL_PLUGIN_OUTPUT_DIR"
POLL_SECONDS = 3.0
#: 一次解析最多等多久(宿主给的预算是 1800 秒,留一点给下载和整理)。
WAIT_SECONDS = 1700.0
REQUEST_TIMEOUT = 60
MAX_BYTES = 200 * 1024 * 1024


class ParseError(RuntimeError):
    """说得出口的失败。消息直接进工具结果,所以要是一句人话。"""


def line(locale: str, zh: str, en: str) -> str:
    return zh if locale.replace("_", "-").split("-")[0].lower() == "zh" else en


class Reporter:
    def __init__(self) -> None:
        self.cancel_file = os.environ.get(CANCEL_ENV, "")

    def progress(self, fraction: float, message: str) -> None:
        print(json.dumps({"event": "progress", "progress": round(max(0.0, min(fraction, 1.0)), 4), "message": message},
                         ensure_ascii=False), flush=True)

    def cancelled(self) -> bool:
        return bool(self.cancel_file) and os.path.exists(self.cancel_file)


def _request(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None,
             timeout: float = REQUEST_TIMEOUT) -> bytes:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _api(locale: str, token: str, path: str, *, payload: dict | None = None) -> dict:
    """调一次 MinerU 的接口,回 `data`。`code` 不是 0、HTTP 出错、网络不通,都翻成一句人话。"""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    try:
        raw = _request(API + path, method="POST" if payload is not None else "GET", headers=headers, body=body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        if exc.code in (401, 403):
            raise ParseError(line(locale, "MinerU 不认这个 Token(过期了或填错了),去插件页重新填一个",
                                  "MinerU rejected the token (expired or wrong); enter a new one on the Plugins page")) from exc
        raise ParseError(line(locale, f"MinerU 返回 {exc.code}:{detail}", f"MinerU returned {exc.code}: {detail}")) from exc
    except urllib.error.URLError as exc:
        raise ParseError(line(locale, f"连不上 MinerU:{exc.reason}", f"Can't reach MinerU: {exc.reason}")) from exc
    try:
        answer = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise ParseError(line(locale, "MinerU 的回复读不懂", "Couldn't read MinerU's reply")) from exc
    if answer.get("code") not in (0, "0"):
        message = str(answer.get("msg") or answer.get("message") or answer.get("code"))
        raise ParseError(line(locale, f"MinerU 没接这一单:{message}", f"MinerU refused the job: {message}"))
    return answer.get("data") or {}


def _options() -> dict:
    return {
        "model_version": os.environ.get("MINERU_MODEL", "").strip() or "vlm",
        "language": os.environ.get("MINERU_LANGUAGE", "").strip() or "ch",
        "enable_formula": True,
        "enable_table": True,
    }


def _page_markdown(block: dict) -> str:
    """content_list 里的一块 → Markdown。表格留 MinerU 给的 HTML(宿主会转成 Markdown 表格)。"""
    kind = block.get("type")
    if kind in ("text", "title"):
        text = str(block.get("text") or "").strip()
        level = int(block.get("text_level") or 0)
        return f"{'#' * min(level, 6)} {text}" if level and text else text
    if kind == "list":
        items = block.get("list_items") or []
        return "\n".join(f"- {str(item).strip()}" for item in items) if items else str(block.get("text") or "").strip()
    if kind == "equation":
        return str(block.get("text") or "").strip()
    if kind == "image":
        caption = " ".join(str(one) for one in block.get("image_caption") or []).strip()
        path = str(block.get("img_path") or "").strip()
        return (f"![{caption}]({path})" if path else "") + (f"\n\n{caption}" if caption else "")
    if kind == "table":
        caption = " ".join(str(one) for one in block.get("table_caption") or []).strip()
        body = str(block.get("table_body") or "").strip()
        if not body and block.get("img_path"):
            body = f"![]({block['img_path']})"
        return "\n\n".join(part for part in (caption, body) if part)
    return str(block.get("text") or "").strip()


def _write_markdown(folder: Path, out: Path) -> int:
    """把 zip 里的结果整理成一份带页标记的 Markdown,交回页数。有 content_list 就按页排;没有就用 full.md 整篇。"""
    listing = next(iter(sorted(folder.rglob("*content_list.json"))), None)
    if listing is not None:
        blocks = json.loads(listing.read_text(encoding="utf-8"))
        pages: dict[int, list[str]] = {}
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            text = _page_markdown(block)
            if text:
                pages.setdefault(int(block.get("page_idx") or 0), []).append(text)
        if pages:
            body = "\n\n".join(f"<!-- page: {index + 1} -->\n" + "\n\n".join(pages[index]) for index in sorted(pages))
            (out / "document.md").write_text(body + "\n", encoding="utf-8")
            return len(pages)
    full = next(iter(sorted(folder.rglob("full.md"))), None)
    if full is None:
        raise ParseError("MinerU 的结果里没有正文(full.md)")
    (out / "document.md").write_text(full.read_text(encoding="utf-8"), encoding="utf-8")
    return 1


def parse(payload: dict, locale: str, reporter: Reporter) -> dict:
    token = os.environ.get("MINERU_TOKEN", "").strip()
    if not token:
        raise ParseError(line(locale, "还没填 MinerU 的 API Token", "The MinerU API token isn't set"))
    source = Path(str(payload.get("file") or ""))
    if not source.is_file():
        raise ParseError(line(locale, "没有拿到要解析的文件", "No file to parse"))
    if source.stat().st_size > MAX_BYTES:
        raise ParseError(line(locale, "MinerU 单个文件最多 200MB", "MinerU takes files up to 200 MB"))
    name = str(payload.get("filename") or source.name)
    out = Path(os.environ.get(OUTPUT_ENV) or source.parent)
    data_id = uuid.uuid4().hex

    reporter.progress(0.02, line(locale, "向 MinerU 申请上传", "Asking MinerU for an upload link"))
    ocr = os.environ.get("MINERU_OCR", "").strip().lower() == "yes"
    batch = _api(locale, token, "/api/v4/file-urls/batch",
                 payload={"files": [{"name": name, "data_id": data_id, "is_ocr": ocr}], **_options()})
    urls = batch.get("file_urls") or []
    batch_id = str(batch.get("batch_id") or "")
    if not urls or not batch_id:
        raise ParseError(line(locale, "MinerU 没给上传地址", "MinerU gave no upload link"))

    reporter.progress(0.05, line(locale, "上传文档", "Uploading the document"))
    try:
        #: 上传地址是签过名的对象存储链接:**不带 Content-Type**(带了签名就对不上)。
        _request(urls[0], method="PUT", body=source.read_bytes(), timeout=600)
    except urllib.error.URLError as exc:
        raise ParseError(line(locale, f"上传到 MinerU 失败:{exc}", f"Upload to MinerU failed: {exc}")) from exc

    deadline = time.monotonic() + WAIT_SECONDS
    zip_url = ""
    while time.monotonic() < deadline:
        if reporter.cancelled():
            raise ParseError(line(locale, "已停止", "Stopped"))
        result = _api(locale, token, f"/api/v4/extract-results/batch/{batch_id}")
        entry = next((one for one in result.get("extract_result") or [] if one.get("data_id") == data_id),
                     (result.get("extract_result") or [{}])[0])
        state = str(entry.get("state") or "")
        if state == "done":
            zip_url = str(entry.get("full_zip_url") or "")
            break
        if state == "failed":
            raise ParseError(line(locale, f"MinerU 解析失败:{entry.get('err_msg') or '没说原因'}",
                                  f"MinerU failed to parse it: {entry.get('err_msg') or 'no reason given'}"))
        done_pages = (entry.get("extract_progress") or {}).get("extracted_pages")
        total_pages = (entry.get("extract_progress") or {}).get("total_pages")
        if done_pages and total_pages:
            reporter.progress(0.1 + 0.75 * float(done_pages) / float(total_pages),
                              line(locale, f"MinerU 解析中 {done_pages}/{total_pages} 页", f"MinerU parsing {done_pages}/{total_pages} pages"))
        else:
            reporter.progress(0.1, line(locale, "MinerU 排队 / 解析中", "Queued / parsing at MinerU"))
        time.sleep(POLL_SECONDS)
    if not zip_url:
        raise ParseError(line(locale, "MinerU 太久没解析完,稍后再试", "MinerU took too long; try again later"))

    reporter.progress(0.9, line(locale, "取回结果", "Fetching the result"))
    archive = zipfile.ZipFile(io.BytesIO(_request(zip_url, timeout=600)))
    unpacked = out / "_mineru"
    for member in archive.namelist():
        #: zip 里的路径不能走出解包目录。
        target = (unpacked / member).resolve()
        if member.endswith("/") or not target.is_relative_to(unpacked.resolve()):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(member))
    #: 插图挪到输出目录的 images/ 下,正文里的 `images/…` 引用照旧成立。
    images = next((one for one in unpacked.rglob("images") if one.is_dir()), None)
    if images is not None:
        (out / "images").mkdir(parents=True, exist_ok=True)
        for one in images.rglob("*"):
            if one.is_file():
                destination = out / "images" / one.relative_to(images)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(one.read_bytes())
    pages = _write_markdown(unpacked, out)
    return {"markdown": "document.md", "pages": pages,
            "summary": line(locale, f"MinerU 解析了 {pages} 页", f"MinerU parsed {pages} pages")}


def run() -> None:
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"bad request json: {exc}"}))
        return
    locale = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
    name = str(request.get("tool") or "")
    if name != "mineru_parse":
        print(json.dumps({"ok": False, "error": f"unknown tool: {name}"}))
        return
    try:
        output = parse(dict(request.get("input") or {}), locale, Reporter())
    except ParseError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return
    except Exception as exc:  # noqa: BLE001 —— 插件的异常不该只剩一个栈
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return
    print(json.dumps({"ok": True, "output": output}, ensure_ascii=False))


if __name__ == "__main__":
    run()
