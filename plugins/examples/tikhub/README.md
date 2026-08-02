# TikHub 自媒体数据

读抖音 / TikTok / 小红书 / B站 / 快手等平台的**公开**数据:作品详情、作者主页与作品列表、
关键词搜索、热榜。用于选题调研、对标账号分析、找素材灵感。

**这个插件没有一行代码。** TikHub 自己发了 MCP 服务,声明连上去就够了。

## 配置

插件页 → 凭据,填两项:

| 键 | 说明 |
| --- | --- |
| `TIKHUB_API_KEY` | 在 <https://user.tikhub.io> 生成 |
| `TIKHUB_PLATFORM` | 端点走哪个平台,见下表 |

填完自动拉一次工具清单;之后改平台记得点「刷新工具」。

平台取值:`douyin` `tiktok` `xiaohongshu` `bilibili` `kuaishou` `weibo` `zhihu` `instagram`
`youtube` `twitter` `threads` `linkedin` `reddit` `wechat` `others` `tikhub`。

**要同时用两个平台**:把这个目录复制一份,改掉 manifest 里的 `id` 和 `name`,两个插件各填各的平台。
一个插件对应一个 MCP 端点 —— 这是 MCP 的形状,不是这里的限制。

## 为什么从"自己写脚本"改成了"接 MCP"

上一版是个 Python 脚本,对外只给一个通用的 `tikhub_fetch(path, params)`:路径由调用方自己
从文档里找。那是在没有别的选择时的写法 —— TikHub 跨十几个平台上百个端点,在插件里抄一份
清单必然烂掉,所以干脆不抄。

但 TikHub 本来就有 MCP 服务(`https://mcp.tikhub.io/{平台}/mcp`,Bearer 鉴权)。接上去之后:

- 工具清单**从服务现拉**,每个工具带自己的名字、说明和入参模式 —— 模型不用再猜路径。
- 服务加了新端点,点一下「刷新工具」就有,不用改插件、不用发版。
- 插件目录里一行代码都没有,也就没有代码会烂。

再写一层脚本去把 stdin 的 JSON 翻译成一次 HTTP 调用、再把结果翻译回 stdout,是在重新实现
一个已经存在的东西。

## 工具太多怎么办

一个平台的端点可能有几十个,全部进智能体的工具表会挤掉内置能力,而且每一轮对话都要为那几十条
描述付 token。manifest 里的 `tools` 是**白名单**:

```jsonc
"tools": [
  { "name": "fetch_one_video", "read_only": true },
  { "name": "fetch_user_post_videos", "read_only": true }
]
```

不写就是全出。名字以插件页「刷新工具」后列出的为准。

顺带一提 `read_only`:标了的工具子智能体才能用。默认不标 —— 插件跑的是别人的服务,
没有确认门也照样能发请求,宁可让子智能体少一个工具。

Sources: [TikHub MCP](https://tikhub.io/mcp) · [TikHub API 文档](https://docs.tikhub.io/)
