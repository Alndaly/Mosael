# 3D 场景:数据形状与几何契约

**用户怎么用这一页,看[使用指南](https://mosael.app/docs/guides/scenes)**(仓库里的源文件是
`website/content/docs/{zh,en}/guides/scenes.mdx`)。那边讲操作:观察方式、加物体、插关键帧、
生成素材、Blender 往返。这里只讲**代码这一侧的契约** —— 同一段操作说明此前在两个地方各写了
一份,写着写着就不是同一件事了(官网有缩略图那段、仓库有建模助手那段,谁也不知道另一边缺什么)。

## 数据形状

`SceneContent.objects` 里**相机和普通物体是同一种东西**,动画写在对象自己的 `track` 上;
`shots` 只说「用哪台机位、拍多久、什么画幅」,用 `camera_id` 指过去。见
[时间与相机设计记录](design/scene-time-and-cameras.md)。

- 位置单位米、旋转单位度,Y 轴向上,地面在 `y=0`;基本体站在自己的 `y=0` 上(球心在 `radius`)。
- 分组只带着孩子走,自己没有几何;相机和灯在**渲染与导出**里没有几何 —— 工作台画的机位模型
  和灯泡标记是编辑辅助物,不是场景内容。
- 导出走 `cloneSceneForExport`,把嵌套的编辑辅助物摘掉,不改实时场景。

## 同一份几何,三个消费者

工作台的 three.js(`frontend/src/features/scenes/sceneMeshes.ts`)、后端的白模渲染器
(`backend/app/domain/scene_render`)、以及发往 Blender 的 GLB(同一份 `meshes.py`)必须画出
同一个东西。人物多高、墙有多厚、运镜怎么缓动、色温换算成什么颜色 —— 任何一处对不上,
参考图、成片和 Blender 里的场景就是三个场景,而且**所有测试都还是绿的**。

一致性由 [`contracts/scene-3d-cases.json`](../contracts/scene-3d-cases.json) 钉住,两侧各跑一遍
(`scene3d.parity.test.ts` / `tests/test_scene_3d_parity.py`)。**改语义时先改语料**,看着两侧一起红,
再改两侧实现。

后端渲染器只渲白模(每个物体取自己的颜色做漫反射),导入的 GLB 渲不出来,`skipped_models`
如实报数。

## 智能体的工具

| 工具 | 作用 | 门 |
| --- | --- | --- |
| `get_scene` / `edit_scene` | 读场景、按 id 改物体与镜头(带 `base_revision` 的 CAS) | 无 |
| `view_scene` | 把场景渲成图**交给模型看**:`shot` 是机位构图,`overview`/`top`/`front`/`side` 自动取景 | 只读 |
| `blender_send_scene` | 把场景发进 Blender(GLB 由 `scene_render/gltf.py` 生成,不经浏览器) | 无 |
| `blender_inspect` / `blender_look` | 读 Blender 场景结构 / 渲几个角度给模型看 | 只读 |
| `blender_execute` | 在 Blender 里跑 `bpy` 建模代码 | 确认卡,`external` 档,自动放行里单独一档 |
| `blender_import_to_scene` | 把 Blender 里做好的东西作为一个模型物体加进场景 | 无 |

工具结果里的图片只在当轮上下文里保留最近几张,轮末不写进会话状态(见
`agent-sidecar/src/toolImages.ts`)。

## Blender 边界

发送时后端生成 GLB(物体、分组父子关系、PBR 材质、点光源),镜头由 worker 按 `shots` 另建成
真正的 Blender 相机并烘 30fps 关键帧;导入的模型各自作为文件导入,挂到 GLB 里给它留的空节点下。
接回时几何是**一个整体模型**,不是逐对象合并;相机回传最多采样 100 帧。

`domain/blender/worker.py` 跑在**用户的 Blender 里**,导不进本应用的任何模块 —— 参数一律以
JSON 数据传入(视角的角度也是),它只按发过去的数据干活。真 Blender 里的行为由
`tests/test_blender_worker_live.py` 验(本机没装 Blender 就跳过)。

设计背景见 [Blender 接入调研](design/blender-integration.md),安装见
[插件说明](../plugins/examples/blender/README.md)。

## 其他约束

- 模型导入:自包含 GLB 2.0 ≤512 MB、内嵌 glTF 2.0 ≤100 MB,支持 Draco/KTX2/meshopt;
  实时上限 5000 节点 / 2000 网格;不加载模型里声明的外部网址或本地路径。
- 每条轨最多 100 帧,镜头时长最多 120 秒。
- 保存是带修订的 CAS,冲突不静默覆盖;场景、模型、画板引用都验工作区归属。
