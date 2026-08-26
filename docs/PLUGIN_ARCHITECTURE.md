# 插件体系:包 / 实例 / 能力

> **已落地(v0.8.0)。** 这份文档留下的是**为什么长成这样** —— 目标模型、以及它替换掉的那个
> 错误模型。写插件怎么写见 [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md),用户视角见
> [插件指南](../website/content/docs/zh/guides/plugins.mdx);决策与被否掉的选项见
> [ADR 0005](adr/0005-plugin-package-instance-capability.md)。

## 改之前错在哪

三个故障,同一个病根:**把「一个包」和「一次接入」当成了同一个东西**。

| 症状 | 改之前的样子 | 病根 |
| --- | --- | --- |
| 节点面板显示「bilibili_web_fetch_one_video · TikHub 抖音数据」 | 包名写死在 manifest,平台却是运行时配置 | 身份来自配置,名字是常量 |
| 41 个工具挤满节点面板和智能体工具表 | MCP 报什么接什么,白名单要手写才生效 | 默认全暴露 |
| 想同时接 bilibili 和 douyin 要复制目录改 id | 一行 `plugins` 记录既是包也是接入 | 包 ≠ 实例 |

还有两处更细的错位(也一并修掉了):

- **配置被当成凭据**。`TIKHUB_PLATFORM` 本质是个枚举,却和 API Key 挤在同一张表、同一个密码框旁边。没有选项、没有校验,改了也不会改名字。现在配置与凭据是 `Field.secret` 的两侧:配置有类型、明文、参与显示名模板,凭据打码。
- **`manifest.tools` 一个字段三种语义**:进程类插件的完整声明 / MCP 插件的白名单 / MCP 插件的覆盖层。读的人得先知道 `kind` 才能理解这个字段。现在 `declare` 与 `overrides` 分开,语义各归各的。

## 现在的模型

```
PluginPackage  一个磁盘目录 + 一份 manifest。没有「启用」状态。
  └── PluginInstance  一次接入 = 配置 + 凭据 + 显示名 + 启用开关
        └── PluginCapability  这个实例的某个工具,暴不暴露由用户定
```

- 无配置的包(text-toolkit 这种)装上时自动建一个默认实例,用户感知不到多出一层。
- 有配置的包(TikHub)由用户「新建连接」,填一次配置 + 凭据得到一个实例;要第二个平台就再建一个,**不用碰磁盘**。
- 实例的显示名默认由模板生成(`TikHub · 哔哩哔哩`),用户可以改成自己的叫法。

## manifest 的形状

```jsonc
{
  "id": "dev.openstudio.tikhub",
  "name": "TikHub",                      // 包名,与任何一次接入无关
  "version": "1.0.0",

  "runtime": {                            // 怎么跑起来(原来的 kind + entry/mcp)
    "kind": "mcp",                        // "process" | "mcp"
    "transport": "http",
    "url": "https://mcp.tikhub.io/${platform}/mcp",
    "headers": { "Authorization": "Bearer ${api_key}" }
  },

  "instance": {                           // 一次接入长什么样
    "multiple": true,                     // 允许建多个;false = 只能有一个
    "name_template": "TikHub · {platform:label}",
    "config": [                           // 明文配置,有类型有选项
      { "key": "platform", "label": "平台", "type": "enum", "required": true,
        "options": [
          { "value": "bilibili", "label": "哔哩哔哩" },
          { "value": "douyin",   "label": "抖音" }
        ] }
    ],
    "credentials": [                      // 密钥,掩码回显
      { "key": "api_key", "label": "API Key", "help": "在 https://user.tikhub.io 生成" }
    ]
  },

  "tools": {                              // 能力策略,不再是"清单"
    "expose": "selected",                 // "selected"(默认) | "all"
    "recommended": ["bilibili_web_fetch_one_video", "bilibili_web_fetch_user_videos"],
    "overrides": {
      "bilibili_web_fetch_one_video": {
        "label": "B站作品详情",
        "read_only": true,
        "node": { "outputs": ["title", "owner", "stat"] }
      }
    }
  }
}
```

变化点:

- **`runtime`** 收口「怎么跑」,`instance` 收口「接一次要什么」,`tools` 收口「暴露什么」。三个字段三件事,读的人不用先看 `kind`。
- **`${platform}` / `${api_key}`** 从配置和凭据里按声明的 key 展开(小写、与声明同名)。进程类插件把两者都注入子进程环境(大写化),但 manifest 里不写环境变量名 —— 那是运行时细节。
- **`tools.overrides`** 是唯一的覆盖入口,`tools.recommended` 是首次启用时的默认勾选。白名单不再由「写没写 tools」隐式决定。

## 能力默认不暴露

`expose: "selected"` 是默认。首次启用实例时按 `recommended` 勾上;没有 `recommended` 就一个都不勾,插件页引导用户去选。

**为什么默认关**:节点面板和智能体工具表都是注意力稀缺的地方。四十个 `bilibili_web_fetch_*` 让面板要人从四十行里找一行,让每轮对话为四十条描述付 token,还挤占模型在内置工具之间的选择权。要人从四十个里挑出该关的三十七个,没有人会做 —— 默认值就是实际行为。

`expose: "all"` 留给工具本来就少的包(text-toolkit 两个工具,让用户逐个勾是无谓的仪式)。

## 命名空间

| 面 | 名字 | 为什么 |
| --- | --- | --- |
| 智能体工具 | `plugin__<实例id>__<工具名>` | 同一个包的两个实例是两套工具,模型要能分辨"从 B 站取"和"从抖音取" |
| 工作流节点类型 | `plugin.<包id>.<工具名>` | 工作流会被导出到别的机器,节点类型必须跨机器稳定 |
| 节点选哪个实例 | 节点 config 的 `instance_id` | 只有一个实例时自动填;缺实例时报「这个节点需要一个 X 连接」 |

节点类型绑包、实例放进 config,是这两条约束唯一的交集:导出的图在别人机器上缺的是**连接**(可以现场建),而不是**节点类型**(缺了图就打不开)。

## 隔离边界不变

这次重构**不动**下面这些,它们是对的:

- 插件进程只拿到 `PATH` / `HOME` / `LANG` 加上**它自己实例**声明的配置与凭据。拿不到应用的供应商 key、数据库、API token。
- 权限逐项授权、deny-by-default;未授权的实例不出工具。
- 智能体、工作流、手动试跑走同一条执行路径,权限校验 / 凭据注入 / 调用留痕都在那里。
- 工具默认不是只读,子智能体拿不到 —— 要 manifest 明写。

## 协议只搬 JSON —— 于是有两条旁路

`stdin 一个 JSON 进,stdout 一个 JSON 出`,上限 1MB。这对纯计算的工具刚好,对另外两类需求
是死结,而它们都不是边缘情况:

**要交出一个文件。** 一个 2GB 的 mp4 塞不进 JSON。加 `artifact`:插件要么把文件写进
`OPEN_STUDIO_PLUGIN_OUTPUT_DIR`(用完即删,路径受限 —— 挡的不是提权,插件本来就以用户身份
运行,挡的是「随手交出一个别处的文件」,而素材库里的东西是能被发布出去的),要么交出
url + 请求头让宿主去下。

**后者才是重点**:让插件负责换取凭据、宿主负责搬字节,进度、取消、重试、失败隔离全部复用
现成的任务机制。反过来每个插件自己下的话,它们会各实现各的,而且插件那一侧只有一次 60 秒的
调用 —— 大文件必然超时。收口在 `tools.invoke`,`artifact` 换成 `asset_id`。

**要记住一点东西。** 插件进程无状态,而 OAuth 令牌要续期 —— 换一个新的很容易,难的是换完
之后没地方放。加 `state`(和 `output` **平级**,不在里面:output 会交给调用方和模型,
刚续出来的令牌不该出现在那里)。只能写清单声明过的键,声明成 credential 的进加密库、
声明成 config 的进明文配置;写了没声明的键**直接失败**,不是忽略 —— 忽略的话插件以为存下了,
下次拿到旧值,而错误表现在几十分钟后的另一个地方。

**还有反过来的一条**:工具在 `input_schema` 里把某个字段标成 `"format": "asset"`,宿主就把
调用方传来的素材**拷一份**到暂存目录,插件收到的是本地路径。有了它插件才能做"上传"这类事。
给副本不给原件:插件是第三方代码,它改坏了或删掉了都伤不到库里那一份。

三条都只给**进程形态**。MCP 是别人的协议,我们不往里加字段。

### 这道缝两头互不认识

`domain/plugins` **不 import 素材库**,一行都没有。它只定义契约(`media_bridge`:
文件进来的来源、文件出去的落点),真正认识素材库的是 `domain/assets/plugin_bridge`,
它在组装根把自己登记进去 —— 和 `domain/agent/receipts` 把智能体登记进任务总线是同一个手法
(发布、导出、转写都建任务,它们没有一个该因为「智能体也许想知道」而认识智能体)。

好处不是洁癖:哪天要支持「从一个 URL 取文件交给插件」,登记另一个来源即可,插件这一层
一行不用改。有一道棘轮钉着这个方向 —— 那个 import 一旦有了,"来源可换"就没了,而这正是
这条缝存在的理由。

## 装进来的两条路

手动放目录 + 扫描,是给写插件的人的;对用它的人是道墙 —— 而插件的价值在于用的人比写的人
多得多。所以加市场:索引是一份普通 JSON,地址可配置,谁都能架(包括公司内网)。

**代价是索引不构成信任背书**,所以防线不在索引那一侧,而在装的那一刻:先下下来读清单,
把声明的权限和会带来的工具摊开给用户看过才落地。装插件 = 在用户机器上放一份会被执行的
代码,那一步省不掉。

安装器挡住的:压缩包路径穿越、符号链接(`extractall` 会规范化 `..` 但不拦它)、解压炸弹、
没有清单的垃圾包、悄悄覆盖一个已经装好并填了凭据的包。挡不住的是「作者是不是好人」——
那件事只能由用户看着权限清单自己决定。

## 数据迁移

| 现在 | 之后 |
| --- | --- |
| `plugins` | `plugin_packages`(去掉 `enabled`) |
| — | `plugin_instances`(package_id, name, enabled, config JSON) |
| `plugin_credentials(plugin_id, key)` | `plugin_credentials(instance_id, key)` |
| — | `plugin_capabilities(instance_id, tool_name, exposed)` |
| `plugin_permission_grants(plugin_id, …)` | `(instance_id, …)` |
| `plugin_invocations(plugin_id, …)` | 加 `instance_id` |

升级时:每个已启用的包建一个默认实例,凭据与授权搬过去,已发现的工具**全部勾上**(保持现状,不在升级里改变用户已经看到的东西);新装的包才走「默认不暴露」。

已经存在的 `plugin_tool` 节点和 `plugin.<包id>.<工具>` 节点继续可跑:前者本来就带 plugin_id,后者补一个默认实例即可。

## 分几步做

1. **数据层**:三张表 + 迁移 + 归属登记。此时行为不变。
2. **manifest 解析**:新形状 + 旧形状兼容读(旧 manifest 仍能装,按单实例处理)。
3. **能力开关**:`plugin_capabilities` 接进 `list_enabled_plugin_tools`,插件页出勾选 UI。
4. **多实例**:插件页的「新建连接」,节点上的实例选择器。
5. **文档**:重写 PLUGIN_MANIFEST.md,更新官网的插件页,范例跟上。

每一步都能独立发布,前三步就把三个故障全修掉;第 4 步是「同时接两个平台」这个能力本身。
