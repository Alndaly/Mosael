"""对话里附上的压缩包 / 文件夹(ADR 0059):解开、认一认,再交给已有的两条路。

- **里面有 `SKILL.md`** → 是技能包:走设置页导入的**同一份**暂存与审阅(skills.use_cases.stage_import),回暂存 id 和全文;
  对话里出一张「发现 N 个技能」的卡,人看过全文、点了才装。这里不另写一套校验。
- **不是技能包** → 图片一张张进素材库(和 📎 附图片同一条路,智能体用 analyze_asset 看);文本文件(按内容判,
  `is_text`)按包里的路径排好,**合订成一份 Markdown 文档**进素材库 —— 和附一份 .md 同一条路:后端本地解析,短的全文、
  长的目录放进上下文,智能体用 read_document 按段读。别的(二进制、太大、超出个数)不收,逐个列出来给人看,
  合订本末尾也写一句,模型知道少了什么。

解包只在 `mosael_formats.agent_skill` 一处(read_archive_files / clean_files):压缩炸弹、路径穿越、符号链接、
系统垃圾(`__MACOSX`、`.DS_Store`)和技能导入挡的是同一套。
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.db.models import Asset, User
from app.domain.agent.skills import use_cases as skill_use_cases
from app.domain.agent.skills.catalog import SkillDomainError
from app.domain.permissions import ensure_workspace_perm
from mosael_formats.agent_skill import (
    MAX_FILE_BYTES,
    MAX_SKILL_FILES,
    SkillError,
    clean_files,
    contains_skill,
    is_text,
    read_archive_files,
)

#: 一次最多合订多少个文本文件。和一个技能最多带的文件数同一个量级:再多的包(整个仓库)该让智能体自己去读,
#: 不是一口塞进对话。单个文本文件的上限就是技能里单个文件的上限(MAX_FILE_BYTES)。
MAX_BUNDLE_TEXT_FILES = MAX_SKILL_FILES
#: 一次最多收几张图。每张都是一个素材、一枚缩略图;一包几百张图的是素材库批量导入的活。
MAX_BUNDLE_IMAGES = 20

#: 跳过的原因(界面按它说人话)。
SKIP_UNSUPPORTED = "unsupported"
SKIP_TOO_LARGE = "too_large"
SKIP_TOO_MANY = "too_many"
#: 合订本末尾那一句,写给模型看的。
_SKIP_SAID = {
    SKIP_UNSUPPORTED: "不是文本也不是图片",
    SKIP_TOO_LARGE: f"超过 {MAX_FILE_BYTES // (1024 * 1024)}MB",
    SKIP_TOO_MANY: "超出一次能收的个数",
}

_LANGUAGE = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript",
    ".tsx": "tsx", ".jsx": "jsx", ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".md": "markdown", ".markdown": "markdown", ".html": "html", ".htm": "html", ".css": "css", ".sh": "bash",
    ".sql": "sql", ".xml": "xml", ".csv": "csv", ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby",
    ".swift": "swift", ".kt": "kotlin", ".c": "c", ".h": "c", ".cpp": "cpp", ".svg": "xml", ".srt": "srt",
}


def collect(*, archive: bytes | None = None, files: dict[str, bytes] | None = None) -> dict[str, bytes]:
    """压缩包或一堆文件 → 规整过路径、丢掉系统垃圾的文件。不合格的(越界路径、符号链接、炸弹)抛 SkillDomainError。"""
    try:
        return clean_files(read_archive_files(archive) if archive is not None else (files or {}))
    except SkillError as exc:
        raise SkillDomainError.relay(exc) from exc


def _is_image(path: str) -> bool:
    mime = mimetypes.guess_type(path)[0] or ""
    #: SVG 是文字(XML),按文本合订:素材库不给它做缩略图,模型读它的源码也比看一张图有用。
    return mime.startswith("image/") and mime != "image/svg+xml"


def _fence(content: str) -> str:
    """比内容里最长的一串反引号再长一截的围栏:文件里本身有 ``` 也不会把合订本截断。"""
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


def _stem(source_name: str) -> str:
    name = PurePosixPath(source_name.strip() or "attachment").name
    return re.sub(r"\.zip$", "", name, flags=re.IGNORECASE) or "attachment"


def compile_text(source_name: str, texts: dict[str, str], skipped: list[dict[str, str]]) -> str:
    """文本文件 → 一份 Markdown 合订本:开头一张目录,每个文件一节(标题是包里的路径,内容原样放在围栏里)。"""
    lines = [f"# {source_name}", "", f"从「{source_name}」解开的 {len(texts)} 个文本文件,每个文件一节,标题是它在包里的路径。", ""]
    lines += [f"- {path}" for path in texts]
    for path, content in texts.items():
        fence = _fence(content)
        language = _LANGUAGE.get(PurePosixPath(path).suffix.lower(), "")
        lines += ["", f"## {path}", "", f"{fence}{language}", content.rstrip("\n"), fence]
    if skipped:
        lines += ["", "## 没有收进来的文件", ""]
        lines += [f"- {one['path']}({_SKIP_SAID.get(one['reason'], one['reason'])})" for one in skipped]
    return "\n".join(lines) + "\n"


def unpack(db: Session, user: User, workspace_id: str, *, source_name: str, archive: bytes | None = None,
           files: dict[str, bytes] | None = None) -> dict:
    """对话里附上的一个压缩包 / 文件夹 → `{source_name, skill_import, assets, skipped}`。

    技能包:`skill_import` 是暂存好的导入(和设置页导入回的是同一个东西),什么都还没装。
    别的:`assets` 是进了素材库的图片和那份合订本,`skipped` 是没收的文件和原因。
    """
    ensure_workspace_perm(db, user, workspace_id, "upload")
    clean = collect(archive=archive, files=files)
    if contains_skill(clean):
        preview = skill_use_cases.stage_import(db, user, workspace_id, files=clean, source_name=source_name)
        return {"source_name": source_name, "skill_import": preview, "assets": [], "skipped": []}

    from app.domain.assets.importer import import_binary_asset

    images: dict[str, bytes] = {}
    texts: dict[str, str] = {}
    skipped: list[dict[str, str]] = []
    for path, data in sorted(clean.items()):
        if _is_image(path):
            if len(images) >= MAX_BUNDLE_IMAGES:
                skipped.append({"path": path, "reason": SKIP_TOO_MANY})
            else:
                images[path] = data
        elif not is_text(data):
            skipped.append({"path": path, "reason": SKIP_UNSUPPORTED})
        elif len(data) > MAX_FILE_BYTES:
            skipped.append({"path": path, "reason": SKIP_TOO_LARGE})
        elif len(texts) >= MAX_BUNDLE_TEXT_FILES:
            skipped.append({"path": path, "reason": SKIP_TOO_MANY})
        else:
            texts[path] = data.decode("utf-8")

    assets: list[Asset] = []
    for path, data in images.items():
        assets.append(import_binary_asset(db, workspace_id=workspace_id, project_id=None, data=data,
                                          original=PurePosixPath(path).name, name=path))
    if texts:
        stem = _stem(source_name)
        document = compile_text(source_name, texts, skipped).encode("utf-8")
        assets.append(import_binary_asset(db, workspace_id=workspace_id, project_id=None, data=document,
                                          original=f"{stem}.md", content_type="text/markdown", name=f"{stem}.md"))
    return {"source_name": source_name, "skill_import": None, "assets": assets, "skipped": skipped}


__all__ = [
    "MAX_BUNDLE_IMAGES",
    "MAX_BUNDLE_TEXT_FILES",
    "SKIP_TOO_LARGE",
    "SKIP_TOO_MANY",
    "SKIP_UNSUPPORTED",
    "collect",
    "compile_text",
    "unpack",
]
