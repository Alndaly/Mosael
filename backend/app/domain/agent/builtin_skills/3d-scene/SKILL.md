---
name: 3d-scene
description: "布置 3D 场景(物体、材质、灯光、镜头)和在用户的 Blender 里给场景建模型的做法:读最新版本再改、改完看一眼、一次只建一个部件。用户要搭场景、摆镜头、建道具或家具、导出首尾帧和运镜参考时,先读它。"
metadata:
  mosael-title: "3D 场景与建模"
---

# 3D 场景与建模

## 场景:读、改、看

工具是 `list_scenes` / `get_scene` / `create_scene` / `edit_scene` / `view_scene`。

1. 先读取最新 revision,再修改对象、材质、灯光或镜头。
2. 改完用 `view_scene` **看一眼**再继续:`shot` 看构图,`overview` / `top` 看布局,`front` / `side` 看高度。
   物体穿地、悬空、互相穿插、挡住门口,数字上看不出来,画面上一眼就能看到。发现问题就改,改完再看。
3. 位置单位米,旋转单位度;不能虚构导入模型的 `model_id`。
4. 镜头插值不自动避障,设计穿门路径时检查空间尺寸。

## 在 Blender 里建模

需要基本体拼不出来的造型(建筑细节、道具、家具、机械)时,在用户的 Blender 里建模:

1. `blender_inspect` 看结构。
2. `blender_execute` 一次只做一个部件(bpy / bmesh / 修改器 / 材质,米制真实尺寸,物体起清楚的名字)。
3. 每步之后 `blender_look` 看一眼再继续。
4. 满意后 `blender_import_to_scene` 收进 Mosael 场景。

不要删改不是你建的物体。它是实际可编辑的几何体,不是视频生成提示词。建模使用当前用户选择的对话模型,不绑定某个模型。

## 交给视频生成

导出首尾帧或参考视频(`render_scene_references`)后,再由用户选择支持相应输入的视频模型;不要承诺生成的视频严格复现轨迹。
