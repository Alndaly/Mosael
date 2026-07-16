from __future__ import annotations

import time
from pathlib import Path

import httpx

from app.core.config import settings

"""
文件 → markdown 转换引擎(Revornix 的引擎抽象思路,单机裁剪版):
- mineru:MinerU 官方 API(mineru.net,批量接口 + 轮询 + zip 结果),
  排版还原最好,需要 token;
- markitdown:微软 MarkItDown,本地转换 PDF/Word/PPT/Excel/HTML;
- text:纯文本/markdown 直接读。
auto 优先级:mineru(配了 token)→ markitdown → text。
"""

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
CONVERTIBLE_SUFFIXES = {".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".xls", ".html", ".htm", ".csv", ".epub"}
MINERU_SUFFIXES = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg"}
MINERU_POLL_SECONDS = 3
MINERU_TIMEOUT_SECONDS = 300


class KbConvertError(RuntimeError):
    pass


def active_engine() -> str:
    engine = settings.kb_convert_engine
    if engine != "auto":
        return engine
    if settings.mineru_api_token:
        return "mineru"
    return "markitdown"


def convert_file_to_markdown(path: Path, filename: str) -> str:
    """把上传文件转成 markdown 文本;失败抛 KbConvertError(带可读原因)。"""
    suffix = Path(filename).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")

    engine = active_engine()
    if engine == "text":
        raise KbConvertError(f"当前转换引擎为 text,无法解析 {suffix} 文件")
    if engine == "mineru" and suffix in MINERU_SUFFIXES:
        try:
            return _convert_with_mineru(path, filename)
        except KbConvertError:
            # MinerU 失败回退本地 markitdown,尽量不让导入死掉。
            pass
    return _convert_with_markitdown(path, filename)


def _convert_with_markitdown(path: Path, filename: str) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError as exc:  # pragma: no cover - 依赖装在 venv 里
        raise KbConvertError("markitdown 未安装") from exc
    try:
        result = MarkItDown(enable_plugins=False).convert(str(path))
    except Exception as exc:
        raise KbConvertError(f"markitdown 解析失败: {exc}") from exc
    text = (result.text_content or "").strip()
    if not text:
        raise KbConvertError(f"{filename} 没有可提取的文本内容")
    return text


def _convert_with_mineru(path: Path, filename: str) -> str:
    """MinerU 官方批量 API:申请上传地址 → PUT 文件 → 轮询 → 下载 zip 取 md。"""
    base = settings.mineru_api_base.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.mineru_api_token}"}
    try:
        with httpx.Client(timeout=60, headers=headers) as client:
            created = client.post(
                f"{base}/api/v4/file-urls/batch",
                json={"files": [{"name": filename, "is_ocr": True}], "language": "auto"},
            )
            created.raise_for_status()
            data = created.json().get("data") or {}
            batch_id = data.get("batch_id")
            urls = data.get("file_urls") or []
            if not batch_id or not urls:
                raise KbConvertError(f"MinerU 返回异常: {created.text[:200]}")
            upload = httpx.put(urls[0], content=path.read_bytes(), timeout=120)
            upload.raise_for_status()

            deadline = time.monotonic() + MINERU_TIMEOUT_SECONDS
            zip_url = ""
            while time.monotonic() < deadline:
                status = client.get(f"{base}/api/v4/extract-results/batch/{batch_id}")
                status.raise_for_status()
                results = (status.json().get("data") or {}).get("extract_result") or []
                if results:
                    state = results[0].get("state")
                    if state == "done":
                        zip_url = results[0].get("full_zip_url", "")
                        break
                    if state == "failed":
                        raise KbConvertError(f"MinerU 解析失败: {results[0].get('err_msg', '未知错误')}")
                time.sleep(MINERU_POLL_SECONDS)
            if not zip_url:
                raise KbConvertError("MinerU 解析超时")
            return _extract_markdown_from_zip(httpx.get(zip_url, timeout=120).content)
    except httpx.HTTPError as exc:
        raise KbConvertError(f"MinerU 请求失败: {exc}") from exc


def _extract_markdown_from_zip(blob: bytes) -> str:
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            names = [name for name in archive.namelist() if name.endswith(".md") and not name.startswith("__MACOSX")]
            if not names:
                raise KbConvertError("MinerU 结果里没有 markdown 文件")
            names.sort(key=lambda name: (0 if name.endswith("full.md") else 1, len(name)))
            text = archive.read(names[0]).decode("utf-8", errors="replace").strip()
            if not text:
                raise KbConvertError("MinerU 结果为空")
            return text
    except zipfile.BadZipFile as exc:
        raise KbConvertError("MinerU 结果包损坏") from exc
