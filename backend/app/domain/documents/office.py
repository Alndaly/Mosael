"""本机的 LibreOffice(ADR 0031 拍板:**装了就用**)。Mosael 不打包它。

用它做两件事:Office 文档转 PDF(渲页面图,智能体能看到 PPT 的版式);老格式(doc / ppt / xls)转成新格式
(没有纯 Python 的可靠读法)。找不到就回 None,调用方说清楚「装了 LibreOffice 能……」。

每次转换用一个**临时的用户配置目录**:用户自己开着 LibreOffice 时,共用配置目录的 headless 进程会直接退出
(「已经有一个实例在跑」),转换就静默失败了。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

from app.core.child_process import run_logged

logger = logging.getLogger(__name__)

#: 老格式先转成哪种新格式再解析。
LEGACY_UPGRADES = {".doc": "docx", ".ppt": "pptx", ".xls": "xlsx"}
CONVERT_TIMEOUT_SECONDS = 180


def _candidates() -> list[str]:
    """PATH 里的,加上各平台默认安装位置 —— 桌面应用从 Dock / 开始菜单启动时 PATH 里往往没有它。"""
    found = [shutil.which(name) for name in ("soffice", "libreoffice")]
    if sys.platform == "darwin":
        found.append("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    elif os.name == "nt":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            if root:
                found.append(str(Path(root) / "LibreOffice" / "program" / "soffice.exe"))
    else:
        found += ["/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice", "/opt/libreoffice/program/soffice"]
    return [one for one in found if one]


def find_soffice() -> str | None:
    return next((one for one in _candidates() if Path(one).is_file()), None)


def convert(source: Path, target_format: str, out_dir: Path) -> Path | None:
    """转成 `target_format`(pdf / docx / pptx / xlsx),交回转出来的文件;没装或转失败回 None(失败记日志)。"""
    soffice = find_soffice()
    if soffice is None:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mosael-lo-profile-") as profile:
        try:
            result = run_logged(
                [soffice, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless", "--norestore",
                 "--convert-to", target_format, "--outdir", str(out_dir), str(source)],
                capture_output=True, text=True, timeout=CONVERT_TIMEOUT_SECONDS, what="LibreOffice 转换",
            )
        except Exception:  # noqa: BLE001 —— 超时、起不来:都是「这一次转不了」
            logger.warning("LibreOffice 转换 %s 失败", source.name, exc_info=True)
            return None
    target = out_dir / f"{source.stem}.{target_format}"
    if result.returncode != 0 or not target.is_file():
        logger.warning("LibreOffice 没转出 %s:%s", target.name, (result.stderr or "")[-300:])
        return None
    return target
