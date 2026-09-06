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


class SceneObject(SceneValue):
    id: Identifier
    name: str = Field("Object", max_length=160)
    kind: Literal["box", "sphere", "cylinder", "plane", "room", "stairs", "group", "model", "light"]
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

    @model_validator(mode="after")
    def model_required(self):
        if self.kind == "model" and not self.model_id:
            raise PydanticCustomError("scene_invalid", "Model objects require an imported model_id")
        return self


class CameraFrame(SceneValue):
    time: float = Field(0, ge=0, le=120)
    position: Vec3 = (8, 5, 8)
    target: Vec3 = (0, 1, 0)
    fov: float = Field(45, ge=10, le=120)

    @model_validator(mode="after")
    def distinct_target(self):
        if sum((a-b)**2 for a, b in zip(self.position, self.target)) < .000001:
            raise PydanticCustomError("scene_invalid", "Camera position and target must differ")
        return self


class SceneShot(SceneValue):
    id: Identifier
    name: str = Field("Shot", max_length=160)
    duration: float = Field(5, ge=.1, le=120)
    aspect: Literal["16:9", "9:16", "1:1"] = "16:9"
    easing: Literal["linear", "smooth"] = "smooth"
    frames: list[CameraFrame] = Field(default_factory=lambda: [CameraFrame()], min_length=1, max_length=100)

    @model_validator(mode="after")
    def ordered_frames(self):
        times = [f.time for f in self.frames]
        if times[0] != 0 or times != sorted(set(times)) or times[-1] > self.duration:
            raise PydanticCustomError("scene_invalid", "Camera frames must begin at 0 and increase within shot duration")
        return self


class SceneContent(SceneValue):
    version: Literal[1] = 1
    objects: list[SceneObject] = Field(default_factory=list, max_length=500)
    shots: list[SceneShot] = Field(default_factory=lambda: [SceneShot(id="camera-1")], min_length=1, max_length=32)
    background: str = Field("#20242c", pattern=r"^#[0-9a-fA-F]{6}$")
    ambient: float = Field(1.5, ge=0, le=10)

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
        return self
