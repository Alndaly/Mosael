"""内置模板「从主题到完整视频」的图:主题 → 主旨 → 脚本 / 视觉圣经 → 三视图与场景设定图 → 分镜 → 3D 白模布景 →
逐镜出首帧、出视频 → 上时间线 → 口播字幕 → 导出。

连同它给布景那一步用的提示词规则(blockout_rules / single_set_rules)。

由 templates.py 统一重新导出;调用方照旧从 templates 取。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.domain.workflows import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates_models import FRAME_ASPECTS, ModelChoice, _capabilities, _image_plan, _video_plan
from app.domain.workflows.templates_schemas import (
    _creative_brief_schema,
    _narrative_script_schema,
    _set_design_schema,
    _storyboard_schema,
    _visual_bible_schema,
)


FULL_VIDEO_GENERATION = "full_video_generation"


#: 两种搭法共用的几段规矩:坐标约定、真道具、相机与运镜 / 镜头 / 打光。**一份文字两处读** —— 改了焦段换算的那一份
#: 和没改的那一份会搭出两种机位。
_COORDINATES = "坐标约定：单位米，Y 朝上，地面 y=0；所有坐标都写**世界坐标**。\n"

_PROP_RULE = """- **能用真道具就别用方块拼。** 下面那份「可用的 3D 道具」清单里的东西是已经建好的真实模型:
  kind="model",model_id 写清单里那个 id,name 写道具名,position/rotation 照常摆。清单里给了
  每件道具实测的长宽高,按它和 figure(人)的比例摆,不要再用 parameters 去"设定"它的尺寸
  (模型自带尺寸,parameters 对它无效)。清单为空就全用基本体。
"""


def _camera_rules(clip: int, *, source: str) -> str:
    return f"""每镜一台相机：kind="camera",id="cam-<n>";position 是起始机位,target 是起始看向点(一般是主体的胸口
或眼睛高度 1.3~1.6 米),fov 是竖直视角,由焦段换算:fov = 2*atan(12/焦段毫米)(14mm≈81°,24mm≈53°,
35mm≈38°,50mm≈27°,85mm≈16°,135mm≈10°)。机位高度按机位角度:平视 1.5~1.7 米,俯拍 2.5~4 米,
仰拍 0.3~0.8 米。相机必须在房间内、不穿过任何物体,和主体的距离要让景别成立(特写约 0.6~1 米,
中景 1.5~2.5 米,全景 3~5 米)。
运镜写在相机的 track 上：static 不写 track;其余至少两档 {{time:0,...}} 和 {{time:{clip},...}}
(position/target/fov 三项都写),推 = 沿视线靠近主体,拉 = 远离,摇 = 机位不动只转 target,
跟 = 机位和 target 一起平移,环绕 = 绕主体转(可加中间一档),升降 = 机位上下移动。

shots:每镜一条 {{id:"shot-<n>", name:"镜头 <n>", duration:{clip}, aspect:画幅, easing:"smooth",
camera_id:"cam-<n>"}}。lighting 按{source}的光线方案给方位角(0=相机默认一侧,90=右侧,180=逆光)、
高度角、强度(2~5)、色温和软硬;preset 写 "custom"。background 写 "#20242c",ambient 写 1.5。
"""


def blockout_rules(clip: int, *, source: str) -> str:
    """搭 3D 白模布景的规矩:坐标、每镜一个布景台、人偶、道具、每镜一台相机和它的运镜、镜头与打光。

    整片模板的「设计 3D 白模布景与机位」和画板上的「按文字搭 3D 场景」(executors/scenes.scene_from_text)读的是
    这同一份 —— 两处各写一份的话,改了台距算法的那一份和没改的那一份会搭出两种白模。`source` 是尺寸、身高、颜色、
    光线从哪来(「视觉圣经」/「这段文字」),`clip` 是每镜几秒(运镜的末档时间)。
    """
    return f"""{_COORDINATES}
**台距 D 由布景尺寸算出来,不是固定值。** 取{source}里最大的那个场景的 width_m 与 depth_m 中较大的
那个,加 8 米;若不足 12 米就按 12 米。第 n 镜(shot_number = n)的布景台整体放在 x = n*D 附近,
台内每一个物体和这一镜相机的 position / target 都要把 x 加上 n*D。
**不要用固定的 40 米**:三四米宽的卧室按 40 米排开,台与台之间会空出三十多米,整个白模散成一串
看不清的小点;而六十米的大场景在 40 米台距下会直接和隔壁穿模。

**每个布景台先出一个组。** kind="group",id="bay-<n>",name="镜头 <n> · <这一镜的场景名>",
position 写 [0,0,0],parent_id 写空字符串;这一台里的**每一个**物体(room、陈设、figure、相机)
都把 parent_id 写成 "bay-<n>"。组只为收纳,它在原点,所以**不改变任何坐标** —— 上面那条"都写世界
坐标"照旧成立。没有组的话,八个台摊平就是七十多条重名的平铺列表。

每个布景台：
- 一个 room(parameters.width/depth/height 取{source}里这个场景的尺寸，position 为 [n*D,0,0]，
  门洞在前后墙正中；没有天花板)。室外场景用一块 plane 当地面、几块 box 当远景体块。
- 关键陈设用 box / cylinder / table / stairs 概括(桌椅、柜子、门、树……)，尺寸按真实比例。
- 这一镜出镜的每个角色一个 figure:parameters.height = 角色身高,width 0.4~0.5(肩宽),depth 0.22~0.28;
  color 用{source}里这个角色的 blockout_color;position 按分镜的站位;rotation[1] 是朝向(度)。
  id 写成 "<角色id>-<n>"。
{_PROP_RULE}- 物体的 target 写 [0,1,0]、fov 写 45、track 写空数组 —— 只有相机用得上它们;
  非 model 的物体 model_id 写空字符串。

{_camera_rules(clip, source=source)}"""


def single_set_rules(clip: int, *, source: str) -> str:
    """搭**一个**布景的规矩:画板上的「按文字搭 3D 场景」(executors/scenes.scene_from_text)用。

    和整片模板的 `blockout_rules` 不同:那边是分镜,每镜可能换一个地方,所以每镜一个布景台;这里是**一个地方里的
    一段事**,每镜复制一份布景的话,出来的是几个互不相干的场景、人偶只是摆在原地(用户截图:「一个女孩在雪山脚下的
    草原上跑步」搭成了三套一样的草原和山,女孩不动)。所以这里只搭一个布景,动作写成人物的关键帧,几个镜头是几台
    相机从不同机位拍同一段动作。相机、运镜、镜头、打光的规矩和整片模板同一份(`_camera_rules`)。
    """
    return f"""{_COORDINATES}
**只搭一个布景。** 这段文字写的是一个地方里发生的一段事 —— 所有镜头都在这**同一个**布景里拍。**不要**每镜复制一份
地面、山和人物,也不要分组:布景放在原点附近,每个物体的 parent_id 都写空字符串。

布景里:
- 地面和环境:室内用一个 room(parameters.width/depth/height 取{source}里这个地方的尺寸,门洞在前后墙正中;
  没有天花板);室外用一块 plane 当地面、几块 box 当远景体块。**地面要够人物走完整段动作**。
- 关键陈设用 box / cylinder / table / stairs 概括(桌椅、柜子、门、树……),尺寸按真实比例。
- 每个出场的角色**一个** figure(整段戏只有这一个,不按镜头复制):parameters.height = 角色身高,
  width 0.4~0.5(肩宽),depth 0.22~0.28;每个角色一个不同的 color;rotation[1] 是朝向(度)。
  这个角色是下面「资产库里的人物」清单里的某一个,entity_id 就写那个 id(之后生成时带上他的长相);不是就写空字符串。
{_PROP_RULE}- 相机以外的物体 target 写 [0,1,0]、fov 写 45(用不上);非 model 的物体 model_id 写空字符串,
  非 figure 的物体 entity_id 写空字符串。

**动作写在人物的 track 上,不要摆成静止的人偶。** 文字里的跑、走、转身、停下……都是这个 figure 的关键帧:
每一档写 position(y=0 贴地)和 rotation(rotation[1] 朝着运动方向),target 写 [0,1,0]、fov 写 45(人物用不上)。
从 time:0 到 time:{clip} 至少两档,转弯、停顿各加一档;速度按常识 —— 走 1.2~1.5 米/秒,慢跑约 3 米/秒,
快跑 5~6 米/秒。不动的物体 track 写空数组。

**几个镜头 = 几台相机拍同一段动作。** 轨上的时间是场景时间,每个镜头都从第 0 秒拍到第 {clip} 秒;镜头之间换的是
景别和角度(比如一个全景交代环境、一个跟拍中景、一个近景或反打)。**跟拍的相机要跟着人走**:它每一档的 position
和 target 都照人物在那一时刻的位置平移,否则人跑出画面。相机的关键帧 rotation 写 [0,0,0](相机用不上)。

{_camera_rules(clip, source=source)}"""


def full_video_generation_graph(
    *, chat: ModelChoice, image: ModelChoice, video: ModelChoice, voice_id: str = "", db: Session | None = None
) -> dict[str, Any]:
    """主题 → 主旨 → 脚本 / 视觉圣经 → 角色三视图 + 场景设定图 → 分镜 → 3D 白模布景 → 逐镜:
    白模参考 → 首帧(需要时加尾帧)→ 视频 → 按序上时间线 → 口播字幕 → 导出。

    此前每一镜只有一段文字提示词:构图、机位、人物长相全靠视频模型猜,几镜之间谁也对不上谁。
    现在一致性和镜头语言各有实物依据:

    - **人物**:每个角色先画一张三视图,之后所有关键帧和参考都带着它;
    - **场景**:每个场景先画一张设定图;
    - **构图与机位**:LLM 按分镜搭 3D 白模,每镜一个布景台、一台相机(推拉摇移都在相机轨迹上),
      后端渲出白模首尾帧和运镜视频,镜头语言从机位轨迹**算出来**进提示词;
    - **每镜两条路之一**(Seedance 这类模型上两组素材互斥,见 generation/catalog.SOURCE_GROUPS):
      `keyframes` 先按白模机位画首帧(需要时加尾帧)再出片,构图最稳;`references` 把三视图、
      设定图、白模帧和运镜视频直接交给视频模型,适合复杂运镜。走哪条由分镜逐镜决定,能选哪几条
      由视频模型的能力决定(见 VideoPlan.modes)。

    ``db`` 让模型的默认参数能读到用户自定义的参数声明;官网导出等无库上下文留空,退回内置目录。
    """
    video_plan = _video_plan(db, video)
    image_plan = _image_plan(db, image)
    clip = video_plan.clip_seconds
    aspect = video_plan.aspect_ratio if video_plan.aspect_ratio in ("16:9", "9:16", "1:1") else "16:9"
    video_parameters = dict(video_plan.parameters or {})
    ratios = [str(one) for one in (_capabilities(db, video, "video") or {}).get("aspect_ratios") or ()]
    if "aspect_ratio" in video_parameters and ratios and aspect not in ratios:
        #: 这个模型不收白模那三种画幅里的任何一种(比如只收 adaptive,画幅跟着首帧走):视频那一步交它认的那一档,
        #: 白模、关键帧和时间线照旧按 `aspect`。
        video_parameters["aspect_ratio"] = video_plan.aspect_ratio if video_plan.aspect_ratio in ratios else ratios[0]
    #: 每种画幅下关键帧图的尺寸、视频的尺寸(按尺寸定画幅的模型)、成片画布 —— 建图时按两个模型的能力表一次算好,
    #: 跑的时候按开始节点的 aspect_ratio 取一组(「按画幅取尺寸」)。此前开始节点里摆着四格要一起改,漏改 frame_size
    #: 或 width / height 的话竖屏的镜头被裁进横屏画布;万相视频的 size 更是写死 832*480,改了画幅照样出横屏。
    frame_table = {
        one: {
            "frame_size": image_plan.frame_sizes.get(one, ""),
            "video_size": (video_plan.sizes or {}).get(one, ""),
            "width": width,
            "height": height,
        }
        for one, (width, height) in FRAME_ASPECTS.items()
    }
    image_parameters = {"size": "{{input.frame_size}}"} if image_plan.frame_sizes else {}
    sheet_parameters = {"size": image_plan.sheet_size} if image_plan.sheet_size else {}
    modes_text = " / ".join(video_plan.modes)

    brief_system = """你是资深创意总监和纪录片策划。先把用户给出的主题收敛为全片唯一核心主旨，
建立清晰的受众收益、叙事因果和可执行视觉母题。不要编造未经输入支持的具体数字、引语、人物经历
或研究结论；需要核实的内容写入 factual_boundaries。只输出符合 JSON Schema 的对象。"""

    narrative_system = """你是资深编剧和旁白导演。围绕唯一核心主旨规划完整叙事，不引入创意简报之外
的事实。按目标时长拆成首尾连续的叙事节拍：开头尽快建立观看理由，中段用因果而不是信息堆砌推进，
结尾回收主旨。口播要自然、可说、符合指定语言。只输出符合 JSON Schema 的对象。"""

    visual_system = """你是摄影指导、美术指导、角色设计和连续性监制。根据创意简报建立全片共享的视觉圣经：
主体、环境、光线、色彩、镜头语言与连续性规则，规则要具体到生成模型可以复用，避免空泛风格词。
同时定下**出镜角色**(最多 4 个；appearance 用英文写到能画出三视图的程度：年龄、脸型发型、服装与配色、
体型、标志性道具)和**场景**(最多 3 个；description 用英文写空间、陈设、材质与光源，给出大致的
长宽高)。每个角色分一个不同的白模颜色，并在 blockout_legend 里用英文说明颜色与角色的对应。
style_prompt 是一句英文画风，全片每张图、每段视频都会带上。不得要求画面生成字幕、UI、Logo 或水印。
用户会给出资产库里已有的人物和场景：故事需要的角色或场景**就是**其中某一个时，name 一字不差地沿用它的名字，
appearance / description 照它的提示词描述写（它的参考图会直接拿来用，不再重画）；只是相像、并不是同一个的不要硬套，
新建一个名字不同的。清单为空就全部新建。
只输出符合 JSON Schema 的对象。"""

    storyboard_system = f"""你是导演、摄影指导、分镜师和生成提示词工程师。把创意简报拆成连续的
{clip} 秒镜头。每镜给出精确起止时间、口播、场景(location_id)、出镜角色、人物站位与走位、景别、
机位角度、焦段(lens_mm)、运镜方式与路径、主体动作、光线、声音设计和连续性。所有镜头时间必须
首尾相接，不重叠、不留空；首镜建立钩子，中段逐步升级信息，末镜完成主旨回收。每镜 narration 念出来
不得超过 {clip} 秒：中文按每秒约 4 字、英文按每秒约 2.5 个词估算，宁短勿长；超出的部分会被加速压进
这一镜，听起来会很赶。

每镜选一条出片路径(reference_mode,可选:{modes_text}):keyframes 先按白模机位画首帧再生成,
构图最稳,适合绝大多数镜头;references 把角色三视图、场景设定图和白模运镜视频直接交给视频模型,
适合环绕、长距离跟拍这类首尾两帧说不清的复杂运镜。first_frame_prompt 用英文完整描述第一帧画面。
generation_prompt 用英文写动作节拍、表演、环境变化与光影，主体动作必须能在 {clip} 秒内完成；
**不要写机位参数**(机位会从白模自动算出来补上),画面中不要生成字幕、UI、Logo 或水印。
transition_in/out 是交付给后期查看的剪辑意图；本工作流自动合成阶段按时间顺序硬切。只输出符合
JSON Schema 的对象。"""

    set_system = f"""你是布景师兼摄影助理。按分镜给每个镜头搭一个 3D 白模布景台，并放好这一镜的相机。
输出就是 3D 场景的数据格式，会被直接建成场景、渲出参考帧交给图像和视频模型 —— 它决定每一镜的构图。

{blockout_rules(clip, source="视觉圣经")}只输出符合 JSON Schema 的对象。"""

    frame_prompt_tail = (
        " Reference images: the first one is a grey 3D blockout of this exact shot — match its camera angle, lens, "
        "framing, horizon line and the placement of the coloured mannequins exactly ({{input.legend}}); the "
        "mannequins are stand-ins, render them as the real characters. The character turnaround sheets fix each "
        "character's face, hair, outfit and proportions; the location concept art fixes the set. Only the characters "
        "described above appear. {{input.style}}"
    )

    generate_body = {
        "nodes": [
            {
                "id": "render_blockout",
                "type": "scene_render",
                "name": {"zh": "渲染本镜白模参考", "en": "Render this shot's blockout"},
                "position": {"x": 80, "y": 140},
                "config": {
                    "scene_id": "{{input.scene_id}}",
                    "shot_id": "shot-{{loop.item.shot_number}}",
                    #: 静帧给首尾帧那条路,运镜视频给参考那条路。两样都渲:运镜视频也是给人检查机位的。
                    "render": "both",
                    "project_id": "{{input.project_id}}",
                },
            },
            {
                "id": "is_keyframes",
                "type": "condition",
                "name": {"zh": "这一镜走首尾帧吗", "en": "Does this shot use keyframes?"},
                "position": {"x": 390, "y": 60},
                "config": {"left": "{{loop.item.reference_mode}}", "op": "equals", "right": "keyframes"},
            },
            {
                "id": "paint_first_frame",
                "type": "ai_generate",
                "name": {"zh": "按白模机位画首帧", "en": "Paint the first frame on the blockout"},
                "position": {"x": 700, "y": 60},
                "config": {
                    "provider": image.provider,
                    "provider_profile_id": image.profile_id,
                    "model": image.model,
                    "kind": "image",
                    "prompt": "{{loop.item.first_frame_prompt}}" + frame_prompt_tail,
                    "parameters": image_parameters,
                    "source_assets": [
                        "{{render_blockout.first_frame_asset_id}}:reference_image",
                        "{{input.sheets}}",
                        "{{input.locations}}",
                    ],
                },
            },
            {
                "id": "needs_last_frame",
                "type": "condition",
                "name": {"zh": "这一镜要尾帧吗", "en": "Does this shot need a last frame?"},
                "position": {"x": 1010, "y": 60},
                "config": {"left": "{{loop.item.last_frame_prompt}}", "op": "not_empty"},
            },
            {
                "id": "paint_last_frame",
                "type": "ai_generate",
                "name": {"zh": "按白模机位画尾帧", "en": "Paint the last frame on the blockout"},
                "position": {"x": 1320, "y": 60},
                "config": {
                    "provider": image.provider,
                    "provider_profile_id": image.profile_id,
                    "model": image.model,
                    "kind": "image",
                    "prompt": "{{loop.item.last_frame_prompt}} This is the last frame of the same shot whose first frame "
                              "is the second reference image — keep characters, wardrobe, lighting and set continuous."
                              + frame_prompt_tail,
                    "parameters": image_parameters,
                    "source_assets": [
                        "{{render_blockout.last_frame_asset_id}}:reference_image",
                        "{{paint_first_frame.asset_id}}:reference_image",
                        "{{input.sheets}}",
                        "{{input.locations}}",
                    ],
                },
            },
            {
                "id": "generate_clip",
                "type": "ai_generate",
                "name": {"zh": f"生成 {clip} 秒镜头", "en": f"Generate the {clip}s shot"},
                "position": {"x": 1320, "y": 260},
                "config": {
                    "provider": video.provider,
                    "provider_profile_id": video.profile_id,
                    "model": video.model,
                    "kind": "video",
                    "prompt": "{{loop.item.generation_prompt}} Camera: {{render_blockout.camera_move}}. "
                              "Keep every character exactly as in the references. {{input.style}}",
                    "negative_prompt": "{{loop.item.negative_prompt}}",
                    "parameters": video_parameters,
                    #: 两组都接上,由 source_group 逐镜选一组(Seedance 上两组互斥)。没跑的首尾帧是空行,
                    #: 自然消失;`{{input.sheets}}` 这样的整组引用在运行时摊平。
                    "source_assets": [
                        "{{paint_first_frame.asset_id}}:first_frame",
                        "{{paint_last_frame.asset_id}}:last_frame",
                        "{{input.sheets}}",
                        "{{input.locations}}",
                        "{{render_blockout.first_frame_asset_id}}:reference_image",
                        #: 白模运镜视频只交给收参考视频的模型(可灵 v3 omni 收参考图、不收参考视频,给了当场拒)。
                        *(["{{render_blockout.video_asset_id}}:reference_video"] if video_plan.reference_video else []),
                    ],
                    "source_group": "{{loop.item.reference_mode}}",
                },
            },
            {
                "id": "organize_clip",
                "type": "asset_update",
                "name": {"zh": "归档并命名镜头素材", "en": "File and name the shot's asset"},
                "position": {"x": 1630, "y": 260},
                "config": {
                    "asset_ids": "{{generate_clip.asset_id}}",
                    "name": "镜头 {{loop.item.shot_number}}",
                    "project_id": "{{input.project_id}}",
                },
            },
            {
                "id": "has_voice",
                "type": "condition",
                "name": {"zh": "选了配音音色吗", "en": "Was a voice picked?"},
                "position": {"x": 80, "y": 420},
                "config": {"left": "{{input.voice_id}}", "op": "not_empty"},
            },
            {
                "id": "has_narration",
                "type": "condition",
                "name": {"zh": "这一镜有口播吗", "en": "Does this shot have narration?"},
                "position": {"x": 390, "y": 420},
                "config": {"left": "{{loop.item.narration}}", "op": "not_empty"},
            },
            {
                "id": "narrate",
                "type": "synthesize_speech",
                "name": {"zh": "合成该镜口播", "en": "Synthesise this shot's narration"},
                "position": {"x": 700, "y": 420},
                # 开始节点里填的是配音库音色的 id,所以引擎是克隆;想用引擎音色,改这里的两格。
                "config": {"text": "{{loop.item.narration}}", "engine": "builtin:clone", "voice": "{{input.voice_id}}"},
            },
        ],
        "edges": [
            {"id": "shot_blockout_mode", "source": "render_blockout", "target": "is_keyframes"},
            {"id": "shot_mode_first", "source": "is_keyframes", "target": "paint_first_frame", "source_handle": "true"},
            {"id": "shot_first_needs_last", "source": "paint_first_frame", "target": "needs_last_frame"},
            {"id": "shot_needs_last", "source": "needs_last_frame", "target": "paint_last_frame", "source_handle": "true"},
            #: 生成视频只挂在白模之后:首尾帧那两个节点在参考那条路上会被跳过,而它们被引用 ——
            #: 引用即依赖,生成会等它们落定(跑完或被跳过)再开始。
            {"id": "shot_blockout_generate", "source": "render_blockout", "target": "generate_clip"},
            {"id": "shot_generate_organize", "source": "generate_clip", "target": "organize_clip"},
            {"id": "shot_voice_gate_narration", "source": "has_voice", "target": "has_narration", "source_handle": "true"},
            {"id": "shot_narration_speak", "source": "has_narration", "target": "narrate", "source_handle": "true"},
        ],
    }
    # 这一段遍历的是上一段的**结果**:每一项是那一镜的全部产物,连同那一镜的分镜本身
    # (`loop.item.loop.item` —— 外面那层 loop 是这一轮,里面那层是生成那一轮)。
    assemble_body = {
        "nodes": [
            {
                "id": "append_clip",
                "type": "timeline_append",
                "name": {"zh": "按镜头顺序接入时间线", "en": "Append this shot to the timeline in order"},
                "position": {"x": 80, "y": 140},
                "config": {
                    "sequence_id": "{{input.sequence_id}}",
                    "asset_id": "{{loop.item.generate_clip.asset_id}}",
                    "track_id": "{{input.video_track_id}}",
                    "start": 0,
                    "end": clip,
                },
            },
            {
                "id": "has_audio",
                "type": "condition",
                "name": {"zh": "这一镜合成了口播吗", "en": "Did this shot get narration?"},
                "position": {"x": 390, "y": 140},
                "config": {"left": "{{loop.item.narrate.asset_id}}", "op": "not_empty"},
            },
            {
                "id": "append_narration",
                "type": "timeline_append",
                "name": {"zh": "把口播对齐到这一镜", "en": "Align the narration to this shot"},
                "position": {"x": 700, "y": 140},
                "config": {
                    "sequence_id": "{{input.sequence_id}}",
                    "asset_id": "{{loop.item.narrate.asset_id}}",
                    "track_id": "{{input.audio_track_id}}",
                    # **放在这一镜画面开始的那一秒**,不是接在上一段口播后面。用的是画面片段**实际**
                    # 落下的位置,不是分镜里写的 start_seconds。
                    "at": "{{append_clip.timeline_start}}",
                    # 不裁(硬裁会把话切掉半句),比镜头长就加速塞进去,最多 1.5 倍。最长按这一镜画面**实际**占的秒数,
                    # 不按计划的 clip 秒:模型交回的视频比 clip 短时,截取被夹到它的末尾。
                    "max_duration": "{{append_clip.duration}}",
                },
            },
            {
                "id": "caption",
                "type": "template",
                "name": {"zh": "这一镜的字幕文本", "en": "This shot's subtitle text"},
                "position": {"x": 1010, "y": 140},
                "config": {"template": "{{loop.item.loop.item.narration}}"},
            },
        ],
        "edges": [
            {"id": "assemble_clip_gate", "source": "append_clip", "target": "has_audio"},
            {"id": "assemble_gate_narration", "source": "has_audio", "target": "append_narration", "source_handle": "true"},
            {"id": "assemble_narration_caption", "source": "append_narration", "target": "caption"},
        ],
    }
    def reuse_or_draw(kind: str, what: dict[str, str], drawer: dict[str, Any], save: dict[str, Any]) -> dict[str, Any]:
        """每个角色 / 场景:先到资产库里按名字认(ADR 0027 阶段 4),**有图就用它的,不再重画**;没有才画,画完
        存成资产 —— 下一部片子里的同一个角色是同一张脸。循环交出的是「认出来的那张」或「新画的那张」:
        没跑的那一支引用出来是空串,两段拼在一起正好是跑了的那一支(见 workflows.interpolate)。"""
        return {
            "nodes": [
                {
                    "id": "find",
                    "type": "entity_get",
                    "name": {"zh": f"在资产库里找这个{what['zh']}", "en": f"Look this {what['en']} up in the asset library"},
                    "position": {"x": 80, "y": 140},
                    "config": {"kind": kind, "name": "{{loop.item.name}}", "limit": 1},
                },
                {
                    "id": "has_art",
                    "type": "condition",
                    "name": {"zh": "库里有它的图吗", "en": "Does the library have its images?"},
                    "position": {"x": 380, "y": 140},
                    "config": {"left": "{{find.asset_ids.0}}", "op": "not_empty"},
                },
                {**drawer, "position": {"x": 680, "y": 240}},
                {**save, "position": {"x": 980, "y": 240}},
            ],
            "edges": [
                {"id": "find_check", "source": "find", "target": "has_art"},
                {"id": "missing_draw", "source": "has_art", "target": drawer["id"], "source_handle": "false"},
                {"id": "draw_save", "source": drawer["id"], "target": save["id"]},
            ],
        }

    sheet_body = reuse_or_draw(
        "character",
        {"zh": "角色", "en": "character"},
        {
            "id": "sheet",
            "type": "ai_generate",
            "name": {"zh": "画这个角色的三视图", "en": "Draw this character's turnaround"},
            "config": {
                "provider": image.provider,
                "provider_profile_id": image.profile_id,
                "model": image.model,
                "kind": "image",
                "prompt": "Character turnaround reference sheet for {{loop.item.name}}: {{loop.item.appearance}}. "
                          "Three full-body views of the same character side by side — front, side profile, back — "
                          "identical outfit and proportions, relaxed A-pose, plain white background, soft even studio "
                          "light, no text, no labels, no borders. {{input.style}}",
                "parameters": sheet_parameters,
            },
        },
        {
            "id": "save",
            "type": "entity_save",
            "name": {"zh": "存成人物资产", "en": "Save as a character asset"},
            "config": {
                "kind": "character",
                "name": "{{loop.item.name}}",
                "prompt": "{{loop.item.appearance}}",
                "description": "{{loop.item.role}}",
                "asset_ids": "{{sheet.asset_id}}",
                "role": "turnaround",
            },
        },
    )
    location_body = reuse_or_draw(
        "location",
        {"zh": "场景", "en": "location"},
        {
            "id": "art",
            "type": "ai_generate",
            "name": {"zh": "画这个场景的设定图", "en": "Paint this location's concept art"},
            "config": {
                "provider": image.provider,
                "provider_profile_id": image.profile_id,
                "model": image.model,
                "kind": "image",
                "prompt": "Establishing concept art of {{loop.item.name}}: {{loop.item.description}}. "
                          "Wide view of the empty set, no people, no text. {{input.style}}",
                "parameters": sheet_parameters,
            },
        },
        {
            "id": "save",
            "type": "entity_save",
            "name": {"zh": "存成场景资产", "en": "Save as a location asset"},
            "config": {
                "kind": "location",
                "name": "{{loop.item.name}}",
                "prompt": "{{loop.item.description}}",
                "asset_ids": "{{art.asset_id}}",
                "role": "wide",
            },
        },
    )

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "填写视频主题", "en": "Describe the video you want"},
            "position": {"x": 40, "y": 300},
            "config": {
                "params": {
                    #: 留空,运行前必填(required_params)。此前写着「请把这里改成你的视频主题」,没改就跑的话这句话被当成主题,
                    #: 整条最贵的流程对着它跑完。
                    "topic": "",
                    "target_duration_seconds": 30,
                    #: 这一次最多做几镜。**它是成本的闸门**:每一镜都是一次付费的视频生成,
                    #: 而镜头数此前完全由模型按时长算,跑之前看不到要花多少。
                    "max_shots": 8,
                    "audience": "对该主题感兴趣的大众观众",
                    "tone": "专业、清晰、克制且有电影感",
                    "language": "简体中文",
                    #: 画幅只能是 16:9 / 9:16 / 1:1(3D 白模的镜头只有这三种)。**只改这一格**:关键帧尺寸、视频尺寸、
                    #: 成片画布由「按画幅取尺寸」按它取(见 frame_table)。视频模型不收这个画幅时(Veo 不收 1:1),
                    #: 运行前就拦,不等关键帧付完钱。resolution 是清晰度档位,一般不用动。
                    "aspect_ratio": aspect,
                    "resolution": video_plan.resolution,
                    "fps": 30,
                    # 配音音色。**留空 = 不配音**(成片只有画面),而不是跑到一半失败。
                    "voice_id": voice_id,
                },
                "required_params": "topic",
            },
        },
        {
            "id": "frame_plan",
            "type": "json_extract",
            "name": {"zh": "按画幅取尺寸", "en": "Pick the sizes for the aspect ratio"},
            "position": {"x": 340, "y": 460},
            "config": {"source": json.dumps(frame_table, ensure_ascii=False), "path": "{{start.aspect_ratio}}"},
        },
        {
            "id": "creative_brief",
            "type": "llm",
            "name": {"zh": "提炼核心主旨与创意简报", "en": "Distil the core idea into a creative brief"},
            "position": {"x": 340, "y": 300},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "precise",
                "system": brief_system,
                "prompt": """主题：{{start.topic}}
目标时长：{{start.target_duration_seconds}} 秒
目标观众：{{start.audience}}
表达气质：{{start.tone}}
成片语言：{{start.language}}

请形成可直接供导演执行的创意简报。核心主旨只能有一个；若主题过宽，主动选择最有叙事张力且
不需要虚构事实的角度。""",
                "response_format": "json_schema",
                "json_schema_name": "professional_video_creative_brief",
                "json_schema": _creative_brief_schema(),
                "json_schema_strict": "true",
                "temperature": 0.3,
                "max_tokens": 2400,
            },
        },
        {
            "id": "narrative_script",
            "type": "llm",
            "name": {"zh": "编写叙事脚本与时间节拍", "en": "Write the narrative script and its beats"},
            "position": {"x": 680, "y": 80},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "precise",
                "system": narrative_system,
                "prompt": """创意简报：
{{creative_brief.text}}

目标时长：{{start.target_duration_seconds}} 秒
成片语言：{{start.language}}
请输出完整口播，并把叙事拆成按时间连续的 beats。每个 beat 必须有明确叙事任务。""",
                "response_format": "json_schema",
                "json_schema_name": "professional_video_narrative_script",
                "json_schema": _narrative_script_schema(),
                "json_schema_strict": "true",
                "temperature": 0.4,
                "max_tokens": 5000,
            },
        },
        {
            "id": "library_characters",
            "type": "entity_list",
            "name": {"zh": "看看资产库里有哪些人物", "en": "See which characters the asset library has"},
            "position": {"x": 340, "y": 620},
            "config": {"kind": "character"},
        },
        {
            "id": "library_locations",
            "type": "entity_list",
            "name": {"zh": "看看资产库里有哪些场景", "en": "See which locations the asset library has"},
            "position": {"x": 340, "y": 780},
            "config": {"kind": "location"},
        },
        {
            "id": "visual_bible",
            "type": "llm",
            "name": {"zh": "定角色、场景与视觉圣经", "en": "Define characters, locations and the visual bible"},
            "position": {"x": 680, "y": 520},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "creative",
                "system": visual_system,
                "prompt": """创意简报：
{{creative_brief.text}}

画幅：{{start.aspect_ratio}}；表达气质：{{start.tone}}。
请建立整条视频共享的视觉圣经、摄影语言和跨镜头连续性规则，并定下出镜角色与场景。

资产库里已有的人物（名字 — 提示词描述；空着就是还没有）：
{{library_characters.text}}

资产库里已有的场景：
{{library_locations.text}}""",
                "response_format": "json_schema",
                "json_schema_name": "professional_video_visual_bible",
                "json_schema": _visual_bible_schema(),
                "json_schema_strict": "true",
                "temperature": 0.55,
                "max_tokens": 5000,
            },
        },
        {
            "id": "video_project",
            "type": "project_sequence_create",
            "name": {"zh": "建立成片项目与时间线", "en": "Create the project and its timeline"},
            "position": {"x": 680, "y": 300},
            "config": {
                "name": "{{creative_brief.json.title}} · 自动成片",
                "width": "{{frame_plan.value.width}}",
                "height": "{{frame_plan.value.height}}",
                "fps": "{{start.fps}}",
            },
        },
        {
            "id": "character_sheets",
            "type": "loop_foreach",
            "name": {"zh": "每个角色:库里有就用,没有就画三视图", "en": "Every character: reuse from the library or draw a turnaround"},
            "position": {"x": 1040, "y": 620},
            "config": {
                "items": "{{visual_bible.json.characters}}",
                "inputs": {"style": "{{visual_bible.json.style_prompt}}"},
                "body": sheet_body,
                #: 每项交出一行 `素材:reference_image` —— 下游把整组一次接进参考图。
                #: 认出来的那张,或新画的那张(另一支没跑,引用出来是空串)。
                "output": "{{find.asset_ids.0}}{{sheet.asset_id}}:reference_image",
                "concurrency": 3,
            },
        },
        {
            "id": "location_art",
            "type": "loop_foreach",
            "name": {"zh": "每个场景:库里有就用,没有就画设定图", "en": "Every location: reuse from the library or paint concept art"},
            "position": {"x": 1040, "y": 820},
            "config": {
                "items": "{{visual_bible.json.locations}}",
                "inputs": {"style": "{{visual_bible.json.style_prompt}}"},
                "body": location_body,
                "output": "{{find.asset_ids.0}}{{art.asset_id}}:reference_image",
                "concurrency": 3,
            },
        },
        {
            "id": "storyboard",
            "type": "llm",
            "name": {"zh": "按时间拆解分镜与机位", "en": "Break the script into timed shots and camera set-ups"},
            "position": {"x": 1040, "y": 300},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "creative",
                "system": storyboard_system,
                "prompt": f"""请把叙事脚本与视觉圣经合并成可直接生成的专业时间分镜。

创意简报：
{{{{creative_brief.text}}}}

叙事脚本与节拍：
{{{{narrative_script.text}}}}

视觉圣经(含角色与场景 id)：
{{{{visual_bible.text}}}}

成片目标时长：{{{{start.target_duration_seconds}}}} 秒；画幅：{{{{start.aspect_ratio}}}}；
语言：{{{{start.language}}}}。每个镜头固定 {clip} 秒。镜头数 = 目标时长 ÷ {clip} 向上取整，
但**最多 {{{{start.max_shots}}}} 镜**；两者冲突时以上限为准，把成片做短一点，
**不要**为了凑满时长而缩短单镜时长——单镜时长是固定的 {clip} 秒。时间码从 0 开始连续编号。""",
                "response_format": "json_schema",
                "json_schema_name": "professional_timed_storyboard",
                "json_schema": _storyboard_schema(video_plan),
                "json_schema_strict": "true",
                "temperature": 0.65,
                "max_tokens": 12000,
            },
        },
        {
            #: 留空 = 这个工作区里的全部模型。模板装出来时通常一份都没有,清单因此是空的,
            #: 布景师照旧只用基本体 —— 等用户在 Blender 里建好道具收进来,不改图就生效。
            "id": "props",
            "type": "scene_props",
            "name": {"zh": "可用的 3D 道具", "en": "Available 3D props"},
            "position": {"x": 1400, "y": 460},
            "config": {"model_ids": ""},
        },
        {
            "id": "set_design",
            "type": "llm",
            "name": {"zh": "设计 3D 白模布景与机位", "en": "Design the 3D blockout sets and cameras"},
            "position": {"x": 1400, "y": 300},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "precise",
                "system": set_system,
                "prompt": """视觉圣经(角色身高与白模颜色、场景尺寸)：
{{visual_bible.text}}

分镜(每镜的场景、出镜角色、站位、景别、机位角度、焦段、运镜与路径)：
{{storyboard.text}}

可用的 3D 道具(kind="model" 时 model_id 只能从这里选;尺寸是实测值)：
{{props.catalog}}

画幅：{{start.aspect_ratio}}。请给每个镜头搭一个布景台并放好相机。""",
                "response_format": "json_schema",
                "json_schema_name": "blockout_scene",
                "json_schema": _set_design_schema(),
                "json_schema_strict": "true",
                "temperature": 0.2,
                "max_tokens": 16000,
            },
        },
        {
            "id": "build_set",
            "type": "scene_create",
            "name": {"zh": "搭建 3D 白模场景", "en": "Build the 3D blockout scene"},
            "position": {"x": 1720, "y": 300},
            "config": {
                "name": "{{creative_brief.json.title}} · 白模",
                "layout": "{{set_design.json}}",
            },
        },
        {
            "id": "generate_shots",
            "type": "loop_foreach",
            "name": {"zh": "逐镜生成画面与口播", "en": "Generate every shot's picture and narration"},
            "position": {"x": 2040, "y": 300},
            "config": {
                "items": "{{storyboard.json.shots}}",
                "inputs": {
                    "project_id": "{{video_project.project_id}}",
                    "voice_id": "{{start.voice_id}}",
                    "scene_id": "{{build_set.scene_id}}",
                    "sheets": "{{character_sheets.results}}",
                    "locations": "{{location_art.results}}",
                    "style": "{{visual_bible.json.style_prompt}}",
                    "legend": "{{visual_bible.json.blockout_legend}}",
                    "frame_size": "{{frame_plan.value.frame_size}}",
                    "video_size": "{{frame_plan.value.video_size}}",
                    "aspect_ratio": "{{start.aspect_ratio}}",
                    "resolution": "{{start.resolution}}",
                },
                "body": generate_body,
                # 不写 output:每一项交出那一镜的全部产物(画面、口播)连同分镜本身,
                # 下一段按顺序上时间线、配字幕都要用。
                "output": "",
                # 三镜同时:视频供应商大多按账号限并发,再多就是排队或 429。
                "concurrency": 3,
            },
        },
        {
            "id": "assemble_timeline",
            "type": "loop_foreach",
            "name": {"zh": "按镜头顺序接上时间线", "en": "Append the shots to the timeline in order"},
            "position": {"x": 2360, "y": 300},
            "config": {
                "items": "{{generate_shots.results}}",
                "inputs": {
                    "sequence_id": "{{video_project.sequence_id}}",
                    "video_track_id": "{{video_project.video_track_id}}",
                    "audio_track_id": "{{video_project.audio_track_id}}",
                },
                "body": assemble_body,
                "output": "",
                # 一镜接一镜:「接到末尾」的落点取决于前一镜已经接上。
                "concurrency": 1,
            },
        },
        {
            "id": "narration_subtitles",
            "type": "generate_subtitles",
            "name": {"zh": "把口播做成字幕", "en": "Turn the narration into subtitles"},
            "position": {"x": 2680, "y": 300},
            "config": {
                "sequence_id": "{{video_project.sequence_id}}",
                "segments": "{{assemble_timeline.results}}",
                "start_field": "append_narration.timeline_start",
                "end_field": "append_narration.timeline_end",
                "text_field": "caption.text",
                # 整片没有口播(没选音色)时交出 0 条,不让一条已经生成完的片子在这里失败。
                "allow_empty": "yes",
            },
        },
        {
            "id": "export_final",
            "type": "export_sequence",
            "name": {"zh": "合成并导出最终视频", "en": "Compose and export the final video"},
            "position": {"x": 3000, "y": 300},
            "config": {"sequence_id": "{{video_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "成片完成通知", "en": "Video finished notice"},
            "position": {"x": 3320, "y": 120},
            "config": {
                "title": "视频已生成：{{creative_brief.json.title}}",
                "body": "脚本、角色三视图、3D 白模、各镜视频和最终合成均已完成。最终素材 ID：{{export_final.asset_id}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付完整制作结果", "en": "Hand over the finished production"},
            "position": {"x": 3320, "y": 480},
            "config": {
                "values": {
                    "title": "{{creative_brief.json.title}}",
                    "core_thesis": "{{creative_brief.json.core_thesis}}",
                    "creative_brief": "{{creative_brief.json}}",
                    "narrative_script": "{{narrative_script.json}}",
                    "visual_bible": "{{visual_bible.json}}",
                    "storyboard": "{{storyboard.json}}",
                    "character_sheets": "{{character_sheets.results}}",
                    "location_art": "{{location_art.results}}",
                    "blockout_scene_id": "{{build_set.scene_id}}",
                    "shots": "{{generate_shots.results}}",
                    "subtitle_count": "{{narration_subtitles.count}}",
                    "project_id": "{{video_project.project_id}}",
                    "sequence_id": "{{video_project.sequence_id}}",
                    "final_asset_id": "{{export_final.asset_id}}",
                }
            },
        },
    ]
    edges = [
        {"id": "start_brief", "source": "start", "target": "creative_brief"},
        {"id": "start_frame_plan", "source": "start", "target": "frame_plan"},
        {"id": "frame_plan_project", "source": "frame_plan", "target": "video_project"},
        {"id": "frame_plan_generate", "source": "frame_plan", "target": "generate_shots"},
        {"id": "brief_narrative", "source": "creative_brief", "target": "narrative_script"},
        {"id": "brief_visual", "source": "creative_brief", "target": "visual_bible"},
        #: 定角色之前先看资产库里有谁、有哪些地方 —— 故事里要的就是库里那一个时原名沿用,下游才认得出它。
        {"id": "start_library_characters", "source": "start", "target": "library_characters"},
        {"id": "start_library_locations", "source": "start", "target": "library_locations"},
        {"id": "library_characters_visual", "source": "library_characters", "target": "visual_bible"},
        {"id": "library_locations_visual", "source": "library_locations", "target": "visual_bible"},
        {"id": "brief_project", "source": "creative_brief", "target": "video_project"},
        {"id": "visual_sheets", "source": "visual_bible", "target": "character_sheets"},
        {"id": "visual_locations", "source": "visual_bible", "target": "location_art"},
        {"id": "narrative_storyboard", "source": "narrative_script", "target": "storyboard"},
        {"id": "visual_storyboard", "source": "visual_bible", "target": "storyboard"},
        {"id": "storyboard_set", "source": "storyboard", "target": "set_design"},
        {"id": "set_build", "source": "set_design", "target": "build_set"},
        {"id": "build_generate", "source": "build_set", "target": "generate_shots"},
        {"id": "sheets_generate", "source": "character_sheets", "target": "generate_shots"},
        {"id": "locations_generate", "source": "location_art", "target": "generate_shots"},
        {"id": "project_generate", "source": "video_project", "target": "generate_shots"},
        {"id": "generate_assemble", "source": "generate_shots", "target": "assemble_timeline"},
        {"id": "assemble_subtitles", "source": "assemble_timeline", "target": "narration_subtitles"},
        {"id": "subtitles_export", "source": "narration_subtitles", "target": "export_final"},
        {"id": "export_notice", "source": "export_final", "target": "done_notice"},
        {"id": "export_output", "source": "export_final", "target": "output"},
    ]
    graph = {
        "meta": {"template_id": FULL_VIDEO_GENERATION, "template_version": 10, "source": "official"},
        "nodes": nodes,
        "edges": edges,
    }
    return normalize_graph(graph, node_types=NODE_TYPES)
