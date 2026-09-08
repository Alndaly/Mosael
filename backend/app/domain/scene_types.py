"""Portable, model-independent scene description. Units are metres and degrees."""
from typing import Annotated, Literal

from pydantic_core import PydanticCustomError
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SceneValue(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


Number = Annotated[float, Field(ge=-10000, le=10000)]
Vec3 = tuple[Number, Number, Number]
Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")]


class ShapeParameters(SceneValue):
    width: float = Field(2, ge=.01, le=1000)
    height: float = Field(2, ge=.01, le=1000)
    depth: float = Field(2, ge=.01, le=1000)
    radius: float = Field(1, ge=.01, le=500)
    steps: int = Field(8, ge=1, le=64)
    door_width: float = Field(1.4, ge=.1, le=100)
    door_height: float = Field(2.3, ge=.1, le=100)


class Keyframe(SceneValue):
    """时间轨上的一个时刻。**相机和物体共用一种形状**,按各自用得上的字段填。

    相机用 `position` + `target` + `fov`:瞄一个点比给欧拉角好摆(镜头总是"看着什么"),
    而且 Blender 往返本来就是按这个约定烘焙的。物体用 `position` + `rotation` + `scale`。
    没填的字段表示"这一档不控制它"。

    共用一种形状而不是分两个类,是因为**时间轴上的插值逻辑只该有一份**:分开写的话,
    "缓动怎么算""端点怎么取"就有两个实现,而它们必然会分岔。
    """

    time: float = Field(0, ge=0, le=120)
    position: Vec3 = (8, 5, 8)
    #: 相机:看向哪里。
    target: Vec3 | None = None
    fov: Annotated[float, Field(ge=10, le=120)] | None = None
    #: 物体:朝向与缩放(度)。
    rotation: Vec3 | None = None
    scale: tuple[Annotated[float, Field(ge=.001, le=1000)], Annotated[float, Field(ge=.001, le=1000)],
                 Annotated[float, Field(ge=.001, le=1000)]] | None = None

    @model_validator(mode="after")
    def distinct_target(self):
        if self.target is not None and sum((a-b)**2 for a, b in zip(self.position, self.target)) < .000001:
            raise PydanticCustomError("scene_invalid", "Camera position and target must differ")
        return self


class SceneObject(SceneValue):
    id: Identifier
    name: str = Field("Object", max_length=160)
    kind: Literal["box", "sphere", "cylinder", "plane", "room", "stairs", "group", "model", "light",
                  "figure", "table", "camera"]
    parent_id: Identifier | None = None
    position: Vec3 = (0, 0, 0)
    rotation: Vec3 = (0, 0, 0)
    scale: tuple[Annotated[float, Field(ge=.001, le=1000)], Annotated[float, Field(ge=.001, le=1000)], Annotated[float, Field(ge=.001, le=1000)]] = (1, 1, 1)
    parameters: ShapeParameters = Field(default_factory=ShapeParameters)
    color: str = Field("#b4bccb", pattern=r"^#[0-9a-fA-F]{6}$")
    roughness: float = Field(.6, ge=0, le=1)
    metalness: float = Field(0, ge=0, le=1)
    intensity: float = Field(30, ge=0, le=10000)
    hidden: bool = False
    model_id: Identifier | None = None
    #: 相机看向哪里,以及视角。非相机忽略它们。
    #:
    #: **相机的静止姿态也放在物体上**(position + target + fov),和别的物体一样 ——
    #: 轨是"随时间的覆盖",空轨就是静止。把静止姿态藏进 track[0] 的话,一台不动的相机就必须
    #: 带一条只有一帧的轨,而"有没有轨"本该正好等于"动不动"。
    target: Vec3 = (0, 1, 0)
    fov: float = Field(45, ge=10, le=120)
    #: 随时间变化。**空的就是静止** —— 绝大多数物体都是空的,所以它是可选而不是必填。
    track: list[Keyframe] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def camera_looks_somewhere(self):
        if self.kind == "camera" and sum((a-b)**2 for a, b in zip(self.position, self.target)) < .000001:
            raise PydanticCustomError("scene_invalid", "Camera position and target must differ")
        return self

    @model_validator(mode="after")
    def model_required(self):
        if self.kind == "model" and not self.model_id:
            raise PydanticCustomError("scene_invalid", "Model objects require an imported model_id")
        return self

    @model_validator(mode="after")
    def ordered_track(self):
        """轨上的时刻**从 0 开始、严格递增**,而且相机的每一档都要有 target。

        端点和顺序是插值的前提:乱序的轨会让"下一个时刻"找错,表现为画面在某一秒突然跳回去。
        相机缺 target 则是"看向哪里"没定义 —— 那时只能猜一个,而猜错的构图看不出是 bug。
        """
        if not self.track:
            return self
        times = [f.time for f in self.track]
        if times[0] != 0 or times != sorted(set(times)):
            raise PydanticCustomError("scene_invalid", "Keyframes must begin at 0 and increase")
        if self.kind == "camera" and any(f.target is None for f in self.track):
            raise PydanticCustomError("scene_invalid", "Camera keyframes need a target")
        return self


class SceneShot(SceneValue):
    """一个镜头 = **用哪台机位、拍多久**。

    运镜本身不在这里 —— 它是那台相机物体的 `track`。此前 `frames` 长在镜头上,于是"随时间
    变化"这件事只有相机享受得到,而且相机本身不是场景里的物体:选不中、拖不动、编不了组。
    见 docs/design/scene-time-and-cameras.md。

    轨上的时间是**场景时间**,镜头目前一律从 0 开始截取。以后要加 `start_time` 不需要迁移
    (默认 0),那时"一段 12 秒的走位被一个 5 秒的镜头截取中间一段"才成立。
    """

    id: Identifier
    name: str = Field("Shot", max_length=160)
    duration: float = Field(5, ge=.1, le=120)
    aspect: Literal["16:9", "9:16", "1:1"] = "16:9"
    easing: Literal["linear", "smooth"] = "smooth"
    #: 拍它的那台相机物体。由 SceneContent 校验它确实存在、确实是相机。
    camera_id: Identifier


class SceneLighting(SceneValue):
    """主光。**它此前是写死在视口里的一盏白光**(方向 (4,9,5)、强度 2.5),不可调、不可关。

    而这一页产出的画面是要交给图像/视频模型当参考的 —— 打光对成片的影响极大,用文字又极难
    说准("暖一点""再侧一点"说十遍也对不齐),用角度和色温一摆就精确。所以它该是场景数据,
    和构图、运镜一样能存能改能复用。

    `preset` 只记**选的是哪一档**,不参与渲染:渲染看下面那几个数。留着它是为了两件事 ——
    界面上要知道当前停在哪一档,以及交给模型时要一并送出那一档的文字描述(灯位由参考帧
    表达"光从哪来",文字表达"这是什么光",两样缺一不可)。用户手动改过数之后 preset 记
    `custom`。
    """

    #: 预设 id,或 "custom"。渲染不看它。
    preset: str = Field("studio-soft", max_length=40, pattern=r"^[\w-]+$")
    #: 方位角:0 = 相机正后方(顺光),90 = 右侧,180 = 逆光。**相对场景,不是相对相机** ——
    #: 相对相机的话,镜头一转光就跟着转,同一场景的两个镜头就对不上了。
    azimuth: float = Field(35, ge=0, lt=360)
    #: 高度角:0 = 与地面齐平(贴地侧光),90 = 正顶光。
    elevation: float = Field(55, ge=0, le=90)
    intensity: float = Field(2.5, ge=0, le=20)
    #: 色温(K)。1800 烛光、3200 白炽、5500 日光、7500 阴天。
    temperature: int = Field(5500, ge=1500, le=12000)
    #: 影子的软硬:0 是硬边(晴天直射),1 是柔和(阴天/柔光箱)。
    softness: float = Field(0.35, ge=0, le=1)


class SceneContent(SceneValue):
    version: Literal[1] = 1
    #: **默认场景自带一台相机。** 镜头必须指向一台相机,所以"空场景"里也得有它 ——
    #: 这也是它现在是一个普通物体的自然结果:相机和地面一样,是场景里的东西。
    objects: list[SceneObject] = Field(
        default_factory=lambda: [SceneObject(id="camera-1", name="主机位", kind="camera",
                                             position=(8, 5, 8))],
        max_length=500)
    shots: list[SceneShot] = Field(
        default_factory=lambda: [SceneShot(id="shot-1", name="镜头 1", camera_id="camera-1")],
        min_length=1, max_length=32)
    background: str = Field("#20242c", pattern=r"^#[0-9a-fA-F]{6}$")
    #: 环境光。**留在这一层而不是并进 lighting**:老场景的 content 里已经存着这个键,挪进去
    #: 就要迁移所有存量 JSON,而它换来的只是"看着更整齐"。加一个带默认值的新块不需要迁移 ——
    #: SceneOut 每次读都过一遍这个模型,老场景自动拿到默认的 lighting。
    ambient: float = Field(1.5, ge=0, le=10)
    lighting: SceneLighting = Field(default_factory=SceneLighting)

    @model_validator(mode="after")
    def valid_hierarchy(self):
        objects = {o.id: o for o in self.objects}
        if len(objects) != len(self.objects) or len({s.id for s in self.shots}) != len(self.shots):
            raise PydanticCustomError("scene_invalid", "Object and shot identifiers must be unique")
        for obj in self.objects:
            seen = {obj.id}
            parent = obj.parent_id
            while parent:
                if parent in seen or parent not in objects:
                    raise PydanticCustomError("scene_invalid", "Scene hierarchy contains a cycle or missing parent")
                if objects[parent].kind != "group":
                    raise PydanticCustomError("scene_invalid", "Only groups may contain objects")
                seen.add(parent)
                parent = objects[parent].parent_id
                if len(seen) > 16:
                    raise PydanticCustomError("scene_invalid", "Scene hierarchy is too deep")
        # 镜头指向的机位必须真的在场景里、而且真的是相机。删掉相机却留着引用它的镜头,
        # 就是一个打不开的场景 —— 而那时的报错会出现在视口里,离真正的原因很远。
        for shot in self.shots:
            camera = objects.get(shot.camera_id)
            if camera is None or camera.kind != "camera":
                raise PydanticCustomError("scene_invalid", "Every shot needs an existing camera object")
        return self
