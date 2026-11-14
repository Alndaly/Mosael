"""「这一镜的机位」—— 镜头从哪个方向拍主体。词表只在这里(ADR 0091)。

三处说的是同一件事、读的是这一份:

- 姿势资产的参考图按机位标(`catalog.ROLES_BY_KIND["pose"]`);
- 3D 场景的镜头标着它(`scenes.types.SceneShot.shot_angle`);
- 生成时用姿势参考,只发和这一镜同机位的那张(`PoseUse.shot_angle`,见 `entities.mentions`)。

**它不是故事板里的 `camera_angle`**(`workflows.templates.schemas.CAMERA_ANGLES`:eye level / high angle /
dutch angle……,写给生成模型看的摄影术语)。这里是主体朝向加俯仰的六档,用来挑同一个姿势的哪一张图。

叶子模块:只有类型,不 import 应用里的任何东西 —— 场景的值类型、资产目录、接口模型都从这里取,彼此不绕。
"""

from __future__ import annotations

from typing import Literal, get_args

ShotAngle = Literal["front", "three_quarter", "side", "back", "high_angle", "low_angle"]

#: 机位的先后就是界面下拉里的先后。名字是文案 `entityRole_<机位>`(和参考图角度共用一份)。
SHOT_ANGLES: tuple[str, ...] = get_args(ShotAngle)

__all__ = ["SHOT_ANGLES", "ShotAngle"]
