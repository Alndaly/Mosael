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
        "read_only": true,            // 见下面「只读」;有后果的工具写 effects,见「确认」
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

#### 一次交出几份

跑一张 ComfyUI 工作流会交出好几张图、一段视频、再加一张预览 —— 用 `artifacts`(一串,每一项和
`artifact` 同一套写法):

```python
return {
    "artifacts": [
        {"path": "up-01.png", "filename": "up_00001_.png", "node": "4", "media": "image"},
        {"path": "up-02.png", "filename": "up_00002_.png", "node": "4", "media": "image"},
    ],
    "summary": "2 张图",
}
```

一份产出上可以写 `"output": "image_9"`:这一份就是工具在 `node.outputs` 里声明的那个具名输出口,宿主把它的素材 id
填进返回值的同名一格(同名只认第一份,你自己写了那一格就不覆盖)—— 下游能直接接「那个保存节点的图」。

宿主全部收进素材库,返回值里 `artifacts` 换成:

- `assets`:每一份 `{asset_id, asset_name, …}` —— 每一项上除了 `path` / `url` / `headers` / `filename` 之外的
  **标量**(上面的 `node`、`media`)原样跟着回来,嵌套结构不带;
- `asset_ids`:按顺序的一串 id(工作流里接下游用);
- `asset_id`:第一份(还没有 `asset_id` 时)—— 下游写 `{{n1.asset_id}}` 不必知道这个工具交的是一份还是几份。

一次最多 64 份(`tools.MAX_ARTIFACTS`),多了整次调用失败 —— 多半是插件把中间帧也交出来了。

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

一次要几份就写成数组:`{"type": "array", "items": {"type": "string", "format": "asset"}}`。调用方传一串
素材 id,你收到一串本地路径(顺序不变)。

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

失败响应还可以带 `"reauthorize": true`,说「对方不再接受已存的令牌」—— 见 `instance.oauth` 那节的「连接的授权状态」。

**失败的响应里也可以带 `state`**(`{"ok": false, "error": "…", "state": {…}}`),宿主照样记住:令牌续好了、
重试却撞上一个与令牌无关的失败(文件不存在)时,有的服务(百度)换令牌时连 refresh_token 一起轮换、旧的当场
作废 —— 这份丢了,下一次只能让用户重新授权。

**只能写清单里声明过的键**(`instance.credentials` 或 `instance.config` 里的)。声明成
credential 的进加密凭据库,声明成 config 的进明文配置 —— 令牌和「上次同步到哪」不该存在
同一个地方。写了没声明的键**直接失败**,不是忽略:忽略的话你以为存下了,下次拿到旧值,
而错误表现在几十分钟后的另一个地方。

用户在插件页看得到这些字段,能自己改、自己清空。一个插件在背后攒一份用户看不见也删不掉的
状态,是不该有的东西。

**写回是比较交换,不是后写者赢。** 一个键只有在库里的值**还是这次调用开始时注入给你的那一个**时才写回;
途中被别的调用(同一连接上并发的另一次刷新)或用户自己改过,这次交回的值就不用了。会轮换 refresh_token
的服务上,这正是两次并发刷新之后不把已作废的令牌盖回去的那道保险。

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

### 配置项的类型

| `type` | 控件 | 存的是 |
| --- | --- | --- |
| `string`(默认) | 文本框;`multiline: true` 给多行框 | 字符串 |
| `enum` | 下拉(`options`);只有一个选项时显示成锁定的值 | 选中项的 `value` |
| `number` | 数字框 | 数字 |
| `boolean` | 开关 | 布尔 |
| `json` | **代码编辑器**(连接卡片上是摘要 +「编辑」,编辑在大弹窗里);边敲边校验,错在第几行第几列当场说,错着存不了;后端保存前再查一遍 | 你粘进去的**原文**(字符串) |
| `code` | 代码编辑器,`language` 决定高亮(`python` / `json` …,认不得的照常编辑、不高亮);不校验 | 原文(字符串) |

一段 JSON、一段脚本**不要**写成 `multiline` 的 `string`:那是一个 200px 宽的文本框,几百行只看得见第一行,
少一个逗号要等插件跑起来才报。`json` / `code` 存的仍是字符串 —— 插件拿到的就是用户粘进去的那一段,自己解析;
存成解析后的对象会让原文的缩进、键的顺序在一次保存之后悄悄变样。

`help` 里的占位符、键名用反引号写成行内代码(`` `{{prompt}}` ``),界面按行内 Markdown 渲染。

### 配置还是凭据?

| | `config` | `credentials` |
| --- | --- | --- |
| 是什么 | 区域、端点、模式、开关 | API Key、token、密码 |
| 控件 | 下拉 / 文本框 / 数字 / 开关 | 密码框 |
| 回显 | 原值 | 掩码(原样交回 = 没改) |
| 参与显示名 | 是 | 否 |

两者都参与 `${...}` 展开,也都注入本地脚本的环境变量(**键名大写**:`API_KEY` → `$API_KEY`)。

键名大写之后**不能盖掉宿主给的变量**(`PATH`、`HOME`、`LANG`、`MOSAEL_*`,以及 Windows 上的
`SYSTEMROOT`、`APPDATA`、`TEMP` 等),配置和凭据之间大写后也不能撞名 —— 这两种写法装的时候就报错。

判据:**这个值要不要藏起来**。要 → 凭据。不要 → 配置。把区域塞进凭据,用户会得到一个没有选项、
没有校验的密码框。

---

## 能有什么能力

### 工具

工具是插件的主体。写好一个工具,它自动出现在:

**智能体的工具表** —— 名字是 `plugin__<连接>__<工具>`,和内置工具在模型眼里没有区别,
`input_schema` 直接在手上。不需要模型先"想到"去列插件清单。函数名最长 64 个字符(各家接口里最严的那个);
放不下时连接 id 缩成前 8 位、工具名截短,末尾接一段指纹 —— 所以工具名前面几个词要说得出它是干什么的。

**工作流的节点** —— 每个工具就是一个节点(`plugin.<包id>.<工具>`),表单从 `input_schema`
自动生成:字符串给模板输入框(能引用 `{{上游.输出}}`)、`enum` 给下拉、`required` 进必填校验。
不写一个字也是一个像样的节点。

**创意画板的工具格** —— 把内容变成新内容的工具(交出素材,或点名落板的文字)也能放在画板上跑,
上游的便签、图片接到字段上,产出落成右边新的几格(见下面「在画板里长什么样」)。

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

#### 在画板里长什么样

**把内容变成新内容的工具**同时也是**创意画板上的一种工具格**(`node:plugin.<包id>.<工具>`,见 ADR 0021):
用户从「添加」菜单或拉线菜单里放一格,表单就是上面那张节点表单(画板的那一份,见下);连进来的便签、文档、
图片、视频、音频、3D 场景可以接到字段上。

**不是每个工具都上画板。** 画板是「想法摊开,边看边做」的地方,只放内容变换(ADR 0021 修订);列清单、看状态、
上传、装环境这类工具只在工作流和对话里。判据全从你的声明里读:

- **交出内容**:落板的输出(`board_outputs`;没写的话是全部不在 `wiring_outputs` 里的,见下)里至少有一个素材(`asset` —— 交出的文件、名字是
  `asset_id` / `*_asset_id` 的输出),或者**点名落板**的文字(写在 `board_outputs` 里、`output_types` 是
  `text`)。只写了类型没点名的文字不算:一行摘要、一句状态不是成品。没声明类型的输出不算 —— 缺省的那一个
  `output` 也一样。
- **吃内容,或者凭空产出素材**:至少一个字段能接上游的素材 / 文字 / 3D 场景;不吃任何内容的工具得交出素材
  (提示词出图、按参数出视频、从远端取回一个文件)。不吃内容、只交出文字的是一份报告,不上画板。
- **必填字段创作者填得了**:画板的表单只摆模型、比例、风格、时长、语言这一类参数;`object` / `array`
  (映射、原始 JSON)这种字段在画板上不出现,**必填**这种字段的工具就不上画板。字符串字段在画板上是一段
  普通的字(没有 `{{…}}` 引用)。

上不上画板每次现算:你改了清单、ComfyUI 上多了一张工作流,画板的工具清单跟着变;画布上存着一个此刻不合格的
工具格,点运行时会说清楚它归工作流。几处声明决定它在画板上好不好用:

- **素材字段写 `"format": "asset"`**。字段就接得上游的图片 / 视频 / 音频(运行时换成本地路径,
  见上面「要收一个文件」),不管它叫不叫 `asset_id`。只写 `"type": "string"` 的字段接的是便签的字。
- **写明 `outputs` 和 `output_types`**。每跑一次,产出按类型落成右边新的几格:`asset` 是素材格
  (图片 / 视频 / 音频按素材种类,别的文件落成写着文件名的便签),`text` / `number` 是便签,
  `json` 是按代码排版的便签。**没声明类型的输出按值猜**:字符串当文字,带 `asset_id` 的对象当文件,
  列表拆成好几格,别的当 JSON —— 一个没声明的 `output` 往往就是一张大 JSON 便签。
- **说清交出的是哪种素材**:`"output_media": {"asset_id": "video"}`(`node` 块里,值是 `image` / `video` /
  `audio`,和输入字段的 `x-media` / `media` 同一个词表)。画板上的工具格长得像它要产出的那种内容 —— 出图的工具是
  一块空的图片格、出视频的是一块空的视频格;落板的第一个输出是主产出。没写的,工具吃哪一种素材就按哪一种画
  (`board_group` 是图片 / 视频 / 音频时),再说不清按图片格画。文字输出落成便签,不用写。
- **只落有用的那几个**:`"board_outputs": ["image", "caption"]`(`node` 块里)点名哪些输出落到画板上,
  缺省是全部。给下游连线用的计数、状态码、引擎名摊在画板上全是噪音。
- **说清哪几个只给连线用**:`"wiring_outputs": ["asset_ids", "count", "summary"]`(`node` 块里)—— id 列表、
  个数、摘要、任务号、「第一份产出」这种别名。它们在工作流里照样接得上,画板上**从不**落成格子:没写
  `board_outputs` 时缺省落的是「全部不在这里的」;写了也不落(两处都写了同一个口子,信这一处,棘轮会报出来)。
  一个工具交出好几个具名文件、又交一个等于第一份的 `asset_id` 时,`asset_id` 就该写在这里 —— 不然跑一次
  画板上就多一张一模一样的图。
- **交出文件**用上面的 `artifact` 约定:它先收进素材库,再落成画板上的一格。
- 一次最多新建 12 格,超出的合进最后一张 JSON 便签;一个返回几百项的工具,在画板上请交一个
  汇总字段 + `board_outputs` 只点它。
- **归哪一组、一句话说明**:「添加」菜单按工具**吃什么内容**分组(产出新素材 / 处理图片 / 视频 / 音频 /
  文字 / 3D 场景 / 素材)。缺省按字段推:素材字段的 `x-media` 只有一种就归那一种,没有素材字段、交出素材的归
  「产出新素材」。想指定就在 `node` 块写 `"board_group": "image"`;菜单和格子上那句说明缺省取 `description`
  的第一句,写给画板的另写 `"board_description": {"zh": "…", "en": "…"}` —— 说它把内容变成什么,不说输出口
  和引用写法。

```jsonc
"overrides": {
  "remove_bg": {
    "node": {
      "config": { "image": { "type": "template", "format": "asset", "required": true, "label": "图片" } },
      "outputs": ["asset_id", "mask_ratio", "engine"],
      "output_types": { "mask_ratio": "number" },
      "board_outputs": ["asset_id"],         // 画板上只落抠好的那张图
      "output_media": { "asset_id": "image" }, // 交出的是一张图:画板上的工具格画成空的图片格
      "wiring_outputs": ["engine"]           // 给连线用的,画板上不落
    }
  }
}
```

画板上**谁点运行就用谁自己的连接**:共享画板上存着别人选的连接不算数;点的人没有这个插件的连接,
画板会说清楚是哪个插件、去插件页建。`internal` 的工具不上画板。取消画板上的那一轮会杀掉你的进程
(和工作流里一样,见「预算」)。

### 运行时报出的工具

清单里 `declare` 的工具是写死的。可有些插件的工具**只有运行时才知道**:ComfyUI 插件里每张保存的工作流都该是一个
工具,入参就是那张图自己的提示词、读素材的节点和可调参数 —— 写死成一个 `run_workflow` 的话,它连要跑哪张图都不知道,
表单却要人填参数:不管选哪张工作流都长一个样,放大工作流也问你要提示词(ComfyUI 插件起先就是这样,1.4.0 删掉了它)。

声明一项宿主能力 `tools`,由一个只给宿主调的工具认领(可以和 `generation` 是同一个工具):

```jsonc
{
  "provides": ["generation", "tools"],
  "tools": { "declare": [ { "name": "my_host", "provides": ["generation", "tools"], "input_schema": {"type": "object"} } ] }
}
```

它收两种 `op`:

```jsonc
{"op": "tools"}        // → {"tools": [ … ], "fingerprint": "…"}
{"op": "fingerprint", "capability": "tools"}   // → {"fingerprint": "…"}  便宜的一问,见「目录变了就刷新」
```

`tools` 里每一项和 `declare` 里的写法一样,宿主认这些键:`name`(`[A-Za-z][A-Za-z0-9_-]*`,不能有点 —— 它要进节点类型
`plugin.<包>.<工具>`;不能和清单里声明的重名)、`label`、`description`(可以按语言分)、`input_schema`(属性的 `title` /
`description` 也可以按语言分)、`read_only`、`effects`(见「确认」;写错的当没写,只读却声明了别的后果按后果算、只读作废)、
`stream`、`timeout_seconds`(上限照旧)、`node`(`outputs` /
`output_types` / `output_labels` / `board_outputs` / `wiring_outputs` / `output_media`)、`recommended`(`true` = 第一次出现时默认开放)、
`replaces`、`mirrors`(见下)。**别的键丢掉**,
尤其是 `provides` 和 `internal`:运行时报出的工具不能替宿主认领能力,也不能把自己藏起来。最多 300 个。

报出来的工具存进 `plugin_instances.discovered_tools`(MCP 连接从服务拉来的清单也存在这里),和清单里声明的走
**同一条路**:插件页的工具表和开关、智能体工具表(`plugin__<连接>__<工具>`)、工作流节点(`plugin.<包>.<工具>`)、
同一个执行入口。调用时你照常收到 `{"tool": <名字>, "input": …}`。刷新时机和生成模型目录一样:连接新建、改配置、
启停、授权、插件页「刷新」、启动时,以及指纹变了;问不到就保留上一份,原因记在 `capability_status["tools"]`。

**名字要稳。** 工作流节点和智能体记的是工具名;一个工具换了名字,存着的节点就找不到它了。ComfyUI 插件用的是 ComfyUI
写进工作流文件里的 id(改名、挪目录都不变),没有 id 的老文件才退到路径的哈希。

#### 取代老工具:`replaces`

一个报出来的工具可以说它取代了某个老工具的某一种用法,宿主据此把**存着的老节点自动改写过来**(工作流里的节点和
连进来的数据边,画板上的工具格和它的绑定;每次清单刷新、以及每次启动的对账步骤 `rewrite-replaced-plugin-tools` 都会做,后者用缓存的清单):

```jsonc
"replaces": {
  "tool": "run_workflow",                    // 老工具
  "match": {"workflow": "portrait.json"},    // 老节点的配置里这几格是这些值才算
  "rename": {"image": "image_10", "images.0": "image_11", "values.3.steps": "steps_3"},
  "drop_if": {"wait": true}                  // 这几格是这个值时直接丢(老工具的默认)
}
```

取代好几种老用法时,`replaces` 写成一组这样的对象(最多 8 个):ComfyUI 的工作流工具除了取代选了这张图的
`run_workflow`,还取代这张图**以前按路径哈希起的名字**(老文件没有 id,在新版 ComfyUI 里再存一次就有了,工具名随之
变成按 id 起的那个)——`match` / `rename` 留空,入参按同名接。

配置按 `键.子键` / `键.序号` 展开后,每一格要么在 `rename` 里、要么新工具有同名的一格、要么按 `drop_if` 可以丢。
有一格(或一条连进来的数据边、画板上的一条绑定)对不上时,看**老工具在那个连接上还在不在**:

- **还在** —— 不改那个节点:宁可留着能跑的老节点,也不丢用户填的值;
- **已经不在了**(你从清单里删掉了它)—— 老节点本来就跑不起来,宿主照样改过去,对不上的格子、数据边和绑定丢掉,
  丢了哪几格写进这一版修订的说明(上一版修订原样留着)。所以**删一个工具之前,先让取代它的工具把 `replaces` 写全**:
  `rename` 里写得越全,迁过去丢的越少(ComfyUI 的工作流工具把 `values` 按节点 id 和按节点标题的两种写法都列了)。

改过的工作流追加一版修订(`migration`),作者和认可人沿用上一版。老工具删掉之后,`replaces` 还要一直报下去:
清单不在手里的时候(服务没开)迁不动,等它下次报上来才迁。

#### 和一个生成模型是同一件事:`mirrors`

插件同时替宿主做生成(`provides: ["generation"]`)时,有些工具和目录里的某个模型**是同一件事**:ComfyUI 里一张只有
一个图片保存节点的工作流,既是图片模型,又是一个工具。画板上一个概念只给一个入口(ADR 0021 修订):生成那一条
结果落在原位、有张数、记用量、能等 6 小时;工具那一条交得回全部输出节点、文字产出。所以这种工具说一声:

```jsonc
"mirrors": {
  "generation_model": "portrait.json",       // 同一个插件在 op: models 里报的模型 id
  "kind": "image",                           // image | video | audio
  "prompt": "prompt",                        // 下面三格可选:存着的工具格改写成生成格时,填过的值怎么带过去
  "parameters": {"steps_3": "3.steps", "seed": "seed", "negative_prompt": "negative_prompt"},  // 入参 → 生成参数键
  "sources": {"image_10": "reference_image"} // 素材入参 → 生成的素材角色
}
```

宿主据此做三件事(都不认识你的插件):

- **画板上不列它**:点运行的人在生成目录里用得上那个模型(**同一个连接**下的、启用着的)时,画板的「添加」菜单里
  没有这个工具,图片 / 视频 / 音频格选那个模型就是它。用不上的人(没这个模型、连接停了)照旧看得到工具格。
  **工作流里两个都在**,节点面板上这个工具的说明末尾多一句「只要图片的话,用『AI 生成素材』节点选这个模型」。
- **存着的工具格改写成生成格**(对账,和 `replaces` 同一个时机:每次清单刷新、每次启动):那一格变成 `kind` 那种
  素材的生成格,选的就是那个模型,id、位置、名字不变。提示词和素材按上面三格带过去(接了上游的保持连线,生成格的
  面板照连线挂);没写进这三格的入参带不过去,丢掉并记日志 —— 所以**能对上的都写上**。在跑的那一格等它落终态;
  格子上没选连接、而几条连接给出的不是同一个模型时不改,点运行时说清楚去用生成。
- **形状不对的整条不认**(`generation_model` 空着、`kind` 不是个标识符):说错了「同一件事」会把一个工具从画板上
  藏起来,比不说更糟。

只在工具**真的**什么都没多做时才声明:它交出两个输出节点、一段文字、拿 alpha 当蒙版、取回预览 —— 这些生成那一条
做不到,就不是同一件事。清单里写死的工具不认这个键,它只属于运行时报出的工具。

#### 表单长什么样

同一份 `input_schema` 在工作流里是节点表单,在插件页是「试一下」的表单 —— 两处是**同一个表单组件**,按同一份字段
声明渲染(`GET /api/plugins` 里每个工具带着 `form`,就是节点目录里的那一份):`title` 是标签;`description` 按行内
Markdown 渲染;`default` 是占位提示;`enum` 是下拉,`boolean` 是「是 / 否」下拉;`integer` / `number` 是数字;
`format: "asset"` 是素材选择器,`x-media: "image" | "video" | "audio"` 让它只列那一种素材(收几种就写成列表,
如 `["audio", "video"]`;画板上也只有这几种格子接得上);素材数组是挑出来的一排,
不是 JSON 框;`x-advanced` 收进「高级选项」;字符串上 `x-multiline` 给高一点的编辑框。

表单里填的都是文字。宿主在交给你之前**按 `input_schema` 把 `integer` / `number` / `boolean` 转回类型**
(空字符串当没填、去掉那一格),转不了的原样给你 —— 工作流节点送来的也是这些字符串,两条路同一个规矩。

### 技能

`skills` 是给**别的智能体**看的一段高层描述(进 `/api/agent/skills`)。工具回答"能调什么",
技能回答"这个东西是干嘛的"。

### 只读

`read_only: true` 的工具才会给**子智能体**用,智能体调它也不开确认卡(它的后果就是 `none`,见下面「确认」)。默认不标。

内置工具的只读判据是"没有确认门"—— 会改东西的都走确认卡。插件工具没有这个对应关系:它跑的是
你的代码,没有确认门也照样能发请求、写文件。所以默认落在保守那侧。宁可让子智能体少一个工具,
也不要让它在一次「帮我查一下」里替用户发了条微博。

### 确认:`effects`

智能体(应用里的助手、Claude CLI 这类 MCP 客户端、飞书)**直接调**一个插件工具之前要不要先问用户,由这个工具的
`effects` 决定 —— 它说的是「这一下的后果落在哪儿」:

| `effects` | 意思 | 智能体调它时 |
| --- | --- | --- |
| `none` | 不花钱、不出门:只读,或者只往 Mosael 自己里面写(收进素材库之类) | 直接跑 |
| `paid` | 会花钱或占付费算力(按次计费的接口、在显卡上跑生成) | 先开确认卡,归 `ai-cost` 档 |
| `external` | 后果在 Mosael 之外、撤不回:传到别人的服务器、改别处的数据、对外发送 | 先开确认卡,归 `external` 档 |
| `local-code` | 在这台电脑上执行一段**调用方写的代码**(不是你插件自己的固定逻辑) | 先开确认卡,归 `external` 档,卡上写明「会在你的电脑上运行代码」 |

```jsonc
"tools": {
  "default_effects": "paid",                      // 可选:这个包里没声明后果的工具按什么算
  "declare": [
    { "name": "render_scene", "effects": "local-code", … },   // 跑模型写的场景代码
    { "name": "upload",       "effects": "external",   … },   // 传到用户的云存储
    { "name": "import",       "effects": "none",       … },   // 只把东西收进素材库
    { "name": "list",         "read_only": true,       … }    // 只读 = none
  ],
  "overrides": { "some_mcp_tool": { "effects": "external" } } // MCP 插件只能在这里写
}
```

**默认值是 `external`**:不只读、也没写 `effects` 的工具,智能体调用前一律先问 —— 插件跑的是别人的代码,「不知道」
落在保守那一边。只读的一定是 `none`;`read_only: true` 再写别的 `effects` 是两句互相矛盾的话,**装的那一刻就报错**
(只读的工具会交给子智能体,而子智能体等不了确认卡);写了不认识的值同样当场报错,不会悄悄按 external 跑。取值顺序:
`overrides` 里的 > 工具自己声明的 > `tools.default_effects` > `external`。

几件事因此自动成立,不用插件再做什么:

- 卡上写着哪个工具、哪条连接、参数摘要和为什么要确认;批准之后走的是同一个执行入口,用的是**批准者自己**的连接
  (别人批不了你的连接);拒了什么都不跑。
- 三档权限模式照常作用(见 [AGENT_PERMISSION_MODES.md](AGENT_PERMISSION_MODES.md)):bypass 放行;auto 档下 `paid`
  按计费那一档放行(有连开上限),`external` / `local-code` 回到人;「本会话始终允许」按**这一个工具**记。
- 画板上智能体替人点运行一个工具格(`run_board_item`)读的是同一个 `effects`。
- 插件页工具旁、市场详情里,有后果的工具标着「需确认」。

**人自己点的不问**:插件页的「试一下」、工作流里的插件节点(用户自己启动的运行)、画板上自己点运行,都不开卡。

### 预算

一次调用默认最多跑 60 秒(`runtime.PLUGIN_TIMEOUT_SECONDS`)。进程插件可以在 `declare` 的那条工具上写
`timeout_seconds`,上限 1800(`tools.MAX_DECLARED_TIMEOUT_SECONDS`);不是正数就当没写。调用方显式给了
预算(Blender 互通)时以调用方为准。**预算该由最知道活有多重的一方给** —— 此前只有调用方能给,插件
说不出「这一步要三分钟」。智能体那一侧单次工具调用最多等 180 秒(`agent-sidecar/src/tools.ts`)。

**认领了生成能力的那个工具按能力给**(见「替宿主做生成」):不写是 1 小时,上限 6 小时
(`tools.MAX_GENERATION_TIMEOUT_SECONDS`,和远端生成任务的轮询上限是同一个数)—— 一段长视频在一块普通
显卡上跑一两个小时是常事。

**超时、取消停的是整棵进程树。** 你的入口脚本自成一个进程组,它起的 `node`、`ffmpeg` 在超时或取消时和它
一起停下 —— 不会在用户点了停止之后还在后台吃满 CPU。反过来,一次调用里起的进程**不该活过这次调用**:
要常驻的服务(一个本地渲染服务器)由用户自己起,插件连过去。

### 边跑边说进度:流式工具

一个要跑几分钟的工具(跑一张 ComfyUI 工作流、转一段视频),在 `declare` 的那条上写 `"stream": true`
(只给进程形态):

```jsonc
{ "name": "render_video", "stream": true, "timeout_seconds": 1800, "input_schema": { … } }
```

stdout 就和「替宿主做生成」同一套 NDJSON:进度一行一个,最后一行是结果。

```
{"event": "progress", "progress": 0.42, "message": "采样 12/20"}
{"ok": true, "output": {…}}
```

- **进度**交给宿主的上报口:在工作流节点里跑时,它成了那个节点的 `workflow.node.progress` 事件,执行面板上
  看得到「采样 12/20」;插件页试跑、智能体调用时没人听,照样能跑。
- **取消**:在任务里跑时,取消任务 = 宿主建取消文件(`MOSAEL_PLUGIN_CANCEL_FILE`),你看到它就去停远端的活,
  然后退出;30 秒不退才杀。不流式的工具取消时是直接杀掉进程 —— 远端那一份(ComfyUI 的一张图)会被它自己跑完。
- **回执不记**:普通工具不跨重启续等(那是生成任务的事)。要跑一小时以上的活,做成生成供应商。
- **预算照旧**:上限 1800 秒。智能体直接调用时一次只等 180 秒 —— 不用确认的长活(`effects: "none"`)给一个
  「只提交」的开关,交回任务号,再给一个「按任务号取回」的工具。要确认的(`paid` / `external` / `local-code`)
  是开卡、批准后在后台跑,不占智能体那一次调用的等待(ComfyUI 的工作流工具就是这样,另有 `import_outputs`
  按任务号把 ComfyUI 历史里的产出取回)。

### 持久目录

`MOSAEL_PLUGIN_DATA_DIR`:每个插件一份(`<数据目录>/plugin-data/<id>`),跨调用、跨更新都在,卸载时
随包一起删。和 `MOSAEL_PLUGIN_OUTPUT_DIR` 正相反 —— 那个是这一次调用的、用完就删。插件目录本身不能
当存储:更新就是整目录替换。

### 只供宿主使用

`overrides.<工具>.internal: true` 的工具**只给 Mosael 自己的适配层调**(例如 3D 场景与 Blender
的互通脚本),不出现在插件页的勾选列表里,智能体、工作流、画板、插件页的「试一下」都调不到 —— 图里存着
也拒绝执行。这道门在唯一的执行路径 `tools.invoke` 里(只有宿主适配层传 `host=True` 时放行)。

用在插件自带一个不经确认的原始入口、而 Mosael 已经有**带确认卡**的同一能力时:Blender MCP 的
`execute_blender_code` 就是这样,智能体建模走内置的 `blender_execute`。两条路并存的话,不经确认
的那条就是绕开确认卡的后门。

### 权限

`permissions` 是一组自由字符串(`network:example`、`assets:read`…)。**逐项授权,全部授予之后
工具才可用**。它不是沙箱 —— 沙箱是进程隔离本身;它是一次明示的"我知道这个插件要做什么"。

---

## 拿不到什么

插件进程只拿到 `PATH` / `HOME` / `LANG`,加上**它自己这个连接**声明的配置与凭据。另有 `PYTHONUTF8=1`:
协议是 UTF-8 的 JSON,stdin / stdout 不跟着这台机器的 locale 走(中文 Windows 上那是 GBK)。

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

不写就不画这个链接。仓库里的插件都写了(`backend/tests/test_first_party_plugins_name_a_homepage.py`
钉着):市场索引和插件页读的是清单里同一个值,生成索引时不再替它退到仓库目录。

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
5. 工具就出现在智能体、工作流和创意画板里了

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
| `id` / `name` / `version` | 必填。`id` 是稳定标识,改了等于换了个插件;只能用字母、数字和 `._-`,以字母或数字开头(它就是插件目录名);`name` 可写成按语言分的对象;`version` 按语义化版本写(`1.2.0`、`1.3.0-beta.1`):市场按它比先后决定「有新版」,写不成语义化版本的只能按「不相等」判 |
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
| `instance.config` | 明文配置:`key` `label` `type` `options` `required` `help` `default`;`type` 见「配置项的类型」(`json` / `code` 给代码编辑器,`code` 另写 `language`);`multiline: true` 给多行框 |
| `instance.credentials` | 密钥,字段同上;`secret` 默认 true |
| `permissions` | 自由字符串,逐项授权 |
| `provides` | 这个插件能替宿主做成哪几件事:`public_url` / `generation` / `tools`(见「声明『我能替宿主做成什么』」「运行时报出的工具」) |
| `skills` | 给别的智能体看的高层描述 |
| `tools.expose` | `"selected"`(默认)/ `"all"` |
| `tools.recommended` | 首次启用默认勾上的工具名 |
| `tools.declare` | 本地脚本的工具声明(MCP 不写,清单从服务拉)。工具名以字母开头,只用字母、数字、`_`、`-`,最长 64,不能重名。每条可写 `read_only`、`effects`(见「确认」)、`timeout_seconds`、`stream`(边跑边说进度,见「流式工具」)、`provides`、`node` |
| `tools.overrides` | 按工具名覆盖 `label` / `description` / `read_only` / `effects` / `node` / `internal` |
| `tools.default_effects` | 没声明后果的工具按什么算(`none` / `paid` / `external` / `local-code`);不写是 `external` |
| `input_schema` 属性的 `x-advanced` | 标成高级,收进面板的「高级」一档。判据:**留空也能跑**的才算 |

## 范例

`plugins/examples/` 下的范例覆盖各种形态(不写数目 —— 每加一个就错一次):

- **text-toolkit** — 纯函数,零依赖零凭据,`expose: "all"`
- **baidu-pan** — 本地脚本 + 凭据自动续期 + 收发文件 + 工作流节点
- **tikhub** — 零代码接 MCP + 多连接 + 枚举配置 + 凭据
- **blender** — 接一台本机跑着的 Blender,工具按只读/可写分开申报
- **remotion** — 用代码做动画视频:自带渲染项目,声明自己的超时预算(`timeout_seconds`),
  几百 MB 的依赖放进跨更新的持久目录(`MOSAEL_PLUGIN_DATA_DIR`),并记下是为哪一份依赖、哪种 Node 平台架构装的;
  工程源码按内容指纹放一份、放好不再改(并发的几次渲染互不踩);渲染工具只看不装,缺什么说去跑 `remotion_setup`
- **manim** — 用 Manim 做教学动画:在持久目录里用跑插件的那个 Python 建 venv、装锁定版本的依赖
  (`manim_setup`,缺系统依赖时逐条说怎么装);venv 跟着解释器走(读 `pyvenv.cfg`:挪了位置当场接回去,
  换了次版本说清楚、准备环境重建);四个工具都是**流式工具**(解析 Manim 的进度条报进度,
  取消文件一出现就连同子进程一起停);讲解视频的内容走 JSON 交给一份固定的场景,**不拼进代码**;
  会执行任意代码的工具不进 `recommended`,要用户自己勾上

  这两个插件起的子进程都不少(pip / Manim / LaTeX,npm / Node / Chrome),共用一份 `tools/plugin_kit.py`
  (两份**字节相同**的拷贝,由 `test_plugin_kits_are_identical.py` 钉住):进度条按 `\r` 逐次读、取消与时限在读输出的
  同一个循环里看、停的时候**整组**停(组长先退了也一样)、装环境上跨进程的文件锁。要起子进程的插件照抄它就好
它们都写了中英两份文案,可以直接照着抄多语言的写法。

改了这里的插件、想让用户在市场里拿到新版,**要发一版**:应用的市场读的是发版附带的索引,下载地址钉在
那次发版的 tag 上(见 [RELEASING.md「插件市场索引」](RELEASING.md#插件市场索引));只合进 main 的话,
官网插件页上的版本号会变,应用里不会出现「有新版」。

另有 `plugins/bundled/` 下**随应用一起发**的插件(今天是 **comfyui** 和 **object-storage**):它们随后端一起打包,每次启动对账
装进插件目录(按内容指纹,见 `domain/plugins/bundled`;新版本多了工具时,已经接好的连接按 `recommended` 补上开关),卸不掉。它们**也在市场索引里**(标
`bundled: true`、没有 `download`),应用内的市场和官网插件页都列出它们、标「内置」,只是不给安装 ——
新版跟着应用来;远端索引拉不到时,市场照样由本机清单列出它们。ComfyUI 插件是
「替宿主做生成」的完整范例:动态模型目录与指纹、按语言分的参数名、参考图 / 蒙版 / 视频槽位、NDJSON 进度、取消文件、
回执与接着取;也是**运行时报出的工具**(每张工作流一个,带 `replaces`、`wiring_outputs`,能表达成生成模型的带 `mirrors`)、**流式工具**和**一次交出几份文件**的范例
(工作流的工具、`import_outputs`),以及 `json` 配置项(API 模板)。

**object-storage**(「对象存储」)是 `public_url` 的第一方实现:阿里云 OSS / 腾讯云 COS / 火山引擎 TOS /
Amazon S3 / S3 兼容服务是**一个插件的五个选项**(枚举配置 `STORAGE_PROVIDER`,和 TikHub 的平台同一种写法),
不是五个插件 —— 接口是同一套(PUT/GET 对象、分片上传、列目录、XML 错误体),差异只有 `tools/providers.py`
那一张表(签名方言、默认接入点、预签名上限、寻址方式)。签名纯标准库手写:SigV4 系三家是 `sigv4.py` 里的
`Flavor`,COS 的原生签名(`q-sign-algorithm=sha1`)在 `qsign.py`;每一种都拿官方 SDK 的向量对过
(`test_*_signature_matches_the_sdk.py`、`test_object_storage_multipart_matches_the_sdk.py`)。
上传是**流式工具**(大文件分片、边传边报进度、取消时 Abort)。它随应用发,是因为宿主自己的功能
(「设置 → 素材外链」、生成时自动换直链)要靠它;此前的四个市场插件由迁移 `merge-object-storage-plugins`
原地合了进来(连接 id 不变)。

## 声明「我能替宿主做成什么」

```json
{
  "provides": ["public_url"],
  "tools": { "declare": [ { "name": "storage_upload", "provides": ["public_url"], "…": "…" } ] }
}
```

有些事宿主自己做不到,而某一类插件能做:

| 能力 | 意思 | 谁需要它 |
| --- | --- | --- |
| `public_url` | 把一份**本地素材**变成一条公网可下载的地址 | 生成链路:某些模型的参考视频 / 源视频**只收链接**(方舟 Seedance 的参考图可以走 Base64,参考视频不行) |
| `generation` | **当一家生成供应商**:列出自己的模型,做一次生成 | 选择器、画板、工作流、智能体 —— 插件的模型和内置供应商的模型一样出现(见下一节) |
| `tools` | **运行时报出工具清单** | 工具表、节点面板、智能体 —— 见「运行时报出的工具」 |

两处都要写:**包上的 `provides`** 说「这个插件能做这件事」,**工具上的 `provides`** 说「这件事归
我」。负责 `public_url` 的工具收 `{asset_id, expires}`,交回 `{url}`;签的有效期比要的短(某家的上限)
就在 `expires_in` 里如实说,宿主按它缓存 —— 否则链接失效了还被当成能用。工具上声明了包上没有的能力,
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
    "kind": "image",                       // image | video | audio(音乐 / 音效,ADR 0022);别的照列、不进选择器
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
    "prompt_dialect": "sd-tags",           // 可选:提示词优化按哪种写法改
    "prompt": "optional"                   // 可选:required(默认)/ optional / none,见下
  }
],
 "fingerprint": "9f2c…"                   // 可选:这份清单的指纹,见下面「目录变了就刷新」
}
```

- `parameters` 认的键:`type`(integer / number / string / boolean)、`enum`、`default`、`minimum`、`maximum`、
  `multipleOf`、`title`、`description`、`x-advanced`、`x-multiline`。认不出的类型整项丢掉。`title` / `description`
  可以按语言分(`{"zh": "步数", "en": "Steps"}`):宿主**原样存着、给人看时再挑** —— 目录是在后台刷新的,刷新那一刻
  的语言不是看的人的语言。`title` 写人话(「采样器」),原始的内部名(`KSampler · sampler_name`)放 `description`,
  界面上悬停看得到。**顺序就是界面上的顺序**:常用的在前,留空也能跑的标 `x-advanced`。
- **宿主自己有控件的那几个键**直接用宿主的控件:`seed`、`negative_prompt`、`size`(`enum` → 尺寸下拉)、
  `resolution` / `aspect_ratio`、`duration_seconds`(`enum` 或 `minimum` / `maximum`)、`num_images`
  (`maximum` → 张数上限,没写用 `max_outputs`)、`generate_audio`,以及音频模型的 `lyrics`(歌词编辑器)与
  `instrumental`(纯音乐开关)。**其余的键**进描述符的 `parameter_schema`,
  AI 工作台、画板、工作流节点用同一个通用控件渲染;提交时宿主按它校验类型、范围和可选值。
  用户没动过的参数**不发**,插件给的 `default` 只当占位提示(ADR 0015)。
- `inputs` 的 `role` 取宿主的素材角色(`reference_image` / `first_frame` / `last_frame` / `reference_video` /
  `source_video` / `driving_audio` / `mask` …,见 `ai/providers/contracts/generation.SOURCE_ROLES`),`max` 是这个角色
  最多几份,`required: true` 是必须给(放大、抠图这类没有提示词的工作流,图就是必须的)。认不出的角色不接。
- `prompt`:这个模型**要不要提示词**。`required`(不写就是它)要写一段;`optional` 可以空着(比如图里存着一句
  默认的提示词,空着就用它);`none` **不收**提示词(放大、抠图这类「处理一份素材」的模型)—— 宿主不摆提示词框,
  智能体不写,带着提示词提交会被当场拒。认不出的值当没写。ComfyUI 插件从图里读:没有文字喂进采样器是 `none`,
  提示词节点里存着话是 `optional`,存的是空的或模板里是 `{{prompt}}` 是 `required`。`optional` 的模型,
  `generate` 请求里的 `prompt` 可能是空串 —— 空串的意思是「没写」,用你自己的默认,不是「清成空」。
- 一次能出几张:声明 `num_images`(`maximum` 是上限,宿主一次最多 4 张)并把 `max_outputs` 设成同一个数;
  `generate` 时 `parameters.num_images` 就是这次要几张,产出几份交回几份。
- 宿主把这份清单**缓存成模型行**:连接新建、改配置、启停、授权 / 凭据变化、插件页点「刷新」,以及后端启动时
  各问一次。问不到(服务没开)就保留上一份,原因显示在插件页;清单里没有了的模型从选择器里消失。插件页上
  「查看模型」列的就是这份缓存(`GET /api/plugins/instances/{id}/models`):名字、种类、模式、收什么、有哪些参数。

### 目录变了就刷新:`fingerprint`

用户在 ComfyUI 里新存一张工作流,不该还得回插件页点一下「刷新」。可是每分钟把上百张工作流全拉一遍、转一遍也不行。
所以分两步:

- `op: models` 的结果里带一个 `fingerprint`(字符串,≤ 200 字符):这份清单的指纹 —— ComfyUI 插件用的是
  「保存的工作流的路径 + 大小 + 修改时间、粘贴的模板、几个模型目录的文件名」的哈希;
- 再支持 `op: "fingerprint"`,只回 `{"fingerprint": "…"}` —— **便宜**,只列目录,不取任何一张图。

宿主每分钟问一次指纹(`{"op": "fingerprint", "capability": "generation"}`,不留调用记录,那不是一次「调用」),
和上次刷新时记下的不一样才重新 `op: models`。`tools` 那一项同理(见「运行时报出的工具」);巡检不认识具体能力
(`domain/plugins/catalog_watch`),哪项能力上次给过指纹就问哪项。
不给指纹的插件不受影响:它们照旧只在上面那几个时机刷新。指纹问不到(服务没开)不算失败,下一分钟再问。

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
| `GET /api/plugins` | 包 + 它们的连接 + 每个连接的工具与开关;`provides`、`bundled`、`oauth`(声明了授权时是 `{fills: [授权会填的凭据键]}`),以及每个连接的 `capability_status`(几个生成模型、何时刷新、为什么没刷出来)和 `authorization`(见「连接的授权状态」) |
| `DELETE /api/plugins/{包id}` | 卸载:删目录 + 删记录 |
| `POST /api/plugins/{包id}/instances` | 新建连接 |
| `PATCH /api/plugins/instances/{id}` | 改名 / 改配置 / 启停 |
| `GET`/`PATCH` `/api/plugins/instances/{id}/credentials` | 凭据(掩码回显) |
| `GET`/`PATCH` `/api/plugins/instances/{id}/permissions` | 授权 |
| `PATCH /api/plugins/instances/{id}/capabilities` | 工具开关 |
| `POST /api/plugins/instances/{id}/refresh` | 重拉 MCP 工具清单;替宿主做生成的插件顺带重问一遍模型清单 |
| `GET /api/plugins/instances/{id}/models` | 替宿主做生成的连接**提供的模型**(缓存的那一份):名字、种类、模式、收什么、参数 |
| `GET /api/plugins/tools` | 所有可用连接**已开放**的工具 |
| `POST /api/plugins/instances/{id}/tools/{工具}/invoke` | 执行一次,留痕 |

智能体、工作流、手动试跑走的是**同一条**执行路径:权限校验、凭据注入、调用留痕都在那里。

## `instance.oauth` —— 让插件自己走一次授权

声明了它,每个连接的卡片抬头下面就多一条**授权**:这个连接授权到哪一步(未授权 / 已授权 / 需要重新授权),
一句说明,和「去授权」/「重新授权」按钮;点了之后在同一条里贴回授权码。用户不必自己手抄 refresh_token。

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
- **`stores` 指向的那几格就是「授权会填的格子」。** 界面不把它们和 AppKey 摆成一样的主输入:它们归连接第一行
  「授权」管,平时收着;点「手动填写令牌」在授权下面展开、单独保存 —— 已经有令牌的人不必走一遍授权。

### 连接的授权状态

状态由宿主算,**只看每一格填没填,不碰令牌本身**:

| 状态 | 什么时候 |
| --- | --- |
| 未授权 | `stores` 指向的格子里,标了 `required` 的还有空着的(一格都没标必填的:一格都没填)。这时连接的「为什么不能用」也说「还没授权」,而不是「缺少凭据:Refresh Token」 |
| 已授权 | 那几格填好了 |
| 需要重新授权 | 填着,但插件上一次调用时说对方不再接受已存的令牌(见下) |

格子非空不等于令牌还有效,而这一点只有真去调过一次的插件知道 —— 所以由插件说:**失败响应里带
`"reauthorize": true`**。

```python
json.dump({"ok": False, "error": "续 access_token 被拒:invalid_grant", "reauthorize": True}, sys.stdout)
```

- 只在「令牌这条路走不通了」时带:refresh_token 换不出新的、续过一次还是说过期。文件不存在、限流、
  参数不对都不带 —— 那会让人去重走一遍授权,而问题不在那儿。只认字面的 `true`。
- 宿主把它记在连接上;**重新授权、手动改了 `stores` 指向的某一格、或之后一次调用成功**,就清掉。
- 只对声明了 `instance.oauth` 的插件生效(没有「去授权」可点,记下来也清不掉);只有进程形态能说 ——
  MCP 是别人的协议。

范例见 [百度网盘插件](../plugins/examples/baidu-pan)。
