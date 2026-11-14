"""角色三视图、场景设计稿怎么画:整片模板与「连续剧 · 系列设定」共用同一份提示词 —— 系列里先画好、存进库的那张,
整片到库里认出来就直接用。此前它住在整片模板模块里(2026-11-14 审计 C3)。
"""

from __future__ import annotations


#: 角色三视图、场景设定图怎么画(循环里每一项有 name / appearance 或 description,画风在 `input.style`)。
#: 整片和系列设定(templates/series)画的是同一种图 —— 系列里先画好的那张,整片到库里认出来就直接用。
TURNAROUND_PROMPT = (
    "Character turnaround reference sheet for {{loop.item.name}}: {{loop.item.appearance}}. "
    "Three full-body views of the same character side by side — front, side profile, back — "
    "identical outfit and proportions, relaxed A-pose, plain white background, soft even studio "
    "light, no text, no labels, no borders. {{input.style}}"
)
#: 场景存进库的是一张**设计稿**(和人物三视图对应,ADR 0097 修订四):一张图四格画同一个地方,出图模型拿它学建筑、陈设、
#: 光线,却没有一个现成的构图可以照搬。此前是一张全景设定图(「Establishing concept art……Wide view」):交给画关键帧
#: 的模型,FLUX.3 / Qwen-Image / MOSS / krea2 都照着它的构图画,白模的机位压不过它。
LOCATION_DESIGN_SHEET_PROMPT = (
    "Location design sheet of {{loop.item.name}}: {{loop.item.description}} "
    "A 2x2 grid of four separate panels with thin white gutters on a plain light background: top-left a high bird's-eye "
    "view showing the whole layout of the place; top-right an eye-level view looking the opposite way; bottom-left a "
    "close-up of the walls, doors, windows and fixtures; bottom-right a close-up of the floor or ground and small props. "
    "The same place, materials, lighting and weather in every panel. No people, no text. {{input.style}}"
)
