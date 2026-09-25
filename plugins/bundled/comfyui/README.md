# ComfyUI

把一台 ComfyUI(本机或局域网里的另一台)接成 Mosael 的图像 / 视频生成供应商。**随 Mosael 一起发**,
装好就在插件页里,不用去市场找。

## 怎么接

1. 插件页 → ComfyUI → 「新建连接」,填服务器地址(本机默认 `http://127.0.0.1:8188`)。
2. 授权 `network:comfyui`,打开连接。
3. 它在 ComfyUI 里**保存的每张工作流**会作为一个模型出现在 AI 工作台、画板、工作流「AI 生成素材」节点的
   模型选择器里;ComfyUI 里新存了工作流,在插件页点「刷新模型」。

多台服务器就建多个连接,各自一串模型。

## 一张工作流变成一个模型时

| 工作流里的东西 | 在 Mosael 里 |
| --- | --- |
| 采样器 / 引导器上游写提示词的节点(CLIPTextEncode 及 Flux、SDXL 的变体) | 主提示词、反向提示词 |
| 采样器的 seed、RandomNoise 的 noise_seed | 「随机种子」(不填每次随机) |
| 生成画布的节点(EmptyLatentImage、Wan / Hunyuan 的视频潜空间节点…)的宽高 | 「尺寸」(不选就用工作流自己的) |
| 其余可调的字面量输入(步数、CFG、采样器、checkpoint、帧数…) | 参数表里的一项,名字是「节点标题 · 输入名」,范围和可选值来自 ComfyUI |
| LoadImage 节点 | 参考图槽位;视频图里接到 `start_image` / `end_image` 的是首帧 / 尾帧 |
| 视频输出节点(VHS_VideoCombine、SaveVideo…) | 这是一个视频模型 |

另有两个模型:**内置文生图**(服务器上至少有一个 checkpoint 时)和**API 模板**(连接配置里粘贴了
「导出 (API)」的 JSON 时,`{{prompt}}` `{{negative}}` `{{seed}}` `{{width}}` `{{height}}` `{{steps}}`
占位符照旧)。

## 进度、取消、重启

- 进度来自 ComfyUI 的 WebSocket:哪个节点在跑、采样器第几步。连不上就退回轮询。
- 在任务中心取消,插件会让 ComfyUI 停下**这一个**任务(在跑的 interrupt,在排队的从队列删掉),
  不会掐掉同一台机器上别人的任务。
- Mosael 重启时正在跑的生成会接着等(按任务号),不会重新提交。

## 代码

`tools/` 只用 Python 标准库:`graph.py`(UI 图 → API 图、看出参数和槽位、填图、收产出)、`models.py`
(有哪些模型)、`run.py`(一次生成)、`comfy_http.py` / `ws.py`(和 ComfyUI 说话)。
协议见 Mosael 仓库的 `docs/PLUGIN_MANIFEST.md`「替宿主做生成」。
