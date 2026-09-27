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


#: 布景的结构化输出(严格模式)要求每一格都在,用不上的引用写空字符串(见 templates._set_design_schema);
#: 场景格式里它们是「没有就不写」。空字符串在这里就是「没有」—— 不是替它猜一个值。
_OPTIONAL_REFERENCES = ("parent_id", "model_id")


#: 关键帧上哪几格归谁用(scene_types.Keyframe):相机看 target / fov,物体看 rotation。严格模式要求每一格都在,
#: 用不上的那几格是填充值 —— 留着的话,人物关键帧的 target 会被当成「看向」校验(和位置重合就拒)。
_CAMERA_ONLY_KEYS = ("target", "fov")
_OBJECT_ONLY_KEYS = ("rotation",)


def _canonical(layout: dict[str, Any]) -> dict[str, Any]:
    """**只做规范化,不做猜测**:关键帧按时间排好序(LLM 常按叙述顺序写),摘掉这种物体用不上的关键帧字段;
    严格模式下写成空字符串的可选引用(父级、模型 id)当作没有。别的一概不改 —— 坐标错了就让校验说出来,替它修一个
    "看起来合理"的值,构图就悄悄变成了另一个镜头。"""
    objects = []
    for obj in layout.get("objects") or []:
        if isinstance(obj, dict) and isinstance(obj.get("track"), list):
            unused = _OBJECT_ONLY_KEYS if obj.get("kind") == "camera" else _CAMERA_ONLY_KEYS
            frames = [{key: value for key, value in frame.items() if key not in unused} if isinstance(frame, dict) else frame
                      for frame in obj["track"]]
            obj = {**obj, "track": sorted(frames, key=lambda frame: float(frame.get("time") or 0) if isinstance(frame, dict) else 0)}
        if isinstance(obj, dict):
            obj = {key: value for key, value in obj.items()
                   if not (key in _OPTIONAL_REFERENCES and isinstance(value, str) and not value.strip())}
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


#: 「按文字搭 3D 场景」最多几镜(每镜一个布景台、一台相机)、每镜几秒(运镜末档的时间)。
MAX_TEXT_SHOTS = 12
DEFAULT_TEXT_SHOTS = 6
DEFAULT_SHOT_SECONDS = 5
SHOT_ASPECTS = ("16:9", "9:16", "1:1")


@register("scene_from_text")
def scene_from_text(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """照一段剧本 / 描述搭**一个** 3D 白模场景:一个布景、人物按文字动起来(关键帧)、几台相机从不同机位拍这段动作。

    **不自己实现两样东西**:写布景的是 LLM 节点(`llm`,结构化输出),相机 / 运镜 / 打光的规矩和整片模板同一份
    (templates.single_set_rules 里引的 `_camera_rules`);建场景的是 `scene_create`。和整片模板不同的是布景:
    那边是分镜,每镜一个布景台;这里是一个地方里的一段事,只搭一个(见 single_set_rules 的说明)。
    """
    from app.domain.workflows.executors.ai import llm
    from app.domain.workflows.field_options import split_chat_model
    from app.domain.workflows.templates import _set_design_schema, single_set_rules

    text = str(config.get("text") or "").strip()
    if not text:
        raise WorkflowDomainError("wfErr_sceneTextMissing")
    try:
        shots = max(1, min(MAX_TEXT_SHOTS, int(config.get("max_shots") or DEFAULT_TEXT_SHOTS)))
        clip = max(1, min(30, int(config.get("shot_seconds") or DEFAULT_SHOT_SECONDS)))
    except (TypeError, ValueError):
        shots, clip = DEFAULT_TEXT_SHOTS, DEFAULT_SHOT_SECONDS
    aspect = str(config.get("aspect") or "16:9")
    if aspect not in SHOT_ASPECTS:
        aspect = "16:9"
    props = scene_props(db, scope, {"model_ids": ""})
    system = (
        "你是导演兼布景师、摄影助理。照下面这段文字搭**一个** 3D 白模场景:定下这个地方(大致的长宽高)和出场的人物"
        f"(身高、每人一个不同的白模颜色),把文字里的动作写成人物 {clip} 秒的关键帧,再用不超过 {shots} 台相机从不同"
        "机位拍这段动作(文字本身写了镜头的,照它的镜头来)。输出就是 3D 场景的数据格式,会被直接建成场景、渲出参考帧"
        "交给图像和视频模型 —— 它决定每一镜的构图。\n\n"
        + single_set_rules(clip, source="这段文字(没写明的尺寸、身高、光线按常识定)")
        + "只输出符合 JSON Schema 的对象。"
    )
    profile_id, model = split_chat_model(str(config.get("model") or ""))
    written = llm(db, scope, {
        "profile_id": profile_id or None,
        "model": model,
        "preset": "precise",
        "system": system,
        "prompt": f"文字:\n{text}\n\n可用的 3D 道具(kind=\"model\" 时 model_id 只能从这里选;尺寸是实测值):\n"
                  f"{props['catalog']}\n\n画幅:{aspect}。",
        "response_format": "json_schema",
        "json_schema_name": "blockout_scene",
        "json_schema": _set_design_schema(),
        "json_schema_strict": "true",
        "temperature": 0.2,
        "max_tokens": 16000,
    })
    name = str(config.get("name") or "").strip() or text.splitlines()[0].strip("# ")[:60] or scope.name
    built = scene_create(db, scope, {"name": name, "layout": written.get("json") or written.get("text")})
    return {"scene_id": built["scene_id"], "shot_ids": built["shot_ids"], "shot_count": built["shot_count"], "name": name}
