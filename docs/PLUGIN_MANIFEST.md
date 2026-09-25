# 写一个插件

插件是 Mosael 里**唯一一处能力由第三方提供**的地方。一个插件写好之后,它的工具同时出现在
三个地方:智能体的工具表、工作流的节点面板、插件页的手动试跑 —— 你不需要为哪一边额外做适配。

架构与取舍见 [PLUGIN_ARCHITECTURE.md](PLUGIN_ARCHITECTURE.md) 与 [ADR 0005](adr/0005-plugin-package-instance-capability.md)。

---

## 三十秒版本

```
~/.mosael/plugins/我的插件/
  mosael.plugin.json     ← 清单
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
  "name": { "zh": "文本工具", "en": "Text Toolkit" },   // 给人看的文字可按语言写,见「多语言」
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

request = json.loads(sys.stdin.read())          # {"tool": …, "input": {…}, "locale": "zh"}
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
out = os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"]
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

限制:单份 8GB;`url` 只能是 http/https;`path` 必须落在 `MOSAEL_PLUGIN_OUTPUT_DIR`
里面(插件本来就以你的身份运行、读得到你读得到的一切,这条挡的不是提权,是「随手交出一个
别处的文件」—— 素材库里的东西是能被发布出去的)。

### 要**收**一个文件

反过来:你的工具要处理一份已有的素材(传到网盘、发给外部服务转码)。在 `input_schema` 里
给那个字段标上 `"format": "asset"`:

```json
{"name": "upload", "input_schema": {"type": "object",
  "properties": {"asset_id": {"type": "string", "format": "asset"},
                 "path": {"type": "string"}},
  "required": ["asset_id", "path"]}}
```

调用方传素材 id,**你收到的是一个本地绝对路径** —— 你不知道素材库存在,也不需要知道。
字段叫什么名字都行:工作流里这个字段按 `format` 认成素材,给的是素材选择器,不是一个让人
手打 id 的文本框。

给的是**副本**,不是库里那一份:你改坏了或删掉了都伤不到用户的素材。调用结束即删,
所以不要往那个路径写你想留下的东西(想留下就用 `artifact` 交回去)。

为什么不让你自己去取:你的环境里没有数据库、没有 API 令牌、没有媒体目录 —— 那是隔离边界
的一部分,不是疏漏。

用 JSON Schema 的 `format` 而不是自造一个键:那个关键字的用途正是"这个字符串在语义上是
什么",而且不认识它的工具会安静忽略,清单仍是合法的 JSON Schema。

### 要**记住**一点东西

插件**进程**是无状态的:环境变量进、JSON 出,跑完就没了,你自己没有任何写回的手段。对纯计算的工具这没问题,对**要续期的凭据**就是个
死结 —— 拿 refresh_token 换一个新的 access_token 很容易,难的是换完之后没地方放。

在响应里放 `state`(和 `output` 平级):

```python
json.dump({
    "ok": True,
    "output": {"files": [...]},              # 回给调用方
    "state": {"MY_ACCESS_TOKEN": "新换的"},   # 宿主替你记住,下次原样注入回环境变量
}, sys.stdout, ensure_ascii=False)
```

**为什么和 output 平级而不是放在里面**:`output` 会交给调用方和模型,而刚续出来的令牌
不该出现在那里。

**只能写清单里声明过的键**(`instance.credentials` 或 `instance.config` 里的)。声明成
credential 的进加密凭据库,声明成 config 的进明文配置 —— 令牌和「上次同步到哪」不该存在
同一个地方。写了没声明的键**直接失败**,不是忽略:忽略的话你以为存下了,下次拿到旧值,
而错误表现在几十分钟后的另一个地方。

用户在插件页看得到这些字段,能自己改、自己清空。一个插件在背后攒一份用户看不见也删不掉的
状态,是不该有的东西。

限制:单个值 8192 字符;只有**进程形态**支持 —— MCP 是别人的协议,我们不往里加字段。

范例见 [百度网盘插件](../plugins/examples/baidu-pan):三十天到期的 access_token 由它
自己续,用户只填一次 refresh_token。

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

**留空也能跑的旋钮标成高级**,它们会收进面板的「高级」一档,不占第一屏 —— 内置节点用的是
同一套语义。JSON Schema 没有这个概念,所以认 `x-advanced`(`advanced` 也认):

```jsonc
"input_schema": {
  "type": "object",
  "properties": {
    "query":   { "type": "string",  "description": "搜什么" },
    "page":    { "type": "integer", "description": "第几页", "x-advanced": true },
    "timeout": { "type": "integer", "description": "超时秒数", "x-advanced": true }
  },
  "required": ["query"]
}
```

**`description` 只写标签说不出的东西。** 字段名已经在标签上了,下面那行小字再说一遍,
读的人要多花一次注意力才发现自己什么也没得到 —— 十几个字段叠起来整张表单就又长又空。
写约束、默认值、格式、留空的含义;写不出新东西就别写。内置节点这条由棘轮钉着
(`test_field_help_says_something_new`),插件这边靠自觉,但表现是一样的。

判据和内置节点一致:**留空也能跑的才算高级**。必填项、以及决定"这个节点在做什么"的那几个
字段留在第一屏 —— 把它们收起来,用户打开面板会以为没配好。

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

### 预算

一次调用默认最多跑 60 秒(`runtime.PLUGIN_TIMEOUT_SECONDS`)。进程插件可以在 `declare` 的那条工具上写
`timeout_seconds`,上限 1800(`tools.MAX_DECLARED_TIMEOUT_SECONDS`);不是正数就当没写。调用方显式给了
预算(Blender 互通)时以调用方为准。**预算该由最知道活有多重的一方给** —— 此前只有调用方能给,插件
说不出「这一步要三分钟」。智能体那一侧单次工具调用最多等 180 秒(`agent-sidecar/src/tools.ts`)。

**认领了生成能力的那个工具按能力给**(见「替宿主做生成」):不写是 1 小时,上限 6 小时
(`tools.MAX_GENERATION_TIMEOUT_SECONDS`,和远端生成任务的轮询上限是同一个数)—— 一段长视频在一块普通
显卡上跑一两个小时是常事。

### 持久目录

`MOSAEL_PLUGIN_DATA_DIR`:每个插件一份(`<数据目录>/plugin-data/<id>`),跨调用、跨更新都在,卸载时
随包一起删。和 `MOSAEL_PLUGIN_OUTPUT_DIR` 正相反 —— 那个是这一次调用的、用完就删。插件目录本身不能
当存储:更新就是整目录替换。

### 只供宿主使用

`overrides.<工具>.internal: true` 的工具**只给 Mosael 自己的适配层调**(例如 3D 场景与 Blender
的互通脚本),不出现在插件页的勾选列表里,智能体和工作流都调不到 —— 图里存着也拒绝执行。

用在插件自带一个不经确认的原始入口、而 Mosael 已经有**带确认卡**的同一能力时:Blender MCP 的
`execute_blender_code` 就是这样,智能体建模走内置的 `blender_execute`。两条路并存的话,不经确认
的那条就是绕开确认卡的后门。

### 权限

`permissions` 是一组自由字符串(`network:example`、`assets:read`…)。**逐项授权,全部授予之后
工具才可用**。它不是沙箱 —— 沙箱是进程隔离本身;它是一次明示的"我知道这个插件要做什么"。

---

## 拿不到什么

插件进程只拿到 `PATH` / `HOME` / `LANG`,加上**它自己这个连接**声明的配置与凭据。

拿不到:Mosael 的供应商 API Key、数据库、内部 API token、别的插件的凭据。

这是有意的。插件因此**绕不过确认卡和权限系统** —— 它不能替用户批准任何东西,只能返回数据,
由智能体带着那份数据去走正常的确认流程。

---

## 把人送到你的文档

一个插件带来几十个工具、一串权限、一套要去某个后台申请的凭据 —— 这些怎么用,只有你说得清。
所以清单里给一条 `homepage`:

```json
"homepage": "https://docs.example.com/"
```

界面会在**三处**给出「文档」链接:插件详情页的页头、市场里那一条、以及**安装确认弹窗** ——
最后一处是最要紧的:决定装不装的最后一问往往是"它到底怎么用、凭据去哪儿申请",而那时候
用户还没装。

只认 `http://` / `https://`。别的一律当没写 —— 那个链接是直接交给用户浏览器打开的。

不写也行:市场里的条目会退回到它在仓库里的目录,至少还能读到源码和 README。

### 使用文档与作者

`homepage` 常常是插件**背后那家服务**的站点(百度网盘开放平台、TikHub 的 API 文档)。而「在 Mosael 里
怎么配、每个工具干什么」要另一页讲 —— 写在 `docs` 里,可以按语言分:

```json
"docs": { "zh": "https://example.com/zh/my-plugin", "en": "https://example.com/en/my-plugin" },
"author": { "name": { "zh": "某某工作室", "en": "Some Studio" }, "url": "https://example.com" }
```

有 `docs` 时,插件详情页、市场条目、安装确认里的「文档」都指向它;没有才退到 `homepage` / 通用的插件指南。
`author` 显示在这三处的名字旁边,有 `url` 就能点进作者主页。两者都只认 `http(s)`。官方插件的 `docs`
指向官网上各自那一页(`mosael.com/<语言>/plugins/<目录名>`),有测试钉住。

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

## 多语言

界面会说好几种语言,而清单里的文案是你写的 —— 所以**一段给人看的文字既可以是一个字符串,
也可以是一个按语言分的对象**:

```json
"label": "起始目录"
"label": { "zh": "起始目录", "en": "Start directory" }
```

只写字符串就是「哪种语言下都这么显示」,已有的清单一个字都不用改。

**翻译贴着它翻译的那个东西写**,不要在清单顶上另开一张 `{"config.X.label": "…"}` 的对照表:
那种表的键要和别处对得上,而对不上时不会报错,只会让那一条永远显示原文。

哪些字段吃这一套(其余字段是标识、路径、类型,不翻):

- `name`
- `skills[].description`(以及 `skills[].name`)
- `instance.name_template`
- `instance.config[]` / `instance.credentials[]` 的 `label`、`help`,以及 `options[].label`
- `tools.declare[]` 的 `description`、`label`、`node.label`,和 `input_schema` 里各属性的 `description`
- `tools.overrides[]` 的 `label`、`description`

挑哪一条:**要的那种语言 → 同一主语言的任意变体(`en-US` 认 `en`) → 你声明的原文语言
(`default_locale`) → 部署缺省 → 你写的第一条**。某种语言没写就退回原文,不是空白 ——
只写了中文的插件在英文界面上显示中文,总好过显示一片空白。

```json
{ "id": "dev.you.toolkit", "default_locale": "en", "name": { "en": "Toolkit", "zh": "工具箱" } }
```

`default_locale` 是**你那些裸字符串是用哪种语言写的**。不写也能跑(退到"你写的第一条"),
写了才能在既没有中文也没有英文时挑得准 —— 比如你写了德语和法语,而界面是中文。

### 跑出来的那些字,由你自己说

清单里的文案我们替你挑;但工具**运行时产出**的文字(摘要、失败原因、枚举出来的项目名)
只有你写得出。所以每次调用都告诉你**读的人在用哪种语言**:

| 形态 | 怎么拿 |
| --- | --- |
| 进程插件 | 请求体里的 `locale`,以及环境变量 `MOSAEL_LOCALE` |
| MCP · stdio | 环境变量 `MOSAEL_LOCALE` |
| MCP · http | 请求头 `Accept-Language`(你自己在 `headers` 里写了同名头就以你的为准) |

```python
locale = request.get("locale") or os.environ.get("MOSAEL_LOCALE", "zh")
return {"summary": "已导入 3 个文件" if locale.startswith("zh") else "Imported 3 files"}
```

**不混进 `input`**:语言是这次调用的上下文,不是工具的一个参数 —— 混进去的话,每个工具都得在
自己的 `input_schema` 里声明一遍,而忘了声明的那个会把它当成非法参数拒掉。

我们自己发的那几个插件由一道棘轮钉着:凡是中文文案都得配上 `en`
(`backend/tests/test_plugin_manifest_i18n.py`)。你的插件不受这条约束,但样板就摆在那儿。

---

## 清单字段速查

| 字段 | 说明 |
| --- | --- |
| `id` / `name` / `version` | 必填。`id` 是稳定标识,改了等于换了个插件;`name` 可写成按语言分的对象 |
| `default_locale` | 可选。你那些裸字符串是用哪种语言写的(见「多语言」),挑不到要的语言时先退到它 |
| `manifest_version` | 当前是 `1`。老清单扫描时自动迁移并补上 |
| `homepage` | **你的文档站**。界面在插件详情页、市场条目、安装确认三处给一个「文档」链接;不写就不画。只认 `http(s)` |
| `docs` | 在 Mosael 里怎么用的文档,可按语言分;有它时「文档」指向它 |
| `author` | `{name, url}`,`name` 可按语言分;显示在名字旁边,`url` 可点 |
| `runtime.kind` | `"process"` 或 `"mcp"` |
| `runtime.entry` | 本地脚本入口,相对插件目录,必须在目录内 |
| `runtime.transport` / `command` / `args` / `url` / `headers` | MCP 的连接方式 |
| `instance.multiple` | 允许建多个连接 |
| `instance.name_template` | 连接的默认名字,`{键}` / `{键:label}` |
| `instance.config` | 明文配置:`key` `label` `type` `options` `required` `help` `default`;`multiline: true` 给多行框(一段 JSON 之类) |
| `instance.credentials` | 密钥,字段同上;`secret` 默认 true |
| `permissions` | 自由字符串,逐项授权 |
| `provides` | 这个插件能替宿主做成哪几件事:`public_url` / `generation`(见「声明『我能替宿主做成什么』」) |
| `skills` | 给别的智能体看的高层描述 |
| `tools.expose` | `"selected"`(默认)/ `"all"` |
| `tools.recommended` | 首次启用默认勾上的工具名 |
| `tools.declare` | 本地脚本的工具声明(MCP 不写,清单从服务拉) |
| `tools.overrides` | 按工具名覆盖 `label` / `description` / `read_only` / `node` / `internal` |
| `input_schema` 属性的 `x-advanced` | 标成高级,收进面板的「高级」一档。判据:**留空也能跑**的才算 |

## 范例

`plugins/examples/` 下的范例覆盖各种形态(不写数目 —— 每加一个就错一次):

- **text-toolkit** — 纯函数,零依赖零凭据,`expose: "all"`
- **baidu-pan** — 本地脚本 + 凭据自动续期 + 收发文件 + 工作流节点
- **tikhub** — 零代码接 MCP + 多连接 + 枚举配置 + 凭据
- **mcp-everything** — 最小的 MCP 接入声明
- **blender** — 接一台本机跑着的 Blender,工具按只读/可写分开申报
- **remotion** — 用代码做动画视频:自带渲染项目,声明自己的超时预算(`timeout_seconds`),
  几百 MB 的依赖放进跨更新的持久目录(`MOSAEL_PLUGIN_DATA_DIR`)
- **volcengine-tos** / **aliyun-oss** / **aws-s3** / **tencent-cos** — 对象存储四家。
  **同一套主体、各自的签名方言**:接口是同一套(PUT/GET 对象、列目录、虚拟主机式寻址),
  只有签名不同。`storage.py` 不认识任何一种签名,由插件把方言对象交给它
  (`Bucket(dialect=…)`):SigV4 系三家用 `sigv4.py` 里的 `Flavor`,腾讯云 COS 的原生签名
  (`q-sign-algorithm=sha1`)不是这一系,带自己的 `qsign.py`。`storage.py` 在四个包里、
  `sigv4.py` 在三个包里都是**字节相同**的拷贝(由 `test_storage_plugins_share_one_core.py`
  钉住);每一种签名都拿官方 SDK 的向量对过(`test_*_signature_matches_the_sdk.py`)。

  它们解决的是一个具体的断链:Mosael 是本地优先的,素材没有公网地址,而有些供应商**只收链接**
  —— 方舟 Seedance 的参考视频就是一例(参考图可以走 Base64,参考视频不行)。
  `*_upload` 把素材传上去,交回一条**限时直链**(签名在查询串里,桶不必设成公共读)。

它们都写了中英两份文案,可以直接照着抄多语言的写法。

另有 `plugins/bundled/` 下**随应用一起发**的插件(今天是 **comfyui**):它们随后端一起打包,每次启动对账
装进插件目录(按内容指纹,见 `domain/plugins/bundled`),卸不掉,也不进市场索引。ComfyUI 插件是
「替宿主做生成」的完整范例:动态模型目录、JSON Schema 参数、参考图槽位、NDJSON 进度、取消文件、回执与接着取。

## 声明「我能替宿主做成什么」

```json
{
  "provides": ["public_url"],
  "tools": { "declare": [ { "name": "oss_upload", "provides": ["public_url"], "…": "…" } ] }
}
```

有些事宿主自己做不到,而某一类插件能做:

| 能力 | 意思 | 谁需要它 |
| --- | --- | --- |
| `public_url` | 把一份**本地素材**变成一条公网可下载的地址 | 生成链路:某些模型的参考视频 / 源视频**只收链接**(方舟 Seedance 的参考图可以走 Base64,参考视频不行) |
| `generation` | **当一家生成供应商**:列出自己的模型,做一次生成 | 选择器、画板、工作流、智能体 —— 插件的模型和内置供应商的模型一样出现(见下一节) |

两处都要写:**包上的 `provides`** 说「这个插件能做这件事」,**工具上的 `provides`** 说「这件事归
我」。负责 `public_url` 的工具收 `{asset_id, expires}`,交回 `{url}`。工具上声明了包上没有的能力,
清单当场拒绝 —— 两处说的不是一回事,宿主不该替作者选一个信。包上声明了、却没有工具认领的,是
写这条规矩之前的老版本:生成时会让用户去插件页更新它。

**为什么是声明,不是猜。** 此前宿主按工具名后缀 `_upload` 去找上传工具 —— 任何一个叫这个名字的
工具都会被当成对象存储,而猜错的表现是**把用户的素材传去了别的地方**。

宿主那一侧的用法见 `backend/app/domain/generation/public_links.py`:提交生成任务时,只收链接的
角色若带的是本地素材,就传上去、换一条限时直链回填进去。从那一刻起它和"用户自己粘了一条链接"
走同一条路,下游一行都不用改。用哪一家:

- **只用发起人自己的连接**(存储的桶和密钥是他的,多人部署时绝不借别人的);
- **只看配好的**;配好一家就用它;
- **配好了几家,用他定的那一家** —— 「设置 → 素材外链」(自己一页 —— 只收链接的不止视频)
  (`GET/PUT /api/settings/asset-link-storage`,存在 `plugin_capability_defaults`)。
  **没定就当场问**,不按名字替他挑。放在设置而不是插件页每一家的连接上:那样是几个互相牵制的
  开关,打开一家会悄悄关掉另一家;
- 同一份素材在同一家存储里,链接还在有效期内就复用(`plugin_public_links`),不重复上传。

没装 / 没配好 / 几家没定 / 版本太旧 / 传失败,**各说各的下一步** —— 它们对用户意味着完全不同的事。

## 替宿主做生成

决策与取舍见 [ADR 0020](adr/0020-plugins-can-be-generation-providers.md);完整范例是
`plugins/bundled/comfyui`。

```jsonc
{
  "provides": ["generation"],
  "runtime": { "kind": "process", "entry": "tools/main.py" },
  "tools": { "declare": [
    { "name": "my_generation", "provides": ["generation"], "timeout_seconds": 7200,
      "description": "…", "input_schema": { "type": "object" } }
  ] }
}
```

比 `public_url` 多三条硬规矩,**装的那一刻就查**(清单不合法直接拒):

- **只给进程形态**(MCP 是别人的协议,我们不往里加字段);
- **有且只有一个工具认领** `generation`;
- 这个工具**只给宿主调** —— 不出现在智能体工具表、工作流节点面板和插件页的勾选表里。它说的是下面这套
  流式协议;让智能体直接调它,等于绕开生成任务、用量台账和回执。预算不写是 1 小时,上限 6 小时。

同一个工具收两种 `input.op`。

### `op: "models"` —— 这个连接有哪些模型

一问一答(和普通工具同一个协议,60 秒预算)。回:

```jsonc
{"models": [
  {
    "id": "portrait.json",                 // 这个连接里稳定;会被存进画板、工作流、默认模型
    "label": {"zh": "人像", "en": "Portrait"},
    "kind": "image",                       // image | video(宿主今天只接这两种;别的照列、不进选择器)
    "modes": ["text-to-image", "image-to-image"],
    "parameters": {                        // 键 → JSON Schema 片段
      "seed": {"type": "integer"},
      "negative_prompt": {"type": "string"},
      "size": {"type": "string", "enum": ["1024x1024", "832x1216"], "default": "1024x1024"},
      "3.steps": {"type": "integer", "title": "KSampler · steps", "default": 20, "minimum": 1, "maximum": 150},
      "3.sampler_name": {"type": "string", "enum": ["euler", "dpmpp_2m"], "x-advanced": true}
    },
    "inputs": [{"role": "reference_image", "max": 2}],
    "max_outputs": 1,
    "prompt_dialect": "sd-tags"            // 可选:提示词优化按哪种写法改
  }
]}
```

- `parameters` 认的键:`type`(integer / number / string / boolean)、`enum`、`default`、`minimum`、`maximum`、
  `multipleOf`、`title`、`description`(后两个可按语言分)、`x-advanced`、`x-multiline`。认不出的类型整项丢掉。
- **宿主自己有控件的那几个键**直接用宿主的控件:`seed`、`negative_prompt`、`size`(`enum` → 尺寸下拉)、
  `resolution` / `aspect_ratio`、`duration_seconds`(`enum` 或 `minimum` / `maximum`)、`num_images`
  (`maximum` → 张数上限,没写用 `max_outputs`)、`generate_audio`。**其余的键**进描述符的 `parameter_schema`,
  AI 工作台、画板、工作流节点用同一个通用控件渲染;提交时宿主按它校验类型、范围和可选值。
  用户没动过的参数**不发**,插件给的 `default` 只当占位提示(ADR 0015)。
- `inputs` 的 `role` 取宿主的素材角色(`reference_image` / `first_frame` / `last_frame` / `reference_video` …),
  `max` 是这个角色最多几份,`required: true` 是必须给。认不出的角色不接。
- 宿主把这份清单**缓存成模型行**:连接新建、改配置、启停、授权 / 凭据变化、插件页点「刷新」,以及后端启动时
  各问一次。问不到(服务没开)就保留上一份,原因显示在插件页;清单里没有了的模型从选择器里消失。

### `op: "generate"` —— 做一次

```jsonc
{"op": "generate", "model": "portrait.json", "kind": "image",
 "prompt": "…", "negative_prompt": "…",
 "parameters": {"seed": 7, "3.steps": 30},
 "inputs": [{"role": "reference_image", "path": "/…/inputs/01-reference_image.png"}],
 "resume": null}
```

stdout 是**一行一个 JSON 对象**,最后一行是和普通协议同形的结果;不是 JSON 对象的行跳过:

```
{"event": "progress", "progress": 0.42, "message": "KSampler 12/20"}
{"event": "task", "task": {"prompt_id": "…"}}
{"ok": true, "output": {"outputs": [{"path": "a.png"}], "usage": {"images": 1}, "raw": {…}}}
```

- **`progress`**:0..1 加一句话(按请求里的 `locale` 说),进任务中心。
- **`task`**:远端回执(一个对象,≤ 8KB)。宿主**收到就落库**(`Job.payload.remote_task`,ADR 0019);发了它
  就等于承诺:后端重启后宿主会带着 `"resume": <回执>` 再调一次,你要**接着等那个任务,不再提交**。
- **输入文件**:`inputs[].path` 是宿主从素材库**拷出来的副本**,放在这次调用的暂存目录里,用完即删。
- **产出**:`outputs` 里每一项和 `artifact` 同一套规则 —— 写进 `MOSAEL_PLUGIN_OUTPUT_DIR` 给 `path`,或者给
  `url`(+ `headers` / `filename`)让宿主去下。宿主把它们交给生成执行器,登记成素材、记用量、写回执。
- **取消**:宿主建一个文件,路径在环境变量 `MOSAEL_PLUGIN_CANCEL_FILE`。看到它就去停远端的活(ComfyUI 是
  `/interrupt` + 删队列)然后退出;30 秒不退就被杀。用文件不用信号:Windows 上没有可靠的信号,而「一个文件在不在」
  任何语言一行就写完。任务取消经任务总线拉下这个开关(和普通插件进程归它所在的任务同一套登记)。
- **预算用完**也走取消那条路(先建取消文件、给宽限、再杀),报超时。

一次调用照样留一条调用记录(插件页看得到),只是记录里不留那几个一次性的暂存路径。

## 接口

| | |
| --- | --- |
| `POST /api/plugins/scan` | 扫描;顺带迁移老清单、清掉目录已不在的包 |
| `GET /api/plugins` | 包 + 它们的连接 + 每个连接的工具与开关;`provides`、`bundled`,以及每个连接的 `capability_status`(几个生成模型、何时刷新、为什么没刷出来) |
| `DELETE /api/plugins/{包id}` | 卸载:删目录 + 删记录 |
| `POST /api/plugins/{包id}/instances` | 新建连接 |
| `PATCH /api/plugins/instances/{id}` | 改名 / 改配置 / 启停 |
| `GET`/`PATCH` `/api/plugins/instances/{id}/credentials` | 凭据(掩码回显) |
| `GET`/`PATCH` `/api/plugins/instances/{id}/permissions` | 授权 |
| `PATCH /api/plugins/instances/{id}/capabilities` | 工具开关 |
| `POST /api/plugins/instances/{id}/refresh` | 重拉 MCP 工具清单;替宿主做生成的插件顺带重问一遍模型清单 |
| `GET /api/plugins/tools` | 所有可用连接**已开放**的工具 |
| `POST /api/plugins/instances/{id}/tools/{工具}/invoke` | 执行一次,留痕 |

智能体、工作流、手动试跑走的是**同一条**执行路径:权限校验、凭据注入、调用留痕都在那里。

## `instance.oauth` —— 让插件自己走一次授权

声明了它,连接页上就多一个「去授权」的入口,用户不必自己手抄 refresh_token。

```json
"instance": {
  "credentials": [
    { "key": "BAIDU_PAN_APP_KEY", "label": "AppKey", "required": true },
    { "key": "BAIDU_PAN_SECRET_KEY", "label": "SecretKey", "required": true },
    { "key": "BAIDU_PAN_REFRESH_TOKEN", "label": "Refresh Token", "required": true },
    { "key": "BAIDU_PAN_ACCESS_TOKEN", "label": "Access Token" }
  ],
  "oauth": {
    "authorize_url": "https://openapi.baidu.com/oauth/2.0/authorize",
    "token_url": "https://openapi.baidu.com/oauth/2.0/token",
    "client_id_field": "BAIDU_PAN_APP_KEY",
    "client_secret_field": "BAIDU_PAN_SECRET_KEY",
    "scope": "basic,netdisk",
    "redirect_uri": "oob",
    "stores": { "refresh_token": "BAIDU_PAN_REFRESH_TOKEN", "access_token": "BAIDU_PAN_ACCESS_TOKEN" }
  }
}
```

几条要点:

- **块写在 `instance` 里**,不是顶层。放错了不会报错,只会让授权按钮静默不出现
  (`test_plugin_oauth_does_the_mechanical_part.py` 钉着这一条)。
- `client_id_field` / `client_secret_field` **指向已有的凭据键**。注册应用、拿 AppKey 这一步
  替代不了 —— 那是用户和开放平台之间的事。能替代的是后面那段机械动作:拼授权链接、拿 code
  换令牌、把令牌存回哪几个键,而那正是最容易抄错、抄错了只换回一句 `invalid_client` 的部分。
- `stores` 把**令牌响应里的字段**映射到**凭据键**。响应里叫什么由对方定,存进哪个键由你定。
  对方没回的字段不会被写 —— 刷新时常常只回 `access_token`,当成空串写回去会抹掉已有的
  refresh_token,而那一份丢了要重新授权一遍。
- `redirect_uri` 默认 `oob`(对方把授权码显示出来让人贴回来)。本地应用没有公网可达的回调
  地址,多这一次粘贴换来的是这条路上没有任何可伪造的输入。
- **声明不全就当没声明**:缺 `token_url` / `client_id_field` / `stores` 中任何一个,整块作废。
  半个声明会让界面长出一个点了必然失败的按钮。
