# ADR 0025: 画板上的做法、版本和端口 —— 让「想法摊开,边看边做」落进数据模型

## Status

Proposed — 2026-09-26(设计;审计发现的八个问题全部要改已获批准,本文的具体取舍待确认)。尚未动工,按文末的 Stage 1…6
分阶段落地,每一阶段单独可发;落地时照 ADR 0021 的做法在这里补「What Stage N actually did」。
沿用 [ADR 0021](0021-board-producers-registry.md) 的产出者注册表和它的「修订:画板上只放内容变换」,
[ADR 0006](0006-migrate-instead-of-branching.md) 的「改数据形状就带迁移,不留读取期分支」,
[ADR 0023](0023-plugin-tools-declare-their-effects.md) 的 `effects` 词表,[ADR 0011](0011-workspace-collaboration-event-stream.md)
的 revision / CAS。

## Context

ADR 0021 的修订把画板定位成「想法摊开,边看边做」:**内容是主角**;**发散**(并排试几版、挑一个接着做);
**人在场**;**一根线的意思是「参考它」**,不是「然后做它」;画板上只有「内容 → 内容」的变换。工作流才是
「做一次,跑无数次」。修订还写了一句:「每一格记得自己是怎么来的(提示词、模型、参考),能重生成」。

一次只读审计(下面的行号取自 main,`c4a7e3f6`)发现这几条定位在数据模型里没有落脚点,而是散在前后端的特例里。

### 1. 发散不在数据里

- 成功的回执**清空**表单上的提示词和参考素材(`backend/app/domain/boards/canvas.py:1109`,
  `form["prompt"] = ""`、`source_assets = []`);有了 `asset_id` 的格子不再挂面板
  (`frontend/src/features/boards/boardItemState.ts:25`)。于是一张生成出来的图**不记得自己是怎么来的**。
- 便签上 AI 写字**覆盖正文**(`canvas.py:1116`,`settled["text"] = text`):「改短一点」之后原文没了。
- 多出来的几张(`canvas.py:1123`)是抄了一份已清空表单的格子,和第一张之间没有任何「同一轮」的关系。
- 没有「再来一版」「换模型再来」;复制一张生成图,提示词跟着丢(它本来就被清空了)。

### 2. 一根线在不同目标上意思不同

- 内置产出者(生成、写字、念)的上游在**前端**取值:`frontend/src/features/boards/boardUpstream.ts` 把上游
  分成素材和文字;`frontend/src/features/boards/boardAssetSources.ts:13` 把 3D 场景当成一张图;文档正文由
  `documentPrompt`(`frontend/src/features/boards/boardDocumentSources.ts`)拼进提示词,便签文字对生成是**预填进
  提示词框**、对写字是 `WriteForm.context`、对念是预填要念的字;请求在 `frontend/src/features/boards/boardComposers.tsx`
  里拼好再发。
- 工具格的上游在**服务端**取值(`backend/app/domain/boards/tools.py` 的 `resolve_bindings`:3D 场景给
  `scene_id`,文档给钉住那一版的正文)。
- 因为请求是前端拼的,智能体跑不了内置产出者:`backend/app/domain/agent/confirmable/automation.py:284`
  只放行工具格(`confirmErr_runBoardItemNotTool`)。

### 3. 该是产出者声明的东西,写成了种类特例,前后端各一份、没有交叉棘轮

| 特例 | 后端 | 前端 |
| --- | --- | --- |
| 就地填 vs 派生新格 | `kind == "action"`(`canvas.py:1084`) | 按 `producerOf` 猜 |
| 产出是文字的格子 | `kind == "note"`(`canvas.py:758`) | `item.kind === "note"`(`boardItemState.ts:151`) |
| 截取不吃上游 | — | `producer !== "trim"`(`frontend/src/features/boards/BoardCanvas.tsx:562`) |
| 新格子挂哪个产出者 | `producer_for_new_slot`(`backend/app/domain/boards/producers.py:539`) | `NEW_SLOT_PRODUCER`(`boardItemState.ts:47`) |
| 智能体看得到哪些产出者 | `list_board_producers` 只留工具格(`backend/mcp_server.py:1952`) | — |

连线本身不校验:`onConnect` 什么都收(`BoardCanvas.tsx:1237`);拉线菜单(`:1033`)列全部种类和工具;
操作条上「接着做」的按钮是一张手写表(`:1797-1822`)。

### 4. 四种落点,一种线

多出来的生成结果排在同一行右边、不连线、抄表单(`canvas.py:1123`);工具产出排在右边新的一列、连线;
截一段 / 取一帧放在下面、不连线;重试就地覆盖。「从它做出来的」和「参考它」是同一种线 —— 工具格连向
产出的那根线,和便签连向图片的那根线,在数据里分不开。

### 5. 字段的意思随种类漂

- `text` 至少有四个意思:便签正文;文档标题的缓存(`canvas.py:559`);3D 场景名字的缓存
  (`frontend/src/features/boards/BoardsView.tsx:1193`、`frontend/src/features/scenes/SceneStudio.tsx:822`);
  媒体文件名(`BoardCanvas.tsx:1123`)—— 而 `frontend/src/features/boards/NodeComposer.tsx` 拿
  `saved.prompt ?? item.text` 当初始提示词,于是文件名成了提示词。
- 智能体能对任何种类 `set_text`,顺手就预填了提示词。
- 3D 场景借用 `asset_id` 放缩略图(`SceneStudio.tsx:822`、`frontend/src/features/boards/boardNodes.tsx:671`)。
- normalize 对 `text`、`color`、`asset_id` 不分种类照收,却单独限制了 `text_format` 和 `move_children`。

### 6. 只有工具格能停

停止按钮只给工具格(`BoardCanvas.tsx:780` 只对 `node.type === "action"` 传 `onStop`);生成、念、写字在跑时
没有停的地方,虽然 `cancel_job` 对它们一样有效。

### 7. 素材引用不校验

`check_canvas` 只校验 3D 场景和文档;素材的归属和种类都不查,一段音频可以放进图片格。

### 8. 「添加」菜单的分组是名词混着动词

「素材」组里既有「文档」「3D 场景」又有「从素材库选一张图」;文档**先放一个空格子再选**,3D 场景**先选再放**。

## Decision

总纲:**画板上的每一件「怎么做、放哪、接什么、这个字段是什么意思」都是一条声明,只在后端写一次,由
`GET /api/boards/producers` 发给界面和智能体;前端读,不抄。** 下面按五块结构说,最后给分阶段计划。

### 决定 1:做法(recipe)和草稿(draft)分开;再跑一次落成一个新版本,不覆盖

**两个概念:**

- **草稿**(`form`,已有)—— 「下一次运行会发什么」。只活在**还没有产出**的格子上(空槽、跑挂了的、
  工具格)。用户和智能体编辑它。
- **做法**(`recipe`,新增)—— 「这一格是怎么做出来的」。**服务端**在回执成功落产出的那一刻写下,之后只读:
  界面拿来显示,「再来一版」拿来当新草稿的起点。客户端和智能体都写不了它(和 `run`、产出一样归服务端,
  见 `_keep_server_owned_state`)。

**一格的生命周期因此变成:**

```
空槽(form=草稿) ──运行──▶ 在跑(form=草稿, run) ──成功──▶ 有产出(recipe=那份草稿, form={producer})
       ▲                           │失败/取消                          │
       └───────── 就地重试 ◀────────┘(草稿原样留着)                  │「再来一版」/「换模型再来」/「改一改再来」
                                                                     ▼
                                            右边新的一格(同一个 version_group, form=做法里的草稿⊕改动)──运行──▶ …
```

- 成功时草稿**搬进**做法,`form` 退回只写着产出者 —— 不是「清空」(`canvas.py:1109` 那段删掉),也不是
  两份并存(画布不会因此大一倍)。
- 一格有了产出,就**不再就地重跑**:对它运行(界面的按钮、智能体的 `run_board_item`、`/run`)一律在它右边
  新建一格同种类的格子、带上同一份做法(可带改动),在那一格上跑。于是「重试覆盖」这种落点消失:
  能就地重试的只剩没产出的格子,它没有东西可覆盖。
- **便签也一样。** 空便签上写字就地填;**有字的便签**上让 AI 改(「改短一点」),改写落成右边新的一张便签,
  原文不动 —— 手写的便签也算「有产出」。原便签是这次改写的一份输入(做法里的 `base`),不是被改的对象。
- 生成一次出多张:第一张填进宿主,其余是同一组的版本,每张都带这份做法。

**做法的形状**(`item.recipe`):

```jsonc
"recipe": {
  "producer": "generate",
  "form": {                                  // 跑的那一刻的草稿,去掉 producer;含 bindings
    "prompt": "黄昏的海边,胶片颗粒",
    "prompt_document": { "type": "doc", … },  // 超出单份做法上限时不存(见「性能」)
    "mentioned_asset_ids": ["as_12"],
    "provider_profile_id": "pp_…", "provider": "…", "model": "…", "mode": "…",
    "parameters": { "size": "1024x1024" },
    "source_assets": [{ "asset_id": "as_12", "role": "reference_image" }],   // 手动挂的
    "bindings": { "prompt": [{ "from": "note_3" }], "references": [{ "from": "img_2", "role": "first_frame" }] }
  },
  "inputs": [                                // 这一版当时**实际用了什么**(只记引用,不抄正文)
    { "port": "prompt", "from": "note_3" },
    { "port": "references", "from": "img_2", "role": "first_frame", "asset_id": "as_91" },
    { "port": "references", "role": "reference_image", "asset_id": "as_12" }
  ],
  "host": "act_7", "output": "vocals",       // 只在派生产出上:哪个工具格、它的哪一个输出
  "text_hash": "…",                          // 只在产出是文字时:落下那段字的摘要
  "job_id": "job_…", "ran_by": "user_…", "ran_at": "2026-10-02T09:12:00Z"
}
```

- 便签的产出(正文)之后还能手改;`text_hash` 对不上时做法照旧显示,但标一句「做出来之后手动改过」。

- `inputs` 记素材 id(小、在库里永远查得到名字),文字输入只记 `from`:便签正文不抄进做法。上游那张便签后来
  改了字,做法显示「参考了便签 note_3」而不是当时的原文 —— 这是有意的取舍(见「性能」和「非目标」)。
- 「再来一版」按做法里的**绑定**再取一次上游:上游改了字,新的一版就用新的字。画板是活的,「改了上游再来一版」
  正是最常见的一步;要冻住某一版的输入,那一版的输入格子就在桌上。

**版本组**(`item.version_group`):一个不透明 id(`vg_…`)。第二个版本出现时服务端生成它,同时写给原来那一格。
不指向某一格(删掉第一版不会让组悬空)。组内的先后按 `recipe.ran_at`;没有做法的格子(贴进来的素材)
加入组时排最前。

**并排的兄弟格 vs 格内的版本叠** —— 选**兄弟格**:

| | 兄弟格(选这个) | 格内版本叠(`versions: [...]`) |
| --- | --- | --- |
| 画板定位 | 并排就是比较:同一句提示词三个模型、三版摆成一行,一眼看完 | 一次只看得见一版,比较要来回翻 |
| 杂乱 | 格子会变多;用版本徽标(「第 2/3 版」)、悬停高亮同组、以后可加「收起其余版本」(纯显示)缓解 | 画布干净 |
| 下游 | 每一版是普通格子,各自能连出去、能被绑定;「挑一个接着做」就是从那一格连线 | 线接的是格子不是某一版:每个取值的地方(绑定、`resolve`、`upstreamOf`)都得先问「现在是哪一版」,等于给所有读者加一条分支 |
| 智能体 | 现成的算子全能用(按 id 移动、连线、删除、读);不需要新词汇 | 要新算子(切版本、删某一版)和新的读法 |
| 撤销 | 普通格子,快照撤销天然成立(见「撤销 / 重做与 CAS」) | 版本叠是一格内的数组,和服务端回执抢同一个字段,撤销要逐项合并 |
| 迁移 | 旧格子什么都不用变 | 每一格变形状 |

所以:版本是**并排的兄弟格 + 一个组 id**,不是一格里的数组。组 id 只服务于显示(徽标、同组高亮、「收起其余
版本」),不参与取值 —— 取值永远按格子和线。

**版本的线。** 新版本**复制宿主进来的参考线里被绑定用到的那几根**(上游 → 新格),否则做法里的绑定在新格上
接不上(绑定必须有线,见 `check_bindings`);版本之间不连线,靠组 id。派生产出的版本:工具格再跑一次,新产出
照旧落成新的一列(见决定 2),每一格按 `recipe.output`(输出名)加入上一轮同名产出的版本组。

### 决定 2:一个落点服务,一种来历线

**产出者声明 `landing`**,三种:

| `landing` | 意思 | 谁 |
| --- | --- | --- |
| `in_place` | 产出填进宿主那一格。宿主已有产出时 → 自动落成它的一个新版本(`sibling_version` 放法) | generate、write、speak、trim、frame |
| `derived` | 宿主是工具格;每份产出是右边新的一格,连一根**来历线** | `node:*`(缺省) |
| `sibling_version` | 产出是**被处理那份内容的新版本**(放大、去背景、降噪):落在源格子的版本行里,加入它的版本组,连一根来历线 | 声明了 `mirrors` 的 `node:*`(见「与进行中的工作」) |

`sibling_version` 取代 ADR 0021 P4 设想的「`node:*` 在媒体格上就地产出」:**画板上没有任何产出覆盖别的东西**。

**一个放法函数** `place_outputs(canvas, host_id, outputs, policy) -> (new_items, new_edges)`,放在
`domain/boards/placement.py`(新),`canvas`、`tools`、各内置产出者全都经它:

- `fill`:第一份填进宿主;其余按 `sibling_version`。
- `sibling_version`:宿主所在那一行、同组最右一格的右边,和宿主同样大小,间距沿用今天的 24。
- `derived`:宿主和它此前派生出的几列的右边新开一列,从宿主的顶边往下排(今天的 `_derive`)。
- 每种放法最后过同一个 `first_free(rect, axis, items)`:与任何已有格子(外扩一个间距)相交就沿本放法的轴
  (版本向右、派生向下)挪到第一个空位。于是「版本往右长」和「派生列在右边」不会叠在一起。
- 需要**先有一格**才能跑的产出者(截一段、取一帧:从一段片子上做出一格新的)也用它放那一格占位:
  `RunRequest` 多一个 `source_item_id`,服务端按 `derived` 相对**源格子**摆出占位、连一根来历线,再在
  占位上 `in_place` 跑。截一段不再放在下面、不连线;前端不再算 `y + height + 60`。
- **取一帧**变成内置产出者 `frame`(`landing: in_place`,源是视频,产出一张图,`effects: none`,和写字一样经
  `run_job_inline` 同步跑)。此前它是前端直接调 `grabAssetFrame` 再 `add` 一格,智能体做不了、落点自成一派。

**来历线**:边多一个可选字段 `kind`,取值只有 `"provenance"`;缺省就是参考线。

```jsonc
{ "id": "act_7->act_7-out-1", "source": "act_7", "target": "act_7-out-1", "kind": "provenance" }
```

- **来历线永远不供值**:`resolve`、`_drop_detached_bindings`、`check_bindings`、前端的上游列表只看参考线;
  来历线上挂不了绑定。
- 只由服务端的放法写;用户和智能体画不出来(`onConnect`、`connect` 算子只建参考线),但都能删。
- 界面画成虚线、无箭头、不高亮成「输入」;右键「用它做参考」把它改成一根参考线(改的是 `kind`,线还是那根)。
- 工具格连出去的线今天全是「做出来的」(工具格从来不当上游),迁移把它们标成来历线。

### 决定 3:内置产出者也用端口 + 服务端取值;只有一个 `resolve`

**端口声明**。每个产出者声明自己的输入端口(`ports`),工具格的端口就是它能接上游的那些配置字段(今天的
`binding_sink`),内置的写明:

```jsonc
"ports": {
  // generate
  "prompt":     { "sink": "text",  "accepts": ["note", "document"], "combine": "material", "draft_field": "prompt", "required": "by_model" },
  "references": { "sink": "asset", "accepts": ["image", "video", "audio", "scene"], "roles": "by_model", "many": true }
}
// write:  "material": { "sink": "text+asset", "accepts": ["note","document","image","video","audio","scene"], "many": true }
// speak:  "text":     { "sink": "text", "accepts": ["note","document"], "combine": "replace", "draft_field": "prompt" }
// node:*: 每个能接上游的字段 → { "sink": …, "accepts": …, "combine": "replace", "draft_field": <字段名>, "many": <*_asset_ids> }
// trim / frame: 没有端口(consumes_upstream: false),源素材是草稿里的 trim.asset_id / frame.asset_id
```

- `accepts` 由**格子能给出什么**(字段表里的 `provides`,见决定 5)和端口的 `sink` 推出来,服务端算一次;
  工具字段上今天的 `board_sources` 并进 `ports[字段].accepts`,旧名删掉(ADR 0006,同一发布单元不留旧名)。
- `combine` 两种:`replace` —— 接了上游就用上游的值,没接用草稿(工具字段、念的字);`material` —— 草稿是
  **指令**,接进来的文字按连线先后作为**材料**附在后面(今天 `documentPrompt` 的格式),草稿为空时材料本身
  就是提示词。便签对生成**不再预填进提示词框**:框里只有人写的字,接进来的便签显示成一枚「提示词 ← 便签」的
  标签,要改那段字就去改便签(标签上有「抄进来编辑」,抄进来之后就断开这条绑定)。
- `roles: "by_model"`:参考端口能收哪些角色、各几份,由所选模型的描述符说(`source_limits`、互斥组,见
  ARCHITECTURE「generation」一段),服务端和面板读的是同一份生成目录。

**绑定**沿用 `form.bindings = {端口: [{"from": 上游格 id}]}`,每条多一个可选 `role`(参考端口用)。今天挂在
`form.source_assets[]` 上、带 `from` 的那几份迁成 `bindings.references`;不带 `from` 的(手动挂的)留在草稿里。

**一个 `resolve`**:`tools.resolve_bindings` 升级成 `resolve_ports(db, board, item_id, producer, draft)`,
按连线先后、按端口声明取值 —— 便签给正文、文档给钉住那一版的正文、媒体给素材、3D 场景给 `scene_id`
或(给图片端口时)`preview_asset_id`。**画板上只有这一处从上游取值。** 各产出者拿到取好的值再拼自己的请求:
generate 在服务端拼提示词(`material` 规则、`@` 素材的图例,今天在 `NodeComposer` 里拼)和发出去的素材清单;
write 把材料分成文字和素材(`look_at` 不变);speak 拿到要念的字;`node:*` 照旧填进配置。

**默认绑定由服务端写,一处。** 一根新的参考线连进一个产出者格子时,`bind_new_edge(canvas, edge)` 按目标端口的
声明写下默认绑定(唯一接得上的端口;参考端口按模型描述符挑角色 —— 今天 `NodeComposer.autoAssign` /
`defaultMode` 的规则搬到服务端)。智能体的 `connect` 算子调它;客户端自动保存时,服务端在
`_keep_server_owned_state` 旁边认出「这次多出来的参考线」同样调它,保存的回包带回写好的绑定,前端照
`prunedLinksPatch` 的样子加一个对称的 `addedLinksPatch` 收下。**服务端只解析存下的绑定**(ADR 0021 P2 的规矩不变)。

**面板变成声明驱动的表单 + 上游标签。** `boardUpstream` 只列「连进来的是哪几格」给标签用,不再分素材 / 文字、
不再拼值;`boardAssetSources`、`boardSourceText`、`documentPrompt` 删掉;`BUILTIN_COMPOSERS` 交出去的是**草稿**,
不是拼好的请求(`GenerateForm.item_form` 那层「发出去的 vs 存下来的」随之消失)。

**之后 `run_board_item` 跑任何产出者**:它从画布上读那一格的草稿(或有产出时读做法),和界面走同一个
`producers.run`;`confirmErr_runBoardItemNotTool` 删掉。卡按产出者的 `effects` 开(生成、写字、念是 `paid`
→ ai-cost;截取、取帧 `none` 直接跑)。`set_form` 对内置产出者开放:草稿按产出者的 pydantic 草稿模型校验
—— P3 拒绝的理由(「面板没见过的表单会打不开」)在草稿有了一份声明之后不再成立。

### 决定 4:把种类特例改成产出者声明,前端读不抄

`Producer` 多这几项,全部随 `GET /api/boards/producers` 发出:

| 声明 | 取值 | 替掉的特例 |
| --- | --- | --- |
| `landing` | `in_place` / `derived` / `sibling_version` | `canvas.py:1084` 的 `kind == "action"` |
| `output_kinds` | 产出落成哪几种格子(`in_place` 就是宿主种类;`node:*` 由输出声明推,即进行中的 `board_products`) | 前端猜 |
| `consumes_upstream` | `bool(ports)` | `BoardCanvas.tsx:562` 的 `producer !== "trim"` |
| `default_for_kinds` | 新放下的这种格子挂谁;一种格子至多一个 | `producers.py:539` 和 `boardItemState.ts:47` 两张表 |
| `ports` / `accepts` | 见决定 3 | `onConnect` 全收、拉线菜单全列、操作条手写表 |
| `cancel` | `stops`(真停得下:进程、远端取消)/ `discards`(停不下,只丢结果:同步写字、MCP 插件) | 只有工具格能停 |

`canvas` 不能 import `producers`(导入环,见 ADR 0021 P2),所以回执要用的 `landing` 和格子的产出字段放在
`backend/app/domain/boards/producer_ids.py` 那张无依赖的表旁边(`landing_of(producer_id)`),注册表从它读、棘轮
核对二者一致。

**响应形状**:`GET /api/boards/producers` 从一个列表变成
`{"kinds": {种类: {…字段表…}}, "producers": [...]}`(字段表见决定 5;Stage 1 先只带 `output_field` 和 `provides`)。

**前端从声明推出:**

- **连线校验**:`onConnect` 只在目标格子的产出者(草稿上的 `form.producer`,有产出时是 `recipe.producer`)有端口
  `accepts` 源的种类时建线;否则不建,在锚点旁说一句「图片用不上这张便签」。
- **拉线菜单**和工具条「添加」是**同一份目录**(决定 6),按 `accepts` 和拉线方向过滤:从一格的出口拉出来,列
  「有端口收它」的产出者和工具;从一格的入口拉出来,列「它的端口收得下」的来源。
- **操作条上的「接着做」**:选中一格,列出 `default_for_kinds` 产出者里有端口收它的那几种(接着出图 / 视频 /
  音频 / 文字),以及按 `board_group` 分好的工具 —— 就是 ADR 0021 修订「下一版」里说的「选中一格内容,就地列出
  能用在它身上的变换」。手写表删掉。
- **新格子的产出者**:`default_for_kinds`;`newSlotForm` 的表删掉,后端 `producer_for_new_slot` 从注册表读。
- **回执 / 保存的产出字段**:`kinds[种类].output_field`(便签是 `text`,媒体是 `asset_id`),替掉
  `canvas.py:758` 和 `boardItemState.ts:151` 的 `note` 特例。

**存下来的线不因规则而失效。** 一根不被任何端口用上的参考线(产出者后来换了、插件卸了)照样存得下、读得回,
画成细灰线并提示「没被用上」;规则只管**建线的那一刻**(界面、`connect` 算子)。这和 normalize 只查产出者名字、
不问它此刻能不能跑是同一个理由,不是兼容分支。

### 决定 5:每种格子一张字段表,生成校验、算子和前端类型

`domain/boards/fields.py`(新)里一张表 `ITEM_FIELDS`:种类 → 字段 → `FieldSpec(类型, 意思, 谁写, provides, ref)`。

| 种类 | 内容 / 产出 | 引用 | 运行 | 其他 |
| --- | --- | --- | --- | --- |
| 共有 | — | — | — | `id` `kind` `x` `y` `width` `height` `title` |
| `note` | `text`(正文;人写或写字产出;provides `text`)、`text_format` | — | `form` `run` `recipe` `version_group` | `color` |
| `image` / `video` / `audio` | `asset_id`(产出;provides `asset:<种类>`;ref 同种类素材) | — | `form` `run` `recipe` `version_group` | — |
| `document` | — | `note_id` `note_revision`(provides `text`:钉住那一版的正文)、`ref_title`(服务端写) | — | — |
| `scene` | — | `scene_id`(provides `scene`)、`preview_asset_id`(provides `asset:image`;ref 图片素材) | — | — |
| `frame` | — | — | — | `move_children` |
| `action` | — | — | `form` `run` | — |

「谁写」三种:`user`(界面和智能体都能写)、`server`(`run`、`recipe`、`version_group`、`ref_title`,以及有产出者的
格子上的产出字段)。这张表生成:

- **normalize**:一格上出现表里没有的字段 → `boardErr_fieldNotForKind`(拒,不丢 —— 「写错的字段一律拒绝」);
  每个字段的值校验照旧。`text_format` / `move_children` 的单独判断并进表。
- **算子**:`add_item` 只收这种格子 `user` 可写的字段;`set_text` 只对 `text` 可写的种类(便签);`set_color` 只对便签。
  智能体再也预填不了提示词。
- **前端类型**:`backend/app/api/schemas/boards.py` 用这张表 `create_model` 出每种格子一个 pydantic 模型,拼成
  以 `kind` 区分的联合类型;OpenAPI → `frontend/src/api/generated/schema.d.ts` 于是是一个判别联合 ——
  对没收窄的 `BoardItem` 读 `.text` 是编译错误,`tsc` 就是这条规矩的棘轮。
- **取值**:决定 3 里「哪种格子给哪种值」读 `provides`,`tools._SOURCE_KINDS` 删掉。

**名字的缓存改成现读或明写:**

- 文档:`text` → `ref_title`。钉住的那一版的标题**不会变**,所以这不是会过期的缓存,是那一版的事实;服务端在
  `check_canvas` 解析引用时写(今天写进 `text` 的同一处),客户端写不了。
- 3D 场景名、媒体文件名:**现读**。场景能改名、素材能在库里改名,存一份就会过期。`GET /api/boards/{id}` 的
  回包多一张只读的侧表 `references: {assets: {id: {name, kind}}, scenes: {id: {name}}}`,读时现查、不进画布;
  节点标签、查找(`boardSearch`)、智能体的 `get_board` 都读它。
- 3D 场景的缩略图:`asset_id` → `preview_asset_id`。它也是场景接进图片端口时给出的那张图
  (今天 `boardAssetSources` 把场景当图的那条规则,变成字段表上的一个 `provides`)。

**素材引用校验(问题 7)**:`check_canvas` 对表里标了 `ref` 的字段(`asset_id`、`preview_asset_id`、
`form.source_assets[].asset_id`、`form.mentioned_asset_ids`、`form.trim.asset_id`)查「在这个工作区、种类对得上」:
不在 → `boardErr_assetNotInWorkspace`,种类不对 → `boardErr_assetKindMismatch`。**已经在板上的引用不再校验**
(和文档、场景同一条:素材删了,那一格照样能挪、能删、能复制),按「引用的是哪份素材」认,不按格子 id 认。

### 决定 6:「添加」是一份按动词分组的目录;空的产出格子有一个模板

组名是动词,行是名词;拉线菜单是同一份目录按 `accepts` 和方向过滤:

| 组 | 行 | 放法 |
| --- | --- | --- |
| 生成 | 图片 / 视频 / 音频 / 文字 | 放一格空槽,挂 `default_for_kinds` 的产出者 |
| 从素材库 | 图片 / 视频 / 音频 | **先挑再放** |
| 引用 | 笔记 / 3D 场景 | **先挑再放**(文档今天先放空格再挑,改成和场景一样) |
| 整理 | 便签 / 分组 | 放一格 |
| 工具 | 按吃什么内容分组(`board_group`,不变) | 放一格工具格 |

「生成 · 文字」放的是挂写字产出者的空便签;「整理 · 便签」放的是同一种格子 —— 区别只在空态模板说的那句话
(一个等你让 AI 写,一个等你自己写),数据上都是 `note` + `write`。

**空的产出格子的模板**(内置和工具格同一个壳):种类图标(工具格用进行中的 `nodeIcons`)、一句动词开头的话
(「写一句话,生成一张图」「接一段视频进来,转成文字」)、次要动作(「从素材库挑一张」「连一张便签当提示词」)、
上游摘要(「提示词 ← 便签『开场』;首帧 ← 图 2」,读存下的绑定)。

**停止属于运行态的壳**:所有在跑的格子(不只工具格)在同一个外壳上有「停止」,调 `cancel_job`;按产出者的
`cancel` 说「停下」或「不要这次的结果」。远端生成的取消照 ADR 0019:提交了的远端任务,供应商可能照样计费,
按钮的说明写明。

## 智能体工具

| 工具 | 变化 | 阶段 |
| --- | --- | --- |
| `list_board_producers` | 返回全部产出者(不再只留工具格)和 `kinds`;带 `landing`、`default_for_kinds`、`ports.accepts` —— 智能体据此知道一根线接到哪一格才有意义 | 1(表)/ 5(完整字段表) |
| `edit_board` · `connect` | 按 `accepts` 校验(`boardErr_edgeNotAccepted`),只建参考线,并调 `bind_new_edge` 写默认绑定 | 1(校验)/ 3(绑定) |
| `edit_board` · `add_item` | 缺省产出者读 `default_for_kinds`;字段按字段表收;`asset_id` 要对得上种类 | 1 / 5 |
| `edit_board` · `set_form` | 对内置产出者开放;草稿逐键合并(null 删键),改了 `prompt` 就丢掉 `prompt_document` | 3 |
| `edit_board` · `set_text` / `set_color` | 只对便签 | 5 |
| `edit_board` · 任何算子 | 写不了 `run`、`recipe`、`version_group`、`ref_title`、`kind: "provenance"`;`remove_edge` 能删来历线 | 2 / 4 / 5 |
| `run_board_item` | 跑任何产出者;对有产出的格子 → 新版本;多一个 `form_overrides`(换模型、改提示词、改参数)合在做法上;回 `{board_id, item_id, producer, job_id}` 里的 `item_id` 是**真正在跑的那一格** | 3 / 4 |
| `get_board` | 看得到 `recipe`、`version_group`、线的 `kind` 和 `references` 侧表 | 2 / 4 / 5 |

`POST /api/boards/{id}/run` 的回包从 `Board` 变成 `{board, item_id}`:在有产出的格子上跑、截一段、取一帧时,
跑起来的是服务端新放的那一格,调用方要知道是哪一格(Stage 2 起)。backend 系统提示词、前端画板助手的上下文、
MCP 文档串随各阶段更新。

## 撤销 / 重做与 CAS

- **撤销只撤人的编辑,不撤回服务端落下的东西。** 撤销栈(`frontend/src/features/boards/canvasHistory.ts`)存的是
  整份快照;回到一份快照时,前端把**服务端归属的格子**(在跑的、带做法的新格子、版本、派生产出)和它们的来历线
  补回去 —— 和 `_keep_server_owned_state` / `serverOwnedPatch` 同一条规则,只在「应用这一份快照」时做一次,
  不去改写历史里那一百份快照。于是撤销不会把一次花了钱的生成撤成「从没发生」,也不会把在跑的一格撤没。
- **删除在跑的格子要先停。** 手动删一格在跑的(不是撤销),先问「停下并删除?」,确认后 `cancel_job` 再删;
  不停的话回执落不回来,钱照花。
- **CAS 不变。** 新版本、派生产出、截取 / 取帧的占位都经 `_merge_into_latest`(服务端写,在最新画布上重算落点,
  revision + 1);手上有未存编辑的客户端照旧撞 409、拉最新的再合。落点在合并函数里算,所以不会基于一份旧画布摆位置。
- 默认绑定(`bind_new_edge`)跟着客户端的那次保存一起落库,是同一个 revision,不另起一次写。

## 协作事件

- 服务端对单格的合并今天一律记成 `board.updated`「编辑了无限画布」。改成按事实记:`board.item_made`
  (payload:`item_ids`、`producer`、`version_group`)、`board.item_failed`;客户端的自动保存照旧 `board.updated`。
  团队动态里于是能读到「X 在『海报』上出了第 3 版」,而不是一串「编辑了无限画布」。
- 打开着同一张板的其他人:和今天一样靠 revision —— 下一次拉取或保存撞 409 时看到新版本。`board.item_made` 给
  以后的实时刷新留好了钩子;实时多人合并不在本 ADR 内。
- 评论挂在格子上(`comment canvas context`),新版本是新格子,评论不跟着搬:对第 2 版的意见就是对第 2 版的。

## 性能:画布大小

- 做法**替代**了成功后被清空的那份草稿,不是额外一份;单份做法上限 8 KB(序列化后),超了就不存
  `prompt_document`(纯文字提示词和 `mentioned_asset_ids` 照存,「改一改再来」时从纯文字重建编辑器文档)。
- 版本让格子变多:`MAX_ITEMS = 2000` 不变;单次运行最多新建的格子沿用 `MAX_DERIVED_ITEMS = 12`,生成的多张按模型
  `max_num_images` 本来就有上限。
- `place_outputs` 的空位搜索按格子的外接矩形线性扫,O(格子数 × 新格子数),2000 格量级无需索引。
- `resolve_ports` 每次运行对每篇接进来的文档读一次钉住的版本(今天前端也要读),不缓存。
- 自动保存仍是整份快照;做法让单次保存变大。Stage 4 带一条性能棘轮:2000 格、每格一份满额做法的画布,
  `normalize_canvas` + `check_canvas` 在实现时实测的预算内完成,回包大小记录在测试里。增量保存不在本 ADR 内。

## 与进行中的工作

- **实体 id 字段变下拉(`options_from`)**:下拉给的是**草稿值**;字段若也是端口(素材、场景这种指向画板内容的
  字段),接了上游就用上游(`combine: replace`),标签显示在下拉上方。只指向库里实体、画板上没有对应格子的
  (连接、账号)不是端口。`binding_sink` 今天对带 `options_from` 的文字字段已经返回「接不了」,这一条不变。
- **工具格的视觉重做**(`0e4e7366`,未合入):它新加的 `board_products` 就是本 ADR 的 `output_kinds`,合并时
  保留一个名字(`output_kinds`);`boardToolFace` 的「吃什么」改读 `ports`;它挪进 `boardTools` 的
  `defaultBindings` 在 Stage 3 被服务端的 `bind_new_edge` 取代,格子上只读存下的绑定;`nodeIcons` 给决定 6 的空态模板用。
- **ComfyUI 的 `mirrors` / 只为接线的输出声明**:只为接线的输出不进 `output_kinds`、不落板(和今天的 `board_outputs`
  同一条)。一个落板输出若声明 `mirrors: <素材字段>`(输出是那份输入的新版本:放大、修脸、去背景),这个工具的
  `landing` 就是 `sibling_version`:产出落在被接进那个字段的源格子的版本行里。没声明的仍是 `derived`。
- **生成能力的证据**:`roles: by_model` 和「换模型再来」可选的模型读同一份生成目录;证据让描述符更准,端口的
  `accepts` / 角色上限随之变,画板这边不用改。做法里记 `provider_profile_id` + `model`(不记描述符快照):
  「再来一版」时按**当下**的描述符校验,模型不再收某个角色时,开跑前在面板上说清楚是哪一份输入用不上了。

## 迁移

每一次改数据形状都带一条自动迁移:有 slug、幂等、改到的板 `revision + 1`(升级那一刻还开着这张板的客户端撞 409
重拉,而不是把旧形状存回来)、登记进 `backend/app/db/migrations.py` 的 AFTER_SCHEMA 步骤、冻结进
`migration_bodies.json`、在 `test/upgrade_db_fixture.py` 的旧画板里有一个对应的形状,并有自己的测试。**没有读取期分支。**

| 阶段 | slug | 做什么 |
| --- | --- | --- |
| 2 | `migrate-board-tool-output-edges-are-provenance` | 源头是工具格的线 → `kind: "provenance"`(工具格从不当上游,所以它连出去的每一根都是「做出来的」) |
| 3 | `migrate-board-slots-bind-their-upstream` | 生成:`source_assets` 里带 `from` 的 → `bindings.references`(带角色);进来的文档线 → `bindings.prompt`(今天它们总被拼进提示词);提示词正好等于上游便签按序拼起来的那段(自动预填的)→ 清空提示词、绑上这些便签,否则(人改过)提示词留着、便签不绑。写字:所有进来的便签 / 文档 / 媒体线 → `bindings.material`(今天它们全被当材料)。念:和生成的预填规则同一条,绑 `text` |
| 4 | `migrate-board-made-cells-remember-their-recipe` | 有产出的生成格:按素材在生成历史里找(`GeneratedAsset` → 它那一轮的 `GenerationJob.request`,本工作区),补一份做法;截出来的格子:`form.trim` 就是完整做法。找不到的(贴进来的素材、念出来的 —— 要念的字已经被清空了)**不补**:半份做法会让「再来一版」念一段空白,没有做法是一个正常状态(「没有记下做法」)。补上做法的格子 `form` 退回 `{producer}`。多张同一轮的(`<id>-<n>` 且做法相同)编进一个版本组 |
| 5 | `migrate-board-reference-names-leave-text` | 文档 `text` → `ref_title`;场景 `text` 删掉(现读);媒体格:空槽且草稿没有提示词时 `text` → `form.prompt`(界面一直把它当提示词显示),有产出的格子 `text` 等于素材名就删,不等(智能体写的)且没起名就进 `title`(按标题规则收空白、截到 120 字),否则删 |
| 5 | `migrate-board-scene-preview-leaves-asset-id` | 场景的 `asset_id` → `preview_asset_id` |
| 5 | `migrate-board-stray-fields-leave-other-kinds` | 非便签上的 `color`、工具格上的 `text` 删掉(界面从没显示过它们) |
| 5 | `migrate-board-media-cells-match-their-asset-kind` | 媒体格的种类跟着素材的种类走(音频素材在图片格里 → 那一格变成音频格);素材不在的(删了)不动,按「已有引用」放过 |

## 棘轮

| 阶段 | 棘轮 | 锁住什么 |
| --- | --- | --- |
| 1 | `test_board_producer_declarations.py` | 每个产出者的 `landing` 合法;`default_for_kinds` 两两不交;`consumes_upstream == bool(ports)`;`accepts ⊆ ITEM_KINDS`;`producer_ids.landing_of` 与注册表一致 |
| 1 | 前端 `boardDeclarations.test.ts`(RATCHET) | `features/boards` 里不出现产出者 id 的字面比较(`=== "trim"` 一类)、`NEW_SLOT_PRODUCER` 式的种类→产出者表、`kind === "action"` / `kind === "note"` 的行为分支(节点渲染表除外,白名单写明理由) |
| 1 | `test_board_run_state_shell` | 每个产出者的在跑格子都有停止;`cancel` 与产出者一致 |
| 2 | `test_board_placement.py` | 随机画布上每种放法都不与已有格子相交;派生 / `sibling_version` 都连来历线;`fill` 不产生线 |
| 2 | `test_board_provenance_never_feeds.py` | 来历线上的绑定被摘掉、`check_bindings` 拒绝、`resolve_ports` 不取值;`connect` 算子造不出来历线 |
| 3 | `test_board_one_resolve.py` | 画板领域里读上游值(`read_reference`、上游的 `text` / `asset_id` / `scene_id`)的只有 `resolve_ports`(和 `check_canvas` 写 `ref_title`) |
| 3 | 前端 `boardComposersSendDrafts.test.ts`(RATCHET) | 面板交出去的是草稿:`boardComposers.tsx` 不再引用上游的文字 / 素材值;`documentPrompt`、`boardAssetSources`、`boardSourceText` 不再存在 |
| 3 | 同一次运行两个入口 | 界面的 `/run` 和智能体的 `run_board_item` 对同一格发出的 `GenerationJob.request` 完全相同 |
| 4 | `test_board_recipes.py` | 成功必写做法、`form` 退回 `{producer}`;有产出的格子上运行一定落成新格子、原格一个字段不变;便签改写不改原文;客户端 / 算子写不了 `recipe` / `version_group`;复制带着做法 |
| 4 | 性能棘轮 | 见「性能」 |
| 5 | `test_board_item_fields_table.py` | 对每个种类 × 表外字段,normalize 都拒;OpenAPI 的 `BoardItem` 联合与表一一对应;`add_item` / `set_text` 只写得了表里 `user` 可写的字段;`provides` 与 `accepts` 一致 |
| 5 | `test_board_asset_references.py` | 新引用的素材要在本工作区、种类对得上;已有引用放过(素材删了照样能存) |
| 5 | `tsc` | 判别联合:没收窄就读 `.text` / `.asset_id` 编译不过 |

## 分阶段计划

依赖顺序:声明 → 落点 + 来历 → 端口 / 服务端取值 → 做法 / 版本 → 字段表;「添加」目录最后。每一阶段单独可发、
单独有用户看得见的结果,不依赖后面的阶段。

### Stage 1 · 产出者声明,前端读不抄

- **范围**:`Producer` 加 `landing`、`output_kinds`、`consumes_upstream`、`default_for_kinds`、`ports`(含 `accepts`;
  内置的端口此阶段**只声明**,取值仍在原处)、`cancel`;`producer_ids.landing_of`;`GET /api/boards/producers` →
  `{kinds, producers}`,`kinds` 先只带 `output_field` 和 `provides`;回执和 `_keep_server_owned_state` 读
  `landing` / `output_field`,删掉 `kind == "action"` / `kind == "note"`;前端删 `NEW_SLOT_PRODUCER`、
  `producer !== "trim"`、操作条手写表,连线校验、拉线过滤、「接着做」按钮从 `accepts` 推;停止挪进运行态外壳,
  所有在跑的格子都有;`list_board_producers` 返回全部产出者;`connect` 算子按 `accepts` 校验。
- **迁移**:无(不改存下的形状)。
- **棘轮**:声明一致性、前端不抄、运行态外壳。
- **用户看到**:连不上的线连不上(并说为什么);拉线菜单只列用得上的;选中一格,「接着做」按钮按内容给;
  生成、念、写字在跑时也能停。

### Stage 2 · 一个落点服务 + 来历线

- **范围**:`domain/boards/placement.py` 的 `place_outputs` 和 `first_free`,接管 `_derive`、多张生成的「往右排」、
  截一段的占位;`RunRequest.source_item_id`;取一帧成为内置产出者 `frame`;边的 `kind: "provenance"`(normalize、
  来历线不供值、前端虚线、「用它做参考」);`/run` 回 `{board, item_id}`;智能体读得到线的 `kind`。
- **迁移**:`migrate-board-tool-output-edges-are-provenance`。
- **棘轮**:落点不相交、来历线不供值。
- **用户看到**:工具产出、截一段、取一帧都落在源格子右边、用虚线标出「从它做出来的」;虚线不会被当成输入;
  智能体能取一帧、截一段。

### Stage 3 · 端口 + 服务端取值(依赖 1、2)

- **范围**:内置端口生效;`BindingRef.role`;`resolve_ports` 取代 `resolve_bindings` 和前端的全部取值;generate 的
  提示词、图例、素材清单在服务端拼;`bind_new_edge` + `addedLinksPatch`;面板变成草稿表单 + 上游标签(便签不再
  预填进提示词框);`set_form` 对内置开放;`run_board_item` 跑任何产出者;`board_sources` → `ports.accepts`。
- **迁移**:`migrate-board-slots-bind-their-upstream`。
- **棘轮**:只有一个取值处、面板只交草稿、两个入口发出同一份请求。
- **用户看到**:连一张便签到图片上,面板显示「提示词 ← 便签」,改便签的字下次生成就跟着变;文档、场景、便签在
  生成、写字、念、工具上的意思一致;智能体能替你出图、写字、配音(花钱的照旧先开卡)。

### Stage 4 · 做法 + 版本(依赖 2、3)

- **范围**:`recipe`、`version_group`;回执把草稿搬进做法;有产出的格子上运行 → `sibling_version`;便签改写成新版本;
  多张生成编成一组;操作条「再来一版」「换模型再来」「改一改再来」,派生产出上「再跑一次」;做法的只读展示
  (提示词、模型、参数、输入标签可点回源格子);版本徽标、同组高亮;撤销补回服务端归属的格子;删在跑的格子先停;
  `board.item_made` / `board.item_failed`;`run_board_item` 的 `form_overrides`;复制带做法。
- **迁移**:`migrate-board-made-cells-remember-their-recipe`。
- **棘轮**:做法与版本的不变式、画布大小的性能棘轮。
- **用户看到**:每张图、每段音频、每张 AI 改过的便签都记得自己怎么来的;一键再来一版、换个模型再来,几版并排比;
  改写便签不再丢原文;复制一张图,提示词跟着走。

### Stage 5 · 每种格子的字段表(依赖 1–4:表要收下它们加的字段)

- **范围**:`domain/boards/fields.py` 的 `ITEM_FIELDS`;normalize、算子、OpenAPI 判别联合从它生成;`ref_title`、
  `preview_asset_id`、`references` 侧表;`set_text` / `set_color` 只对便签;`check_canvas` 校验素材引用;
  `tools._SOURCE_KINDS` 由 `provides` 取代;`list_board_producers` 带完整字段表。
- **迁移**:`migrate-board-reference-names-leave-text`、`migrate-board-scene-preview-leaves-asset-id`、
  `migrate-board-stray-fields-leave-other-kinds`、`migrate-board-media-cells-match-their-asset-kind`。
- **棘轮**:字段表、素材引用、`tsc` 判别联合。
- **用户看到**:文件名不再冒充提示词;场景、素材改了名,画板上跟着变;音频放不进图片格;智能体不会把字写进
  不该有字的格子。

素材引用校验(问题 7)不依赖前四个阶段,若先要,可以单独提前到 Stage 1 之后发;它只是随字段表的 `ref` 声明写才最省。

### Stage 6 · 「添加」目录 + 空态模板(依赖 1、3;可在 Stage 3 之后任何时候发)

- **范围**:工具条「添加」按「生成 / 从素材库 / 引用 / 整理 / 工具」重排,拉线菜单是同一份目录按 `accepts` 和方向
  过滤;文档改成先挑再放;内置和工具格共用空态模板(图标、动词句、次要动作、上游摘要)。
- **迁移**:无。
- **棘轮**:目录只有一份(拉线菜单和「添加」读同一个构造函数,前端测试锁住)。
- **用户看到**:「添加」里的每一组是一件要做的事;空格子告诉你它要什么、已经接了什么。

## 非目标

- **格内版本叠**(见决定 1 的比较)和「选定这一版」标记:挑一版就是从那一格连线出去。「收起其余版本」若要做,
  只是显示层,不改数据。
- **上游一改就自动重跑下游**、在画板上串起一条链一次跑完:那是「然后做它」,归工作流;画板的线是「参考它」,
  重跑永远是人按的(或人让智能体按的)。
- 做法冻住上游文字的原文、版本之间的对比视图、成本估算(ADR 0021 P3 已说明无从估算)。
- 为历史里查不到的格子**编造**做法。
- 「从画板沉淀为工作流」「把工作流结果送到画板」:仍是 ADR 0021 修订里的下一版;本 ADR 的做法和端口是它们的
  地基(一串带做法的格子 + 端口声明,就是一张工作流的草图),但不在这里做。
- 实时多人协同编辑、增量保存、跨画板的来历。
- 改变工作流自己的绑定模型。

## Alternatives rejected

- **A. 保留前端拼请求,另给智能体写一个拼请求的后端版本。** 两个拼装器,「连一张便签到图片上是什么意思」就有
  两个答案,正是问题 2。
- **B. 格内版本叠。** 见决定 1 的表:它牺牲的恰好是画板存在的理由(并排比较),还给每个取值者加了「哪一版」的分支。
- **C. 做法放进一张独立的表(`board_item_recipes`)。** 画布是这张板的唯一事实:复制画板、复制格子、智能体读画板、
  导出全都读画布;另一张表要跟着每一条路搬、在删格子时清孤儿,而单份做法本来就是有上限的小对象。
- **D. 用线的 `label` 区分来历。** `label` 是用户写的字;拿它当语义字段,用户改一个字线的意思就变了。
- **E. 成功后保留草稿(不清空也不搬走)、就地重跑覆盖。** 今天清空就是为了避免「看着像要重跑」;保留下来又回到
  「重跑覆盖上一版」,发散仍不在数据里。
- **F. 在 normalize 里强制「每根参考线都要被端口用上」。** 插件卸了、产出者换了,一张旧板就存不下;规矩只在建线时管。

## Consequences

- 画板上「怎么做、放哪、接什么、字段是什么意思」各只有一处声明:产出者注册表和字段表,前端和智能体读同一份。
  加一个内置产出者或插件工具,连线、菜单、操作条、落点、停止都不用再写前端特例。
- 智能体在 Stage 3 之后能做界面上能做的每一件产出,花钱的照旧先开卡(ADR 0023 的词表)。
- 数据形状变化共七条迁移,都有 slug、测试和升级夹具里的旧形状;没有读取期分支。
- 画布会变大(做法、版本);有上限和性能棘轮看着,增量保存留作以后。
- 风险:Stage 3 把拼提示词从前端搬到服务端,图例、文档材料的格式要逐字对齐今天(用「两个入口同一份请求」
  和现有 `NodeComposer` 的测试对照);Stage 4 的撤销补回规则要和 `_keep_server_owned_state` 同步维护 ——
  两处写的是同一条规矩,棘轮要覆盖撤销那一侧。
