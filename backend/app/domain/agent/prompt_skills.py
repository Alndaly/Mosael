from __future__ import annotations

import re
from typing import Any

from app.core.config import settings

"""
Prompt skills(Claude Code 同构的 skill 约定):每个技能是
`~/.mibu-new/skills/<id>/SKILL.md`,YAML frontmatter 带 name/description,
正文是给智能体的操作手册。内置技能首次访问时落盘(不覆盖用户改动),
用户可以直接编辑文件或新建自己的技能目录。

智能体侧按需加载:系统提示词只带 id+description 索引,命中任务时通过
MCP 的 load_skill 拉取正文 —— 与 Claude Code 的 skill 惰性加载模型一致。
"""

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

BUILTIN_SKILLS: dict[str, str] = {
    "transcript-rough-cut": """---
name: 逐字稿粗剪
description: 基于逐字稿删除静音、口癖与废话段,一次性提交粗剪确认卡。
---

# 逐字稿粗剪

目标:把口播素材里的静音、语气词(嗯/啊/就是)与重复表述剪掉,保留自然语流。

流程:
1. `list_assets` 找到目标口播素材;若还没有逐字稿,提示用户先在剪辑页转写。
2. `inspect_sequence` 拿到时间线现状,确认素材对应的 clip 与 src 区间。
3. 读取逐字稿(素材的 transcript),收集要删除的 token 区间:
   - 相邻 token 间隔 ≥0.8s 视为静音段;
   - 单字语气词(嗯、啊、呃)且时长 <0.5s;
   - 用户点名要删的句子。
4. 把相邻/重叠区间合并,换算成该 clip 的源区间列表(src_start/src_end)。
5. 用 `edit_timeline` 提交 cut_clip_ranges,一张确认卡装下全部区间,并在
   摘要里写明"删除 N 段共 X 秒"。
6. `get_confirmation` 轮询结果,完成后汇报删了多少段、成片预计时长。

注意:删除量超过素材时长 40% 时先向用户复述清单再提交。
""",
    "asset-organize": """---
name: 素材整理与打标
description: 批量理解素材内容,按主题/景别/可用性打标签,方便检索。
---

# 素材整理与打标

目标:让素材库可检索——每个素材有主题、景别、质量标签。

流程:
1. `list_assets` 列出工作区素材(注意 kind 与时长)。
2. 对图片/视频用 `analyze_asset` 逐个理解画面(主体、场景、运镜、光线)。
3. 归纳出 3-6 个复用标签(如 海边/人物/空镜/夜景/可用/废片)。
4. 用 `update_asset_tags` 直接写入标签(元数据操作,随时可改,不走确认卡);
   注意该工具是整体替换,合并已有标签时先读当前 tags。
5. 汇报:每个标签下有哪些素材,哪些素材建议弃用。

注意:标签用中文短词,不超过 6 个字;同义标签合并(海面→海边)。
""",
    "highlight-reel": """---
name: 高光混剪
description: 从长素材中挑选高光片段,按节奏拼接成短片时间线。
---

# 高光混剪

目标:从一段或多段长素材里挑出高光,拼成 30-60 秒的节奏短片。

流程:
1. `list_assets` + `analyze_asset` 了解素材内容;有逐字稿的优先按台词挑点。
2. 与用户确认:目标时长、节奏(快切/舒缓)、是否要背景音乐轨。
3. `inspect_sequence` 确认目标时间线(通常新建或清空一条)。
4. 规划片段清单:每段给出 asset、src_in/src_out、目标顺序,单段 2-6 秒,
   开头放最强的画面。
5. 用 `edit_timeline` 按顺序 insert_clip;背景音乐放 A1 轨并对齐总长。
6. 提交确认卡后汇报片段清单与总时长,提醒用户可在剪辑页微调转场与调色。

注意:一张确认卡对应一个连贯意图;插入超过 10 个片段时分两批提交。
""",
    "export-delivery": """---
name: 导出交付
description: 检查时间线完整性后触发导出,跟踪渲染任务直到产出成片。
---

# 导出交付

目标:把当前时间线安全地渲染成成片。

流程:
1. `inspect_sequence` 检查:有没有空轨道、片段间意外空隙、静音轨。
2. 发现问题先列出来问用户是否处理,不要擅自修改。
3. `render_sequence` 提交导出确认卡,摘要写明分辨率/fps/预计时长。
4. `get_confirmation` 轮询;导出任务开始后可用 job 状态汇报进度。
5. 完成后告诉用户成片已进入素材库(名称含 Export)。

注意:导出失败时把错误原文给用户,并给出最可能的原因(缺素材文件/编码参数)。
""",
}


def ensure_builtin_skills() -> None:
    """内置技能落盘(只在文件不存在时写入,用户的修改永远优先)。"""
    for skill_id, content in BUILTIN_SKILLS.items():
        path = settings.skills_dir / skill_id / "SKILL.md"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, text[match.end() :]


def list_prompt_skills() -> list[dict[str, Any]]:
    ensure_builtin_skills()
    skills: list[dict[str, Any]] = []
    if not settings.skills_dir.is_dir():
        return skills
    for entry in sorted(settings.skills_dir.iterdir()):
        path = entry / "SKILL.md"
        if not entry.is_dir() or not path.is_file():
            continue
        meta, _body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        skills.append(
            {
                "id": entry.name,
                "name": meta.get("name", entry.name),
                "description": meta.get("description", ""),
                "source": "builtin" if entry.name in BUILTIN_SKILLS else "user",
            }
        )
    return skills


def load_prompt_skill(skill_id: str) -> dict[str, Any] | None:
    ensure_builtin_skills()
    # 目录名即 id;拒绝路径穿越。
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", skill_id):
        return None
    path = settings.skills_dir / skill_id / "SKILL.md"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    return {
        "id": skill_id,
        "name": meta.get("name", skill_id),
        "description": meta.get("description", ""),
        "source": "builtin" if skill_id in BUILTIN_SKILLS else "user",
        "body": body.strip(),
    }


def skills_index_for_prompt() -> str:
    """系统提示词里的技能索引(一行一个,正文按需 load_skill)。"""
    lines = [f"- {skill['id']}: {skill['name']} — {skill['description']}" for skill in list_prompt_skills()]
    return "\n".join(lines)
