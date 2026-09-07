# Blender MCP for Mosael

Connect your chosen Mosael agent to local Blender, then exchange models and camera shots from the **3D 场景 → Blender** menu. This plugin uses the community [Blender MCP](https://github.com/ahujasid/blender-mcp) server, pinned to **1.9.1**. It does not require Astra or a separate modeling-model API key.

## 安装

1. 安装并打开 Blender。本次实际验证版本为 **Blender 5.2.0 LTS**；其他版本请先用小场景验证。Blender 与 Mosael 桌面后端必须在同一台电脑。
2. 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，确保 Mosael 后端可以找到 `uvx`。安装此版本配套的 Add-on：

   ```sh
   uvx --python 3.11 blender-mcp==1.9.1 install-addon
   ```

   如电脑有多个 Blender 版本，可通过 `--addons-dir` 指定对应版本的 `scripts/addons` 目录。安装后在 Blender 的 Preferences → Add-ons 中启用 **MCP for Blender**。这是社区插件，不是 Blender 官方插件。
3. 将本目录复制到 Mosael **数据目录的 `plugins/blender/`**，在插件页面点击扫描。默认数据目录是 `~/.mosael`；自定义部署以 `MOSAEL_DATA_DIR` 为准。也可在发布包包含 `dev.mosael.blender.zip` 后从插件市场安装。
4. 创建 Blender MCP 接入，保留本机主机地址和默认端口 `9876`（若修改，须与 Blender 面板一致），授予清单列出的权限并启用。插件默认关闭上游遥测。
5. 打开 3D 场景，点击工具栏 **Blender → 检测**。开发模式需以 `MOSAEL_LOCAL_DESKTOP=1` 启动本机后端；不要对远程部署启用此开关来绕过本机限制。

首次启动会下载固定版本的 Python / MCP 包，可能需要等待。该 Add-on 在 Blender 图形界面中运行，不支持用 `--background` 替代交互连接。

## 使用

- **发送当前场景**：等待保存完成，将当前可见模型、支持的材质/灯光和全部镜头发到一个独立的 `Mosael · 场景名称` Blender Scene，不清空其他 Scene。选中的镜头成为 Blender 活动相机。
- 在 Blender 中编辑模型、修改器、材质或相机。也可以在 Mosael 的建模助手中，使用已启用的 Blender 插件工具操作该 Scene；智能体模型由用户选择。
- **接收 Blender 修改**：读取对应发送记录的 Scene，创建新的 Mosael 场景。模型作为一个整体 GLB 导入；相机回传为可编辑的镜头关键帧。原 Mosael 场景及版本保持不变。
- **打开接收的场景**：检查模型和镜头，继续使用已有的镜头预览、首尾帧及参考视频生成流程。
- **.blend**：下载最近接收的工程；尚未接收时下载发送时的工程。文件包含该 Scene 及其依赖，不包含无关 Scene。新增的外部纹理等链接资源应在 Blender 中自行打包或一并保存。

发送记录保存在本机数据目录，刷新应用后仍可接收。Blender 重启后，需要重新打开对应 `.blend`，或再次发送场景。接收定位依据 Scene 的 `mosael_transfer_id` 属性，改名不会影响定位；删除该属性或 Scene 后需要重新发送。

## 当前范围

- 发送以 30 fps 烘焙镜头运动及垂直 FOV。接收按镜头时长最多采样 100 帧；长镜头会显示检查提示。
- 支持无 roll 的透视镜头；正交/倾斜镜头暂保留发送时版本并明确提示。接收沿用源镜头的名称、时长和比例；新建的 Blender 相机不会自动变成 Mosael 镜头。
- 接收的是第一帧几何快照，并尽可能应用修改器。复杂节点材质、物体动画、世界光和 Area light 无法通过 GLB 完整还原；完整编辑信息留在 `.blend`。环境背景/环境光沿用发送快照。
- 场景文件最大 25 MB，接收沿用 Mosael 模型复杂度和外部资源校验。大型场景应拆分后传输。
- 本阶段没有自动逐物体合并、持续双向同步或 Cycles 后台渲染队列。

`execute_blender_code` 能执行本机 Blender Python，拥有 Blender 进程的文件权限；它不是沙箱。仅启用信任的接入。界面的同步 API 不接受任意 Python 或自定义文件路径，使用固定脚本，并经过用户、工作区和插件授权检查。

## English quick start

Install `uv`, run `uvx --python 3.11 blender-mcp==1.9.1 install-addon`, and enable **MCP for Blender** in Blender. Copy this plugin folder into the Mosael data directory under `plugins/blender`, scan it in Plugins, create a connection, grant its declared permissions, and enable it. Keep Blender and the desktop backend on the same computer.

Use **3D scene → Blender** to check the connection, send a saved scene, and receive edits into a separate new scene. Cameras return as sampled editable shots; geometry returns as one GLB model. Download the associated `.blend` project for native editing. Agent tools work with the model you choose. See the limitations above before using large scenes or advanced Blender animation/materials.
