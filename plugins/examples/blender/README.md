# Blender MCP for Mosael

Connect your chosen Mosael agent to local Blender, then exchange models and camera shots from the **3D 场景 → Blender** menu. This plugin uses the community [MCP for Blender](https://github.com/ahujasid/mcp-for-blender) server (published as `mcp-for-blender`; called `blender-mcp` before 2.0), pinned to **2.0.3**. It does not require Astra or a separate modeling-model API key.

## 安装

1. 安装并打开 Blender。本次实际验证版本为 **Blender 5.2.0 LTS**；其他版本请先用小场景验证。Blender 与 Mosael 桌面后端必须在同一台电脑。
2. 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，确保 Mosael 后端可以找到 `uvx`。安装此版本配套的 Add-on：

   ```sh
   uv run plugins/examples/blender/install-extension.py
   ```

   装成 **Extension**(Blender 4.2+ 的新体系)。上游只发旧式单文件 add-on，而 Blender 5.x 的
   `Preferences → Add-ons` **默认只列 Extensions** —— 直接跑上游的 `install-addon` 会出现
   「文件明明在、界面上却找不到」。脚本从上游那份重新生成，因此升级时重跑一遍即可；它同时会
   删掉同版本的 legacy 副本，两份并存会抢同一个 9876 端口。

   默认装到所有 4.2 及以上的 Blender；`--blender 5.2` 只装一个，`--list` 先看会装到哪里。
   仍要用旧体系(Blender 4.2 以下)时才跑 `uvx --python 3.14 mcp-for-blender==2.0.3 install-addon`。

   装好后在 Blender 的 Preferences → Add-ons 中搜 MCP，勾选 **MCP for Blender**。这是社区插件，
   不是 Blender 官方插件。
3. 将本目录复制到 Mosael **数据目录的 `plugins/blender/`**，在插件页面点击扫描。默认数据目录是 `~/.mosael`；自定义部署以 `MOSAEL_DATA_DIR` 为准。也可在发布包包含 `dev.mosael.blender.zip` 后从插件市场安装。
4. 创建 Blender MCP 接入，保留本机主机地址和默认端口 `9876`（若修改，须与 Blender 面板一致），授予清单列出的权限并启用。插件默认关闭上游遥测。
5. 打开 3D 场景，点击工具栏 **Blender → 检测**。开发模式(`pnpm dev`)已默认带上 `MOSAEL_LOCAL_DESKTOP=1`——dev 后端本来就和你的文件在同一台机器上；想模拟团队服务器时用 `MOSAEL_LOCAL_DESKTOP=0 pnpm dev`。**不要对远程部署启用此开关**来绕过本机限制：互通要把 `.blend` 写到本机磁盘再交给同机 Blender 打开，服务器上的后端够不到你的电脑。

首次启动会下载固定版本的 Python / MCP 包，可能需要等待。该 Add-on 在 Blender 图形界面中运行，不支持用 `--background` 替代交互连接。

## 使用

- **从 Blender 获取**（3D 场景列表页）：把 Blender 里**当前打开的那个场景**取成一个新的 Mosael 场景，不要求先发送过 —— 手上已经有 Blender 工程时从这里进来。只取几何体：Mosael 的镜头要知道「看向哪里」，而那个距离只有从 Mosael 发送过去的相机才带着，任意 Blender 相机无从得知，所以相机不一起取回（有相机会明确提示），镜头在 Mosael 这边重新设计。
- **发送当前场景**：等待保存完成，将当前可见模型、材质/灯光和全部镜头发到一个独立的 `Mosael · 场景名称` Blender Scene，不清空其他 Scene。选中的镜头成为 Blender 活动相机。GLB 由**后端**按已落库的那一版生成（不再由浏览器导出上传），所以智能体也能发送——见 `blender_send_scene`。导入的 GLB 模型各自作为文件导入，挂在场景里对应的位置上。
- 在 Blender 中编辑模型、修改器、材质或相机。也可以让 Mosael 的智能体（建模助手或对话页，模型由你选择）直接在 Blender 里建模，见下一节。
- **接收 Blender 修改**：读取对应发送记录的 Scene，**更新当前场景**。模型作为一个整体 GLB 导入；相机回传为可编辑的镜头关键帧。它是当前场景上的一次普通改动 —— ⌘Z 可撤销，接收前的那一版也留在版本记录里。
- **另存为新场景**：想让原场景一个字节都不动时用它，接收结果会去到一个独立的新场景（此前这是唯一的接收方式）。接着用「打开接收的场景」检查模型和镜头，继续走已有的镜头预览、首尾帧及参考视频生成流程。
- **.blend**：下载最近接收的工程；尚未接收时下载发送时的工程。文件包含该 Scene 及其依赖，不包含无关 Scene。新增的外部纹理等链接资源应在 Blender 中自行打包或一并保存。

发送记录保存在本机数据目录，刷新应用后仍可接收。Blender 重启后，需要重新打开对应 `.blend`，或再次发送场景。接收定位依据 Scene 的 `mosael_transfer_id` 属性，改名不会影响定位；删除该属性或 Scene 后需要重新发送。

## 让智能体在 Blender 里建模

连接可用时，智能体自带四个 Blender 工具，作用在**你此刻在 Blender 里开着的那个场景**：

- `blender_inspect`：列出物体、类型、层级、变换、尺寸、修改器与材质。只读。
- `blender_look`：自动取景渲几张图（俯瞰 / 正面 / 侧面 / 背面 / 顶视 / 场景相机）作为视觉输入交给模型。`solid` 用 Workbench，约一秒；`rendered` 用 EEVEE 看真实材质。渲染设置临时修改，渲完还原。只读。
- `blender_execute`：执行模型写的 `bpy` 建模代码——bmesh、修改器、曲线、几何节点、材质都可以用。**走确认卡**：Blender 的 Python 不是沙箱。执行前压一个撤销点，可以在 Blender 里 ⌘Z；代码报错时 traceback 交回给模型，由它修改后重试。自动放行里有独立的「Blender 建模」一档，放开它不会连带放开「不隔离执行代码」。
- `blender_send_scene`：把 Mosael 场景（白模几何、分组、材质、全部镜头）发进 Blender，和界面上的「发送当前场景」同一条路。
- `blender_import_to_scene`：把整个 Blender 场景、或按名字挑出的物体（含子物体）作为一个模型物体加进 Mosael 场景。

建模循环是「执行一小步 → 看一眼 → 修正」。模型本身能不能看图决定了第二步是否生效；不支持看图的模型收不到截图，会得到一句说明。

插件自带的 `execute_blender_code` 是不经确认的原始入口。0.2.0 起它在清单里标为 `internal`：只供 3D 场景互通的固定脚本使用，不出现在插件页的勾选列表里，智能体和工作流都调不到——否则它就是绕开确认卡的后门。更新到 0.2.0 需要重新复制插件目录或从插件市场更新。

上游其余的工具按后果申报:只读的(查看场景 / 物体、视口截图、`describe_node_type` 与 `bpy_api_lookup` 查写法、各集成的 `get_*_status`)智能体直接调;改场景、下载资产、导出文件、调 Hyper3D / 混元生成的,智能体调用前先出确认卡。

## 当前范围

- 发送以 30 fps 烘焙镜头运动及垂直 FOV。接收按镜头时长最多采样 100 帧；长镜头会显示检查提示。
- 支持无 roll 的透视镜头；正交/倾斜镜头暂保留发送时版本并明确提示。接收沿用源镜头的名称、时长和比例；新建的 Blender 相机不会自动变成 Mosael 镜头。
- 接收的是第一帧几何快照，并尽可能应用修改器。复杂节点材质、物体动画、世界光和 Area light 无法通过 GLB 完整还原；完整编辑信息留在 `.blend`。环境背景/环境光沿用发送快照。
- 场景文件最大 512 MB，接收沿用 Mosael 模型复杂度（5000 节点 / 2000 网格）和外部资源校验。真撞上时先试压缩：Mosael 能解 Draco、KTX2(Basis) 和 meshopt；再不行就隐藏用不到的物体、把贴图降到 2K，或拆成几份分别传输。
- 本阶段没有自动逐物体合并、持续双向同步或 Cycles 后台渲染队列。

Blender 里的 Python 拥有 Blender 进程的文件权限，不是沙箱。仅启用信任的接入。界面的同步按钮和智能体的查看、截图、导出都使用固定脚本，参数以数据传入，并经过用户、工作区和插件授权检查；只有 `blender_execute` 执行模型写的代码，而它必须经过确认卡或你明确设置的自动放行。

## English quick start

Install `uv`, run `uv run plugins/examples/blender/install-extension.py`, and enable **MCP for Blender** in Blender. The script installs it as an *extension* (Blender 4.2+), because upstream only ships a legacy add-on and Blender 5.x hides those by default — installing upstream's way leaves the file present but invisible in Preferences. Re-run it after upstream upgrades; it also removes the legacy copy, which would otherwise fight for the same port. Copy this plugin folder into the Mosael data directory under `plugins/blender`, scan it in Plugins, create a connection, grant its declared permissions, and enable it. Keep Blender and the desktop backend on the same computer.

Use **3D scene → Blender** to check the connection, send a saved scene, and receive edits back into the current scene as an undoable change (or into a separate new scene with **另存为新场景**). Cameras return as sampled editable shots; geometry returns as one GLB model. Download the associated `.blend` project for native editing. Agent tools work with the model you choose: `blender_inspect`, `blender_look` (rendered views the model can see), `blender_execute` (runs the model's `bpy` code after approval, with an undo step pushed first) and `blender_import_to_scene`. The plugin's raw `execute_blender_code` is marked `internal` (0.2.0): only the scene exchange's fixed scripts call it; agents and workflows cannot. See the limitations above before using large scenes or advanced Blender animation/materials.

## Mosael 1.2.0 的时间轨

相机与普通物体都在底部时间线中编辑；选中对象、移动播放头、调整姿态后按 **I** 插入关键帧。镜头通过 `camera_id` 选择机位，相机关键帧保存在该物体的 `track` 上。

发送边界会把相机轨道转换为 Blender 使用的逐镜头帧序列，空轨按固定机位发送；未填写的 FOV/目标使用机位自身值。首帧之前保持第一帧，不向外推算。接回时保留线性采样节奏，相机使用回传的世界坐标，不再引用已被整体模型替代的原组。

生成参考图可附带单独渲染的中性灰模；模型与参考帧导出会排除嵌套组内的编辑摄像机辅助物。Mosael 的普通物体动画仍不作为 Blender 原生动画轨往返，复杂动画应保留 `.blend` 工程。
