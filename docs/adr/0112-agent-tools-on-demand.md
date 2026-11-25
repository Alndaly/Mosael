# 0112 工具按需检索:主工具表只放常用项,桌面 / 浏览器由 tool_search + run_tool 够到

- 状态：已采纳
- 日期：2026-11-25
- 相关：ADR 0044（工具跟着地点走）、ADR 0084（插话边界）、`agent-sidecar/src/tools.ts`、`domain/agent/tools/manifest.py`

## 背景

工具注册表已经 **184 个**，其中 147 个是「通用、哪儿都发」。工具定义每轮重发，按 3.5 字符 / token 估算约 5 万 token；桌面控制（26 个）和浏览器（17 个）这两族占了 43 个，但绝大多数轮次用不上。模型在 150+ 个名字里选工具，也更容易选错近似的名字（`edit_project` / `edit_timeline` / `edit_scene`）。

把这些工具从主工具表拿掉不能靠「猜它这次会不会用」；拿掉之后又必须够得着，否则就是能力静默消失。

## 决定

### 1. 主工具表只放「直接可见」的工具

`agent-sidecar/src/tools.ts` 过滤掉 `computer_` / `browser_` 两族，并在列表末尾放三个本地工具：

- `tool_search(query)`：只读，返回最多 8 个按需工具的**完整参数 schema**、确认门控和只读标记；
- `run_tool(name, arguments)`：执行 `tool_search` 找到的任意工具；确认 / 选择卡沿用原有阻塞协议；
- `run_read_tool(name, arguments)`：只允许 `read_only` 的目标，给子智能体用。

子智能体的 `readOnlyTools` 因此拿到 `tool_search` + `run_read_tool` + 原有只读工具，仍然能查浏览器页面（如果有会话）和桌面状态，但不能借 `run_tool` 获得写权限。

### 2. 三个入口共用同一份执行路径

`executeSpec` 负责补工作区、发 `/api/agent/tools/{name}`、处理 `confirmation` / `awaits_answer` / 图片。主工具表和 `run_tool` 不再各写一份等待逻辑；确认卡上记的 toolCallId 仍是发起这次调用的那个。

### 3. 水位按真正发出去的那份算

`domain/agent/tools/manifest.visible_tool_specs` 与 sidecar 使用同一组前缀；`host.tool_definition_tokens` 只量可见工具。`/api/agent/tools` 仍返回完整清单（sidecar 需要用它建 `byName` 表），但模型的工具定义不再包含那 43 个。

改前缀时两处必须一起改；`agent-sidecar/test/on-demand-tools.test.mjs` 钉住「按需族不进主表、search 找得到、run_tool 调得到、子智能体只能跑只读」。

## 后果

- 主模型每轮少背 43 个定义；按需工具需要多一轮 `tool_search`，但只在使用时付。
- `run_tool` 的调用在对话里显示成一次通用工具调用，而不是目标工具自己的卡；确认卡和结果仍属于目标工具。
- 如果某类工具需要经常用，应该进主表（或按地点成为 kit），而不是让模型每轮都搜一次。
