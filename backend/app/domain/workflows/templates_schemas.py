"""整片生成模板里,对话节点要交回的结构化产物的 JSON Schema:主旨、脚本、视觉圣经、分镜、场景设计。

对话节点按它出结构化结果;布景执行器(executors/scenes)也借场景设计那一份。

由 templates.py 统一重新导出;调用方照旧从 templates 取。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows.templates_models import VideoPlan


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _creative_brief_schema() -> dict[str, Any]:
    fields = {
        "title": {"type": "string", "description": "准确、有记忆点且不过度承诺的视频标题"},
        "core_thesis": {"type": "string", "description": "全片唯一核心主旨，一句话可复述"},
        "audience_takeaway": {"type": "string", "description": "观众看完应理解、感受或采取的行动"},
        "opening_hook": {"type": "string", "description": "前五秒建立问题和观看理由的钩子"},
        "narrative_arc": {"type": "string", "description": "开场、展开、转折、收束的因果弧线"},
        "visual_concept": {"type": "string", "description": "贯穿全片的视觉母题与场景逻辑"},
        "tone": {"type": "string"},
        "factual_boundaries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "不得凭空断言、需要用户复核的事实边界",
        },
    }
    return _object(fields, list(fields))


def _narrative_script_schema() -> dict[str, Any]:
    beat_fields = {
        "beat_number": {"type": "integer", "minimum": 1},
        "start_seconds": {"type": "number", "minimum": 0},
        "end_seconds": {"type": "number", "exclusiveMinimum": 0},
        "objective": {"type": "string", "description": "这一段对主旨推进的唯一任务"},
        "narration": {"type": "string", "description": "该时间段的完整口播或对白"},
    }
    fields = {
        "opening_hook": {"type": "string"},
        "narrative_arc": {"type": "string"},
        "full_narration": {"type": "string"},
        "beats": {"type": "array", "minItems": 1, "items": _object(beat_fields, list(beat_fields))},
    }
    return _object(fields, list(fields))


#: 白模里给人物上的颜色。视觉圣经给每个角色分一个,布景照着上色,关键帧提示词照着说"红色人偶是谁"。
BLOCKOUT_COLORS = ["#d9534f", "#4a7fd6", "#5cb85c", "#e0a030"]


def _visual_bible_schema() -> dict[str, Any]:
    character = {
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,30}$", "description": "英文小写短 id,如 hero"},
        "name": {"type": "string"},
        "role": {"type": "string", "description": "在故事里是谁"},
        "appearance": {
            "type": "string",
            "description": "英文,交给图像模型画三视图:年龄、脸型发型、服装与配色、体型与身高、标志性道具",
        },
        "height_m": {"type": "number", "minimum": 0.5, "maximum": 2.5},
        "blockout_color": {"type": "string", "enum": BLOCKOUT_COLORS, "description": "白模里这个人偶的颜色,每个角色不同"},
    }
    location = {
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,30}$"},
        "name": {"type": "string"},
        "description": {"type": "string", "description": "英文,交给图像模型画场景设定图:空间、时代、材质、关键陈设、光源"},
        "width_m": {"type": "number", "minimum": 2, "maximum": 60},
        "depth_m": {"type": "number", "minimum": 2, "maximum": 60},
        "height_m": {"type": "number", "minimum": 2, "maximum": 20},
    }
    fields = {
        "subject_bible": {"type": "string", "description": "人物或主体跨镜头保持一致的外观与行为"},
        "environment_bible": {"type": "string", "description": "空间、时代、材质与关键道具约束"},
        "camera_language": {"type": "string", "description": "景别、焦段、机位与运镜的统一语法"},
        "lighting_plan": {"type": "string"},
        "color_palette": {"type": "string"},
        "continuity_rules": {"type": "array", "items": {"type": "string"}},
        "global_negative_prompt": {"type": "string"},
        "characters": {
            "type": "array", "maxItems": 4, "items": _object(character, list(character)),
            "description": "出镜的角色(最多 4 个);纯物件/风景的片子可以为空",
        },
        "locations": {
            "type": "array", "maxItems": 3, "items": _object(location, list(location)),
            "description": "全片用到的场景(最多 3 个)",
        },
        "style_prompt": {"type": "string", "description": "英文一句话的全片画风,每张图、每段视频都会带上"},
        "blockout_legend": {
            "type": "string",
            "description": "英文,说明白模里各颜色人偶分别是谁,如 'red mannequin = Lin (class president), blue mannequin = Kai'",
        },
    }
    return _object(fields, list(fields))


SHOT_SIZES = ["extreme wide", "wide", "full", "medium", "medium close-up", "close-up", "extreme close-up"]

CAMERA_ANGLES = ["eye level", "high angle", "low angle", "overhead", "dutch angle"]

CAMERA_MOVES = ["static", "dolly in", "dolly out", "pan", "tilt", "tracking", "orbit", "crane up", "crane down"]


def _shot_schema(plan: VideoPlan) -> dict[str, Any]:
    clip = plan.clip_seconds
    fields: dict[str, Any] = {
        "shot_number": {"type": "integer", "minimum": 1},
        "start_seconds": {"type": "number", "minimum": 0},
        "end_seconds": {"type": "number", "exclusiveMinimum": 0},
        "duration_seconds": {"type": "number", "minimum": clip, "maximum": clip},
        "story_beat": {"type": "string", "description": "该镜头推进叙事的唯一任务"},
        "narration": {
            "type": "string",
            "description": f"该时间段的口播或对白，念出来不超过 {clip} 秒；无则写空字符串",
        },
        "location_id": {"type": "string", "description": "视觉圣经里的场景 id"},
        "characters": {"type": "array", "items": {"type": "string"}, "description": "这一镜出镜的角色 id"},
        "blocking": {"type": "string", "description": "人物站位与走位:谁在哪、朝向哪、从哪走到哪(米为单位的相对位置)"},
        "shot_size": {"type": "string", "enum": SHOT_SIZES},
        "camera_angle": {"type": "string", "enum": CAMERA_ANGLES},
        "lens_mm": {"type": "integer", "minimum": 14, "maximum": 200, "description": "等效全画幅焦段"},
        "camera_movement": {"type": "string", "enum": CAMERA_MOVES},
        "camera_path": {"type": "string", "description": "机位从哪里开始、沿什么路径、到哪里结束,起止构图各是什么"},
        "subject_action": {"type": "string", "description": f"主体在 {clip} 秒内可完成的动作节拍"},
        "lighting": {"type": "string"},
        "sound_design": {"type": "string", "description": "环境声、拟音、音乐节拍与静默点"},
        "transition_in": {"type": "string"},
        "transition_out": {"type": "string"},
        "continuity_notes": {"type": "string", "description": "人物、服装、空间、光向和运动连续性"},
        "reference_mode": {
            "type": "string", "enum": plan.modes,
            "description": "这一镜用哪条路出片:keyframes = 先按白模机位画首帧(需要时加尾帧)再生成视频,构图最稳;"
                           "references = 直接把角色三视图、场景设定图和白模运镜视频交给视频模型,适合复杂运镜",
        },
        "first_frame_prompt": {
            "type": "string",
            "description": "英文,这一镜第一帧画面的完整描述(人物、动作、表情、环境、光线、画风),交给图像模型画首帧",
        },
        "generation_prompt": {
            "type": "string",
            "description": f"英文,交给视频模型:主体动作节拍(须能在 {clip} 秒内完成)、表演、环境变化、光影;"
                           "不要写机位参数(会从白模自动补上),不要要求字幕、UI、Logo 或水印",
        },
        "negative_prompt": {"type": "string"},
    }
    if plan.last_frame:
        fields["last_frame_prompt"] = {
            "type": "string",
            "description": "英文,这一镜最后一帧的完整描述;只在结束构图必须精确(大幅运镜、落版、衔接下一镜)时写,否则写空字符串",
        }
    return _object(fields, list(fields))


#: 分镜**最多**能有几镜。这是 schema 上的硬天花板,不是用户那个数 —— 两者分工不同:
#:
#: 用户在 `start.max_shots` 里填的是"我这次想要几镜",走提示词,模型可以据此把成片缩短;
#: 这里是"再怎么样也不能超过"。每一镜都是一次付费的视频生成,而跑之前用户看不到账单 ——
#: 模型一次给出四十镜的后果是四十次扣费,那不该由一句提示词兜着。
#:
#: 故意比默认值宽出一截:两者贴太近的话,模型多给一镜就是整条流程作废(schema 不匹配当场失败),
#: 而那正是我们要避免的失败方式。
MAX_SHOTS_CEILING = 24


def _storyboard_schema(plan: VideoPlan) -> dict[str, Any]:
    fields = {
        "total_duration_seconds": {"type": "number", "minimum": plan.clip_seconds},
        "timeline_summary": {"type": "string"},
        "continuity_bible": {"type": "string", "description": "所有镜头共享的人物、场景、风格连续性约束"},
        "shots": {"type": "array", "minItems": 1, "maxItems": MAX_SHOTS_CEILING, "items": _shot_schema(plan)},
    }
    return _object(fields, list(fields))


#: 布景用得到的物体种类 —— SceneObject.kind 里除了导入模型(没有文件)和灯之外的那些。
#: `group` 是**收纳**用的:八个布景台摊平就是七十多条重名的列表(「出租屋卧室」出现八次),
#: 谁也分不出哪个是哪个。每台一个组之后,列表是八行。
#: `model` 是**导入的模型**(通常在 Blender 里建好再收进工作区):基本体拼不出来的产品、道具、
#: 设备。它要配一个 model_id,而布景师是从上游「可用的 3D 道具」节点给的清单里拿到那个 id 的 ——
#: 没有那份清单时清单为空,布景师就只用基本体(提示词里说了)。
SET_KINDS = ["group", "room", "box", "cylinder", "sphere", "plane", "stairs", "table", "figure",
             "model", "camera"]


def _set_design_schema() -> dict[str, Any]:
    """布景的形状 = 3D 场景的数据格式(SceneContent),只收这条流程用得到的那部分。

    所有字段都列成必填(结构化输出的严格模式要求如此);用不上的给中性值 —— 非相机的 target/fov
    给 [0,1,0] / 45,不动的物体 track 给空数组,关键帧里相机的 rotation、物体的 target/fov 写了也会被摘掉。
    """
    vec3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
    #: 相机和物体共用一种关键帧(scenes.types.Keyframe):相机用 target / fov,物体(跑动的人)用 rotation。
    #: 严格模式要求每一格都在,用不上的那几格由 executors/scenes._canonical 按物体种类摘掉。
    keyframe = {"time": {"type": "number", "minimum": 0}, "position": vec3, "target": vec3,
                "fov": {"type": "number", "minimum": 10, "maximum": 120}, "rotation": vec3}
    parameters = {
        "width": {"type": "number", "minimum": 0.01}, "height": {"type": "number", "minimum": 0.01},
        "depth": {"type": "number", "minimum": 0.01}, "radius": {"type": "number", "minimum": 0.01},
        "steps": {"type": "integer", "minimum": 1, "maximum": 64},
    }
    obj = {
        "id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
        "name": {"type": "string"},
        "kind": {"type": "string", "enum": SET_KINDS},
        #: 归到哪个布景台的组下面;顶层物体(组自己)写空字符串。严格模式要求每一格都在,
        #: 所以用空串而不是 null 表示「没有父级」。
        "parent_id": {"type": "string"},
        "position": vec3, "rotation": vec3,
        #: 只有 kind="model" 用得上:上游道具清单里的那个 id。其余物体写空字符串
        #: (严格模式要求每一格都在)。
        "model_id": {"type": "string"},
        #: 只有 figure 用得上:它演的是资产库里哪个人物(ADR 0029 §3)。没有就写空字符串。
        "entity_id": {"type": "string"},
        "parameters": _object(parameters, list(parameters)),
        "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
        "target": vec3, "fov": {"type": "number", "minimum": 10, "maximum": 120},
        "track": {"type": "array", "items": _object(keyframe, list(keyframe))},
    }
    shot = {
        "id": {"type": "string"}, "name": {"type": "string"},
        "duration": {"type": "number", "minimum": 0.1, "maximum": 120},
        "aspect": {"type": "string", "enum": ["16:9", "9:16", "1:1"]},
        "easing": {"type": "string", "enum": ["smooth", "linear"]},
        "camera_id": {"type": "string"},
    }
    lighting = {
        "preset": {"type": "string", "enum": ["custom"]},
        "azimuth": {"type": "number", "minimum": 0, "maximum": 359}, "elevation": {"type": "number", "minimum": 0, "maximum": 90},
        "intensity": {"type": "number", "minimum": 0, "maximum": 20},
        "temperature": {"type": "integer", "minimum": 1500, "maximum": 12000},
        "softness": {"type": "number", "minimum": 0, "maximum": 1},
    }
    fields = {
        "objects": {"type": "array", "maxItems": 480, "items": _object(obj, list(obj))},
        "shots": {"type": "array", "minItems": 1, "maxItems": 32, "items": _object(shot, list(shot))},
        "lighting": _object(lighting, list(lighting)),
        "background": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
        "ambient": {"type": "number", "minimum": 0, "maximum": 10},
    }
    return _object(fields, list(fields))
