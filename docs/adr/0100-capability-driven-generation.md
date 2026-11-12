# 0100 能力驱动的生成网关

- 状态：接受，分阶段实施
- 日期：2026-11-12

## 背景

MosaelCloud 目前只支持 OpenAI 兼容对话：

- 供应商 `protocol` 只有 `openai`
- 模型 `kind` 只有 `chat`
- 价格只有每千输入 / 输出 token
- 网关只有 `/gateway/v1/chat/completions`

图片、视频、语音的交互和计费都不同。继续按业务名词加枚举，会在核心层积累
`if kind == "video"`、`if provider == "kling"` 之类的分支。

## 决策

把「交互形态」「能力」「计量维度」拆成三个正交轴：

- `interaction`: `stream` / `job`
- `capability`: 受控 JSON Schema，描述输入、输出、限制和默认值
- 价格：`cloud_model_price_components` 按 `unit` 拆行

供应商只保存凭据、端点、`adapter` 和配置；一个供应商可以提供多种模型。厂商差异收敛到
adapter 与 capability，核心不判断厂商名称。

### 数据

- `CloudProvider.adapter`: `openai` / `volcengine_ark` / `kling` 等注册表 key
- `CloudGatewayModel.interaction`: `stream` / `job`
- `CloudGatewayModel.capability`: 能力 schema
- `CloudModelPriceComponent`: `token_input` / `token_output` / `image` / `second` / `request`
- `CloudGenerationJob`: 通用异步任务（下一阶段）
- `CloudMediaArtifact`: 结果对象存储（下一阶段）

### 适配器

```text
StreamAdapter: stream(request, capability) -> events
JobAdapter:    submit() / poll() / cancel() / parse_webhook()
```

adapter 只描述“怎么和上游说话”，不负责积分换算；计费由 `usage facts × price components` 统一处理。

## 迁移顺序

采用 expand / migrate / contract，不做双读：

1. **expand**：新增 `adapter`、`interaction`、`capability`、price components，回填现有数据；旧列暂留但新代码不读。
2. **migrate**：聊天网关、管理台、CLI 全部切到新字段；旧列保持不再写入。
3. **contract**：删除 `protocol`、`kind`、`input_per_1k`、`output_per_1k` 和旧 CHECK。
4. 加通用 job / worker / artifact / billing，再接图片与视频 adapter。

## 后果

- 新增模态不需要改核心表；新增厂商只注册 adapter。
- 旧聊天立即保持原接口，只换内部字段。
- 迁移窗口内存在旧列但代码不读取，没有兼容分支。
- 图片/视频结果必须落对象存储，不能直接转发供应商临时 URL。
- 异步任务必须支持幂等、预占、取消、超时、回调验签和崩溃恢复。
