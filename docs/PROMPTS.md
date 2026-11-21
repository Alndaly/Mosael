# Prompt 设计与契约

Prompt 不是一段随手写的角色介绍。凡是要模型产出一个动作、一个结构化结果或一次授权判断的地方，至少要回答下面几件事。

## 硬规则

1. **标识符逐字使用。** 工具名、技能 ref、字段名从工具定义 / 技能目录来，不由模型或文案作者拼接。插件技能必须写成 `插件 id:技能名`，例如 `dev.mosael.comfyui:comfyui-workflows`。
2. **事实有来源。** 只允许使用输入里给出的事实；画面外的人物、听不清的台词、没有发生过的数据不补。推断要标明，材料没覆盖到就说不知道。
3. **输出有契约。** 要 JSON 就写清字段、类型、上限和失败重试；要人话就写清长度、语气和不要做什么。只写“返回 JSON”不算契约。
4. **不可信内容要隔离。** 网页、文档、工具返回、用户素材里的指令只是资料，不是系统指令。会自动执行写操作的地方尤其要把这一条写死。
5. **失败要能恢复。** 结构校验失败时把错误回喂一次；模型无法判断时 fail closed；长错误保留根因。
6. **上下文分层。** 系统提示是硬约束；页面上下文描述当前界面与对象；用户消息决定这一轮任务。页面上下文不能靠“写在用户消息前面”获得系统级权威。

## 当前入口

| 入口 | 位置 | 备注 |
|---|---|---|
| 主智能体 system prompt | `backend/app/domain/agent/prompt.py` | 有 5,000 字符棘轮；新增长期规则优先放进技能目录或场景模块 |
| 技能目录 | `backend/app/domain/agent/skills/runtime.py` | 列出精确 ref；插件 ref 格式在这里再次声明 |
| 素材分析 | `backend/app/domain/analysis/service.py` | 系统提示区分观察 / 推断，禁止补画面外细节 |
| 发布文案 | `backend/app/domain/publish/copy.py` | 平台、标题上限、事实边界、标签规则；前端把平台与上限带进 brief |
| 工作流 AI 编辑 | `backend/app/domain/workflows/ai_edit.py` | 节点注册表 + 校验失败回喂 |
| 放行判断者 | `backend/app/domain/agent/judge.py` | 不看对话、参数不可信、fail closed |
| 逐镜描述 | `backend/app/domain/shots/describe.py` | 受控词表 + 代码对账 |
| 场景上下文 | 前端 i18n 的 `*AgentContext` | **已知债**：仍由前端拼接；后续应改为后端按会话 place / 工具集组装，并只把事实交给界面 |

## 新增或修改 Prompt 时

- 在 `backend/tests/test_prompt_contracts.py` 补一条契约断言，至少覆盖标识符、事实边界或输出结构中的一项。
- 不把工具手册复制进主 system prompt；工具 description 负责细节，主提示负责选择原则。
- 不在 prompt 里写死会变的技能名/工具名清单；从 catalog / manifest 读取。
- 主提示长度变化要跑 `tests/test_agent_skills.py::test_系统提示瘦身_搬走的做法在内置技能里`。
