"""3D 白模:搭场景、渲参考。

两个节点让自动流程用上 3D 白模 —— 此前它只在工作台里能手动用,而整片生成的每一镜只有一段
文字提示词:构图、机位、人物站位全靠模型猜,几镜之间谁也对不上谁。

- `scene_create`:把一份布景(物体、机位轨迹、镜头、打光 —— 就是 SceneContent 的形状)建成
  一个真正的 3D 场景。它出现在「3D 场景」列表里,用户可以打开、在工作台里调。
- `scene_render`:从某个镜头渲出白模首帧、尾帧和运镜视频,外加一句从机位轨迹**算出来**的镜头
  语言。实现在 domain/scenes.render_shot_references —— 接口和智能体工具用的是同一份。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.models import Scene3D
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import RunScope, register
from app.domain.workflows.executors.common import id_list


def _layout(value: Any) -> dict[str, Any]:
    """布景可以是上游 LLM 的结构化输出(dict),也可以是一段 JSON 文本。"""
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        raise WorkflowDomainError("wfErr_sceneLayoutMissing")
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise WorkflowDomainError("wfErr_sceneLayoutInvalid", params={"reason": str(exc)}) from exc
    if not isinstance(parsed, dict):
        raise WorkflowDomainError("wfErr_sceneLayoutInvalid", params={"reason": "not an object"})
    return parsed


def _canonical(layout: dict[str, Any]) -> dict[str, Any]:
    """**只做规范化,不做猜测**:关键帧按时间排好序(LLM 常按叙述顺序写)。别的一概不改 ——
    坐标错了就让校验说出来,替它修一个"看起来合理"的值,构图就悄悄变成了另一个镜头。"""
    objects = []
    for obj in layout.get("objects") or []:
        if isinstance(obj, dict) and isinstance(obj.get("track"), list):
            obj = {**obj, "track": sorted(obj["track"], key=lambda frame: float(frame.get("time") or 0))}
        objects.append(obj)
    return {**layout, "objects": objects}


@register("scene_props")
def scene_props(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """交给布景师的道具清单:这个工作区里哪些模型能摆,各自多大。

    **尺寸是量出来的,不是填的**:读一遍 GLB 取包围盒。布景师要靠它决定摆在哪、和人偶比多高 ——
    而"这个模型多大"只有文件自己知道,让人在节点里手填等于请他抄一遍,抄错了没人发现。

    读不了的那几份(压缩网格、超预算、文件不在)**不进清单**,并在 `catalog` 里说一句 ——
    列出来只会让布景师摆上一件渲不出来的东西,而那时画面里是个空位。
    """
    import numpy as np

    from app.db.models import Scene3DModel
    from app.domain.scene_render.model_mesh import read_model, UnsupportedModel
    from app.domain.scenes import list_models, model_file

    # 逗号串(选择器存的)或列表(整串引用上游输出)都合法 —— 和素材 id 同一份解析。
    wanted = id_list(config.get("model_ids"))
    available = {model.id: model for model in list_models(db, scope.workspace_id)}
    chosen: list[Scene3DModel] = ([available[one] for one in wanted if one in available]
                                  if wanted else list(available.values()))

    lines: list[str] = []
    notes: list[str] = []
    usable: list[str] = []
    for model in chosen:
        try:
            parts = read_model(model_file(model))
        except (UnsupportedModel, OSError, ValueError) as exc:
            notes.append(f"(「{model.name}」这次用不了:{exc})")
            continue
        points = np.concatenate([part.vertices for part in parts])
        size = points.max(axis=0) - points.min(axis=0)
        lines.append(f"- {model.id} · {model.name} · 宽 {size[0]:.2f} × 高 {size[1]:.2f} × 深 {size[2]:.2f} 米")
        usable.append(model.id)

    missing = [one for one in wanted if one not in available]
    if missing:
        notes.append(f"(指定的 {len(missing)} 份模型不在这个工作区里,已跳过)")
    catalog = "\n".join(lines) if lines else "(没有可用的 3D 道具,这次只用基本体搭布景。)"
    if notes:
        catalog = catalog + "\n" + "\n".join(notes)
    return {"catalog": catalog, "model_ids": usable, "count": len(usable)}


@register("scene_create")
def scene_create(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.scene_types import SceneContent
    from app.domain.scenes import SceneDomainError, create_scene

    name = str(config.get("name") or "").strip() or scope.name
    try:
        content = SceneContent.model_validate(_canonical(_layout(config.get("layout"))))
    except ValidationError as exc:
        #: 前三条就够定位:布景是 LLM 写的,错一般错在同一类地方(坐标、镜头指向的机位)。
        reasons = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()[:3]
        )
        raise WorkflowDomainError("wfErr_sceneLayoutInvalid", params={"reason": reasons}) from exc
    try:
        scene = create_scene(db, scope.workspace_id, name[:160], content)
    except SceneDomainError as exc:
        raise WorkflowDomainError("wfErr_sceneLayoutInvalid", params={"reason": str(exc)}) from exc
    return {
        "scene_id": scene.id,
        "shot_ids": [shot.id for shot in content.shots],
        "shot_count": len(content.shots),
    }


@register("scene_render")
def scene_render(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.scenes import SceneDomainError, render_shot_references

    scene_id = str(config.get("scene_id") or "").strip()
    scene = db.get(Scene3D, scene_id) if scene_id else None
    if scene is None or scene.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_sceneNotInWorkspace")
    try:
        return render_shot_references(
            db, scene, str(config.get("shot_id") or "").strip(),
            render=str(config.get("render") or "stills").strip(),
            project_id=str(config.get("project_id") or "").strip() or None,
        )
    except SceneDomainError as exc:
        raise WorkflowDomainError("wfErr_sceneRenderFailed", params={"reason": str(exc)}) from exc
