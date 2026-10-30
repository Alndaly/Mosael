# 上游供应商与通道分层

- 状态：已采纳
- 日期：2026-10-30
- 关联：ADR 0088 §4

## 背景

ADR 0088 第一版把「端点、Key、上游模型名、优先级」全塞在一条 `cloud_upstream_channels` 里。实际配置同一个供应商（同一端点、同一把 Key）挂多个模型时，
每加一个模型都要复制一遍 Key；换 Key 要逐条通道改，漏一条就会出现新旧凭据并存。管理端也无法回答「这把 Key 还挂在哪些地方」。

## 决策

拆成两层：

| 层 | 表 | 负责 |
| --- | --- | --- |
| 供应商 | `cloud_upstream_providers` | 名称、协议、端点、加密 Key、启用状态、备注 |
| 通道 | `cloud_upstream_channels` | 对外模型 → 供应商 + 上游模型名、优先级、冷却、启用、备注 |

- **凭据只存在供应商一层**。通道不再有 `base_url` / `api_key_encrypted` / `protocol`。
- 网关路由先按模型找启用的通道，再 join 供应商；通道或供应商任一停用，该路由都不可用。
- 冷却仍留在通道上：429 / 5xx 通常只说明「这个模型经这个供应商」此刻不行，不连带停掉同供应商的其他模型。
- 管理端新增「上游供应商」页；通道表单只选供应商和上游模型名。换供应商 = 新建通道，不原地改路由历史。
- 命令行拆成 `provider-add` / `provider-list` 与 `channel-add --provider <id>`；Key 仍只从环境变量或终端读取。

## 迁移

`0016_upstream_providers` 将旧通道按 `(protocol, base_url, api_key_encrypted)` 去重生成供应商，并把每条通道指过去，
然后删除通道上的旧列。已有数据不丢；同一端点同一把 Key 的多条通道共享一个供应商。降级按通道回填供应商字段，再删供应商表。

## 不选的做法

- **通道里保留旧列并双写**：会产生两套真相，换 Key 永远可能漏；也违反「不留兼容旧包袱」。
- **供应商按 `base_url` 唯一**：同一端点可能轮换多把 Key（额度隔离），唯一约束会把正常的双账号配置挡掉。
- **把冷却放到供应商**：一个模型的 429 会误伤同供应商下其他模型；需要更细的健康度时再加供应商级熔断，而不是现在合并。

## 影响

- `catalog.channels_in_order` 返回 `(channel, provider)` 路由；网关发请求时必须显式传 `upstream_model` 与供应商 Key。
- 管理 API 增加 `/admin/providers`；`/admin/channels` 的创建体改为 `provider_id`，不再接收 Key。
- `cloud/README.md`、`docs/CLOUD_ACCOUNTS.md` 的命令与接口表同步更新。
