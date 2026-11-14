"""搭 3D 白模布景的提示词规矩:坐标、布景台、人偶、道具、相机与运镜、镜头与打光,以及「白模只交代形状、不交代气氛」。

整片模板的「设计 3D 白模布景与机位」(`blockout_rules`,每镜一个布景台)和画板上的「按文字搭 3D 场景」
(`single_set_rules`,一个布景几台相机,见 executors/scenes.scene_from_text)读的是同一份 —— 两处各写一份的话,
改了一处的焦段换算、配色,另一处就搭出另一种白模。此前它住在整片模板模块里(2026-11-14 审计 C3)。
"""

from __future__ import annotations


#: 两种搭法共用的几段规矩:坐标约定、真道具、相机与运镜 / 镜头 / 打光。**一份文字两处读** —— 改了焦段换算的那一份
#: 和没改的那一份会搭出两种机位。
_COORDINATES = "坐标约定：单位米，Y 朝上，地面 y=0；所有坐标都写**世界坐标**。\n"

_PROP_RULE = """- **能用真道具就别用方块拼。** 下面那份「可用的 3D 道具」清单里的东西是已经建好的真实模型:
  kind="model",model_id 写清单里那个 id,name 写道具名,position/rotation 照常摆。清单里给了
  每件道具实测的长宽高,按它和 figure(人)的比例摆,不要再用 parameters 去"设定"它的尺寸
  (模型自带尺寸,parameters 对它无效)。清单为空就全用基本体。
"""


def _camera_rules(clip: int | str, *, source: str) -> str:
    return f"""每镜一台相机：kind="camera",id="cam-<n>";position 是起始机位,target 是起始看向点(一般是主体的胸口
或眼睛高度 1.3~1.6 米),fov 是竖直视角,由焦段换算:fov = 2*atan(12/焦段毫米)(14mm≈81°,24mm≈53°,
35mm≈38°,50mm≈27°,85mm≈16°,135mm≈10°)。机位高度按机位角度:平视 1.5~1.7 米,俯拍 2.5~4 米,
仰拍 0.3~0.8 米。相机必须在房间内、不穿过任何物体,和主体的距离要让景别成立(特写约 0.6~1 米,
中景 1.5~2.5 米,全景 3~5 米)。
运镜写在相机的 track 上：static 不写 track;其余至少两档 {{time:0,...}} 和 {{time:{clip},...}}
(position/target/fov 三项都写),推 = 沿视线靠近主体,拉 = 远离,摇 = 机位不动只转 target,
跟 = 机位和 target 一起平移,环绕 = 绕主体转(可加中间一档),升降 = 机位上下移动。

shots:每镜一条 {{id:"shot-<n>", name:"镜头 <n>", duration:{clip}, aspect:画幅, easing:"smooth",
camera_id:"cam-<n>", shot_angle:这台相机从主体哪个方向拍}}。shot_angle 从 front(正面)、three_quarter(斜侧,
约 45°)、side(侧面)、back(背面)、high_angle(明显俯拍)、low_angle(明显仰拍)里选;没有主要人物、说不清的写空字符串。

**白模只交代形状、机位和站位,不交代气氛。** 渲出来的那张交给画关键帧的模型照着取景;夜色、色调、天气由画关键帧那一步
按提示词画。所以:
- room、地面、陈设、远景体块一律用中性灰,按离相机由近到远分三档:近 "#c8c8c8"、中 "#9a9a9a"、远 "#6e6e6e"
  —— 夜景、雨天也**不调暗、不上色**;人物照旧用各自的颜色(它们是图例),灯笼、烛火这类本身发光的小件可以留它的颜色;
- background 写 "#b8bcc2",ambient 写 2.5;
- lighting 只取{source}光线方案里的**方向**:方位角(0=相机默认一侧,90=右侧,180=逆光)和高度角;强度写 3.5、
  色温 6500、softness 0.5,preset 写 "custom"。
此前跟着视觉圣经把背景、墙面都调成近黑的深蓝灰、灯光按夜色压暗:渲出来几乎一片黑,形状看不出来,画关键帧的模型
只好照着场景设定图的构图画。
"""


def blockout_rules(clip: int | str, *, source: str) -> str:
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


def single_set_rules(clip: int | str, *, source: str) -> str:
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
