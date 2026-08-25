# 写一个插件

插件是 Open Studio 里**唯一一处能力由第三方提供**的地方。一个插件写好之后,它的工具同时出现在
三个地方:智能体的工具表、工作流的节点面板、插件页的手动试跑 —— 你不需要为哪一边额外做适配。

架构与取舍见 [PLUGIN_ARCHITECTURE.md](PLUGIN_ARCHITECTURE.md) 与 [ADR 0005](adr/0005-plugin-package-instance-capability.md)。

---

## 三十秒版本

```
~/.open-studio/plugins/我的插件/
  open-studio.plugin.json     ← 清单
  main.py                     ← 代码(MCP 插件可以没有)
```

插件页点「扫描插件」,它就出现了。目录路径以插件页空态里显示的为准 —— Windows 上不是 `~/`。

## 先选一种形态

| | **本地脚本** | **接一个 MCP 服务** |
| --- | --- | --- |
| 什么时候用 | 逻辑是你自己写的 | 对方**已经**有 MCP 服务 |
| 代码量 | 一个 Python 文件 | 零 |
| 工具清单 | 你在清单里声明 | 从服务现拉,不手抄 |

判据很简单:**对方有没有 MCP 服务**。有就别写脚本 —— 再写一层把 stdin 的 JSON 翻译成一次 HTTP
调用、再把结果翻译回 stdout,是在重新实现一个已经存在的东西,而且每加一个端点都要改代码。

---

## 形态一:本地脚本

```jsonc
{
  "id": "dev.example.text",          // 稳定唯一 id;改了等于换了个插件
  "name": "文本工具",
  "version": "1.0.0",
  "manifest_version": 1,

  "runtime": { "kind": "process", "entry": "main.py" },

  "tools": {
    "expose": "all",                  // 工具就两三个,不必让用户逐个勾
    "declare": [
      {
        "name": "count_words",
        "description": "统计字数、词数与预计口播时长。",
        "read_only": true,            // 见下面「只读」
        "input_schema": {
          "type": "object",
          "properties": { "text": { "type": "string", "description": "要统计的文本" } },
          "required": ["text"]
        }
      }
    ]
  }
}
```

`main.py` 的协议:**stdin 一个 JSON 进,stdout 一个 JSON 出**。

```python
import json, sys

def count_words(payload):
    text = str(payload.get("text", ""))
    return {"chars": len(text), "seconds": round(len(text) / 4.5, 1)}

TOOLS = {"count_words": count_words}

request = json.loads(sys.stdin.read())          # {"tool": "count_words", "input": {...}}
try:
    output = TOOLS[request["tool"]](request.get("input") or {})
    json.dump({"ok": True, "output": output}, sys.stdout, ensure_ascii=False)
except Exception as exc:
    json.dump({"ok": False, "error": str(exc)}, sys.stdout, ensure_ascii=False)
```

规矩:进程 60 秒超时,stdout 上限 1MB,`output` 必须是个对象。进程崩了、超时了、吐了非 JSON ——
失败的是那一次调用记录,不是应用。

### 要交出一个**文件**

上面那条路只搬 JSON,上限 1MB —— 一个 2GB 的 mp4 塞不进去。要把文件交给素材库,在 `output`
里放 `artifact`,有两种交法:

```python
# 一、你自己下好了。**必须写在给你的目录里**
out = os.environ["OPEN_STUDIO_PLUGIN_OUTPUT_DIR"]
path = os.path.join(out, "video.mp4")
download_to(path)
return {"artifact": {"path": "video.mp4"}}       # 相对这个目录,或者绝对路径

# 二、你只换到了下载凭据,让宿主去下
return {"artifact": {
    "url": "https://.../dlink?sign=...",
    "headers": {"User-Agent": "pan.baidu.com"},   # 有些接口不带特定头就 403
    "filename": "video.mp4",
}}
```

**第二种通常更好。** 让插件负责换取凭据、宿主负责搬字节 —— 进度、取消、重试、失败隔离全都
是现成的,你一行都不用写。反过来自己下的话,这些每个插件都要再实现一遍。

宿主收下之后,`output` 里的 `artifact` 会被**换成** `asset_id` / `asset_name`,调用方拿到的
就是一个素材 id,和其它产素材的工具一样。暂存目录用完即删,所以那个路径不会传给下游 ——
它在返回的那一刻就已经失效了。

限制:单份 8GB;`url` 只能是 http/https;`path` 必须落在 `OPEN_STUDIO_PLUGIN_OUTPUT_DIR`
里面(插件本来就以你的身份运行、读得到你读得到的一切,这条挡的不是提权,是「随手交出一个
别处的文件」—— 素材库里的东西是能被发布出去的)。

## 形态二:接一个 MCP 服务

```jsonc
{
  "id": "com.example.thing",
  "name": "示例服务",
  "version": "1.0.0",
  "manifest_version": 1,

  // 本地进程:spawn 一个子进程
  "runtime": { "kind": "mcp", "transport": "stdio", "command": "npx", "args": ["-y", "@scope/server"] },

  // 或者远端:url / headers 里用 ${键名} 引用下面声明的配置与凭据
  // "runtime": {
  //   "kind": "mcp", "transport": "http",
  //   "url": "https://example.com/${REGION}/mcp",
  //   "headers": { "Authorization": "Bearer ${API_KEY}" }
  // },

  "instance": {
    "credentials": [{ "key": "API_KEY", "label": "API Key", "help": "在哪儿生成" }]
  },

  "tools": { "expose": "selected", "recommended": ["fetch_one", "search"] }
}
```

工具清单在**启用时**、**填完凭据后**各拉一次,之后可以在插件页点「刷新工具」。服务升级加了新
工具,刷一下就有 —— 不用改插件、不用发版。

---

## 一个包,多次接入

有些服务是"同一套代码、不同端点"(TikHub 十几个平台各一个 MCP 端点)。这时候声明 `multiple`,
用户就能建多个**连接**,各有各的配置和凭据:

```jsonc
"instance": {
  "multiple": true,
  "name_template": "示例服务 · {REGION:label}",   // 连接的默认名字,由配置生成
  "config": [
    { "key": "REGION", "label": "区域", "type": "enum", "required": true,
      "options": [{ "value": "cn", "label": "中国" }, { "value": "us", "label": "美国" }] }
  ],
  "credentials": [{ "key": "API_KEY", "label": "API Key" }]
}
```

`{REGION}` 取配置值,`{REGION:label}` 取枚举的显示文案。**名字必须由配置生成** —— 否则用户配了
「中国」而卡片上写着「美国」,那比没有名字更坏(这正是重构前的一个真实 bug)。

### 配置还是凭据?

| | `config` | `credentials` |
| --- | --- | --- |
| 是什么 | 区域、端点、模式、开关 | API Key、token、密码 |
| 控件 | 下拉 / 文本框 / 数字 / 开关 | 密码框 |
| 回显 | 原值 | 掩码(原样交回 = 没改) |
| 参与显示名 | 是 | 否 |

两者都参与 `${...}` 展开,也都注入本地脚本的环境变量(**键名大写**:`API_KEY` → `$API_KEY`)。

判据:**这个值要不要藏起来**。要 → 凭据。不要 → 配置。把区域塞进凭据,用户会得到一个没有选项、
没有校验的密码框。

---

## 能有什么能力

### 工具

工具是插件的主体。写好一个工具,它自动出现在:

**智能体的工具表** —— 名字是 `plugin__<连接>__<工具>`,和内置工具在模型眼里没有区别,
`input_schema` 直接在手上。不需要模型先"想到"去列插件清单。

**工作流的节点** —— 每个工具就是一个节点(`plugin.<包id>.<工具>`),表单从 `input_schema`
自动生成:字符串给模板输入框(能引用 `{{上游.输出}}`)、`enum` 给下拉、`required` 进必填校验。
不写一个字也是一个像样的节点。

想更讲究就写 `node`(参照 ComfyUI 的自定义节点 —— 节点长什么样由插件说了算):

```jsonc
"tools": {
  "overrides": {
    "fetch_one": {
      "label": "取一条作品",
      "node": {
        "description": "按作品 id 取完整信息。",
        "config": { "aweme_id": { "type": "template", "required": true, "description": "作品 id" } },
        "outputs": ["title", "author", "digg_count"]     // 下游写 {{n1.title}}
      }
    }
  }
}
```

声明了 `outputs` 就按同名键从返回值里拆开;没声明就把整份返回值装进 `output`。

### 技能

`skills` 是给**别的智能体**看的一段高层描述(进 `/api/agent/skills`)。工具回答"能调什么",
技能回答"这个东西是干嘛的"。

### 只读

`read_only: true` 的工具才会给**子智能体**用。默认不标。

内置工具的只读判据是"没有确认门"—— 会改东西的都走确认卡。插件工具没有这个对应关系:它跑的是
你的代码,没有确认门也照样能发请求、写文件。所以默认落在保守那侧。宁可让子智能体少一个工具,
也不要让它在一次「帮我查一下」里替用户发了条微博。

### 权限

`permissions` 是一组自由字符串(`network:example`、`assets:read`…)。**逐项授权,全部授予之后
工具才可用**。它不是沙箱 —— 沙箱是进程隔离本身;它是一次明示的"我知道这个插件要做什么"。

---

## 拿不到什么

插件进程只拿到 `PATH` / `HOME` / `LANG`,加上**它自己这个连接**声明的配置与凭据。

拿不到:Open Studio 的供应商 API Key、数据库、内部 API token、别的插件的凭据。

这是有意的。插件因此**绕不过确认卡和权限系统** —— 它不能替用户批准任何东西,只能返回数据,
由智能体带着那份数据去走正常的确认流程。

---

## 用户会看到什么

1. 把目录放进插件目录 → 插件页「扫描插件」
2. 有配置的包:填配置 → 「新建」得到一个连接;没配置的包:自动就有一个连接
3. 填凭据 → 授权 → 启用
4. **勾选要开放的工具**(默认不开,按 `recommended` 预勾)
5. 工具就出现在智能体和工作流里了

第 4 步值得解释:一个 MCP 端点可能报四十上百个工具。全放出去,节点面板要人从四十行里找一行,
智能体每轮对话为四十条描述付 token,还挤占模型在内置工具之间的选择权。所以默认关,由 `recommended`
给一个起点;工具本来就少的包写 `expose: "all"` 全开。

---

## 清单字段速查

| 字段 | 说明 |
| --- | --- |
| `id` / `name` / `version` | 必填。`id` 是稳定标识,改了等于换了个插件 |
| `manifest_version` | 当前是 `1`。老清单扫描时自动迁移并补上 |
| `runtime.kind` | `"process"` 或 `"mcp"` |
| `runtime.entry` | 本地脚本入口,相对插件目录,必须在目录内 |
| `runtime.transport` / `command` / `args` / `url` / `headers` | MCP 的连接方式 |
| `instance.multiple` | 允许建多个连接 |
| `instance.name_template` | 连接的默认名字,`{键}` / `{键:label}` |
| `instance.config` | 明文配置:`key` `label` `type` `options` `required` `help` `default` |
| `instance.credentials` | 密钥,字段同上;`secret` 默认 true |
| `permissions` | 自由字符串,逐项授权 |
| `skills` | 给别的智能体看的高层描述 |
| `tools.expose` | `"selected"`(默认)/ `"all"` |
| `tools.recommended` | 首次启用默认勾上的工具名 |
| `tools.declare` | 本地脚本的工具声明(MCP 不写,清单从服务拉) |
| `tools.overrides` | 按工具名覆盖 `label` / `description` / `read_only` / `node` |

## 范例

`plugins/examples/` 下三个,覆盖三种形态:

- **text-toolkit** — 纯函数,零依赖零凭据,`expose: "all"`
- **tikhub** — 零代码接 MCP + 多连接 + 枚举配置 + 凭据
- **mcp-everything** — 最小的 MCP 接入声明

## 接口

| | |
| --- | --- |
| `POST /api/plugins/scan` | 扫描;顺带迁移老清单、清掉目录已不在的包 |
| `GET /api/plugins` | 包 + 它们的连接 + 每个连接的工具与开关 |
| `DELETE /api/plugins/{包id}` | 卸载:删目录 + 删记录 |
| `POST /api/plugins/{包id}/instances` | 新建连接 |
| `PATCH /api/plugins/instances/{id}` | 改名 / 改配置 / 启停 |
| `GET`/`PATCH` `/api/plugins/instances/{id}/credentials` | 凭据(掩码回显) |
| `GET`/`PATCH` `/api/plugins/instances/{id}/permissions` | 授权 |
| `PATCH /api/plugins/instances/{id}/capabilities` | 工具开关 |
| `POST /api/plugins/instances/{id}/refresh` | 重拉 MCP 工具清单 |
| `GET /api/plugins/tools` | 所有可用连接**已开放**的工具 |
| `POST /api/plugins/instances/{id}/tools/{工具}/invoke` | 执行一次,留痕 |

智能体、工作流、手动试跑走的是**同一条**执行路径:权限校验、凭据注入、调用留痕都在那里。
