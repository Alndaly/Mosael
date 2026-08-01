# TikHub 自媒体数据(插件示例)

读抖音 / TikTok / 小红书 / B站 / 快手等平台的**公开**数据:作品详情、作者作品列表、搜索、热榜。
用于选题调研、对标账号分析、找素材灵感。

## 配置

```bash
cp config.example.json config.json   # 然后填入你的 TikHub API Key
```

`config.json` 已被 .gitignore 忽略。

**为什么 Key 放在插件目录里而不是 Open Studio 的设置页**:插件运行时只向子进程透传
`PATH` / `HOME` / `LANG`,不给任何应用凭据(见 `backend/app/domain/plugins/runtime.py`)。
这是有意的隔离——插件因此绕不过确认卡与权限系统。代价是插件自己的凭据得自己管。
应用侧的插件凭据托管还没做,那是这套插件体系下一步该补的东西。

## 工具

| 工具 | 说明 |
| --- | --- |
| `tikhub_quota` | 查 Key 是否有效、还剩多少额度。配完先跑这个。 |
| `tikhub_fetch` | 调任意只读端点。`path` 取自 [TikHub 文档](https://docs.tikhub.io),`params` 是该端点的查询参数。 |

**为什么不为每个平台写专用工具**:TikHub 跨十几个平台、上百个端点,而且各平台的 App/Web
版本还在迭代(抖音已到 App V3)。在插件里抄一份端点清单,等于把一个每月都在变的东西冻住——
它会烂,而且烂得很安静。`path` 直接取自 TikHub 自己的文档,那份永远是最新的。

**只允许 GET**。TikHub 也有写类接口(投放、下单),但一个「读数据」的插件不该顺手具备那些
能力;真要用,那属于另一个插件、另一次授权。

## 示例

```jsonc
// 查额度
{ "tool": "tikhub_quota", "input": {} }

// 取一条抖音作品(路径以 TikHub 文档为准)
{ "tool": "tikhub_fetch", "input": { "path": "/api/v1/douyin/web/fetch_one_video", "params": { "aweme_id": "7372484719365098803" } } }
```
