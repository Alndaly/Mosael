# ADR 0072:「一次挑一组素材」只有一个控件 —— 形状由后端声明点名,值编码和角色词表各只有一份

## Status

Accepted — 2026-10-17。判据由 `backend/tests/test_asset_group_fields_use_the_shared_grid.py` 与
`frontend/src/features/nodeForms/assetGridFields.dom.test.tsx` 两道棘轮守着。本文档与 ADR 0045 的
「两层名字」、ADR 0067(引用到的图并进这一格)**互指**:那两份说的是"哪些素材进得来",
这一份说的是"这一格长什么样、由谁决定"。

## Context

同一件事 —— **挑一组素材** —— 此前有**三种长相**,而且哪一种由**字段住在哪个节点**决定:

| 哪里 | 长什么样 |
| --- | --- |
| `llm.image_asset_ids`(要模型看的图片) | 紧凑格子:上传瓦片 + 「+」瓦片 + 一格一份缩略图,挑、拖排序、直接传 |
| `ai_generate.source_assets`(输入素材) | 检查器**自绘**的「按角色一行两条下拉」(那是 275 行专门写在这一个节点里的代码) |
| `entity_save.asset_ids` / `asset_tag.asset_ids` / `asset_update.asset_ids` | 手填引用的**文本框** |

三种长相背后的**同一件事**因此有三套规矩:上传怎么进来、排序怎么拖、"这一格收哪几种素材"在哪判、
值写回去是什么编码。加上 ADR 0067 的"引用即发送"之后,同一处语义还要在自绘那一份里再实现一遍。

**值编码也不是一种**:生成节点那一格是**行的列表**(每行 `素材id:角色`,因为某一行可以是一整串引用
`{{…}}`,插值后是一组),大模型那一格是**逗号分隔的素材 id 串**。两种编码此前分住在两个功能模块里。

## Decision

### 1. 形状由声明点名:`editor: "asset_grid"`

后端的 `NODE_TYPES`(`app/domain/workflows/node_types.py`)在这几个字段上只加一条**纯展示声明**
`editor: "asset_grid"`,前端按它渲染那一个共用控件
(`frontend/src/features/nodeForms/AssetGridField.tsx`):

- `llm.image_asset_ids`(**合流**,行为一字未改 —— 它本来就是那个控件);
- `ai_generate.source_assets`(删掉自绘那 275 行,`NodeInspector.generatePrompt` / `nodeInspectorGenerate.tsx` 相应收口);
- `entity_save.asset_ids`、`asset_tag.asset_ids`、`asset_update.asset_ids`(三个文本框换成格子)。

**判据是"这一格装的是好几份素材",不是字段名**:名字以 `asset_ids` 结尾、声明了 `ref_assets_from`、
或者声明了 `lines`。`entity_ids` / `model_ids` / `clip_ids` 不在内(那挑的是资产、3D 模型、时间线片段);
单个 `asset_id` 也不在(那是"挑一份",套格子没有意义)。这条判据就是那道棘轮,谁再给这种字段自绘一套、
忘了声明,它就红。`type: "code"` 的字段排除在外(插件硬把两种声明叠在一起时,代码优先)。

### 2. 两种值编码**只有一处实现**

`frontend/src/lib/sourceAssetLines.ts`(从 `features/workflows` 搬到 `lib/`):

- 声明了 **`lines: True`** → 值是**行的列表**,每行一条 `素材id:角色`,写回去也是行的列表;
- 其余 → **逗号分隔的素材 id 串**;
- `_roles` 那一份记账走同一份行编码。

**为什么住在 `lib/`**:值编码有两个消费方 —— 工作流那一侧(画布上的输入口、就绪检查)和那一格**控件**
(大模型节点那格也用它)。功能模块之间不许互相引用(`features/featureBoundaries.test.ts` 棘轮),
所以编码住在两边都够得着的 `lib/`,而不是让控件去 import 工作流模块。

### 3. 角色只从**声明**取

`entry_labels: "source_roles"` 指向 `frontend/src/lib/sourceFrames.ts` 那一张**唯一**的词表
(`SOURCE_ROLES` + `ROLE_COPY`)。此前有一份重复的 `SOURCE_ROLE_ORDER` / `LABELS` 散在检查器里 ——
删掉。控件的做法是:`roleLabel` 认不出的角色**照原样写出来**,不静默换成别的词。

**控件不认识任何节点与模型**:"这个模型收哪几种角色 / 每种几份 / 槽位叫什么"由**宿主算好传下来**
(`source_limits` 等),控件只画。

### 4. 素材种类照 `media` 声明过滤

`media: ["image"]` 只图,`["image", "video"]` 图 + 视频,**不声明 = 什么素材都收**
(`asset_tag` / `asset_update` 就是这样:打标签、改元数据本来就不限种类,所以那两个格子比
「要模型看的图片」宽)。上传本地文件与"接上游输出"(整格连接开关 + 一行的「再加一份」)都保住。
`max` 按各角色 `source_limits` 之和算(不会被一个固定的 8 卡住),大模型那格仍是 8。

### 5. 瓦片行:**同一行内尽量满宽**,这条版式也只有一处

瓦片数**不到**设计列数时不写死轨道数,改用隐式列 `grid-flow-col auto-cols-fr`(每枚一等份
`minmax(0,1fr)`)—— 轨道数 = 枚数,整行天然占满;超过设计列数就回到固定列,八张图仍旧一排四张,
不会变成巨块。设计列数:带角色的 **2** 列(角色角标要写下一个角色名,四列放不下),不带角色的 **4** 列。

根因是**轨道数写死**:不带角色那版写死 `grid-cols-4`,两枚瓦片各占 25%、右边空出一截(截图里
「LLM 生成」那格正是这样),而带角色那版轨道数恰好等于枚数,看着是满的 —— 同一件事两个格子两种观感。
用的正是仓库既有的同一句话(`frontend/src/features/workflows/OutputAssets.tsx` 的
`grid-flow-col auto-cols-fr`),没有新增 `controlOverrides`、没有压高度留白圆角字号、没有 calc 魔法数。

## Consequences

- **一处改、五格跟着变**:上传、"从素材库挑"、拖排序、删除、"引用即发送"的自动那一行、
  排除清单(`<那一格>_excluded`)只在 `AssetGridField.tsx` 里有一份。
- **自绘那一份被删掉**(约 275 行),`ai_generate.source_assets` 的行为靠声明对齐,而不是靠两处代码
  各写一遍"记得也支持拖排序"。
- **`editor` 从此是一条正式的声明**:它和 `media` / `entry_labels` / `edited_by` 同族 —— "决定怎么渲染"
  的声明之一(`backend/scripts/export_openapi.py` 的快照把它一起导出,与既有 `edited_by` 同性)。
- **代价:控件变胖**(`AssetGridField.tsx` 950 行上下)。取舍是"一个胖控件"对"三份逐渐漂移的自绘代码":
  前者能靠棘轮钉住一致性,后者不能。
- 前端那道棘轮拿**后端导出的真声明**遍历这些字段,断言画出来的是共用格子、mode 照声明、
  角色角标只在 `source_roles` 那一格长 —— 所以"声明改了、控件没跟"会红。

## 验收

- `backend/tests/test_asset_group_fields_use_the_shared_grid.py`:凡"一次挑一组素材"的字段必须点名
  `editor: "asset_grid"`(先红:4 个字段没点名)。
- `frontend/src/features/nodeForms/assetGridFields.dom.test.tsx`:拿真声明遍历,画出来的是共用格子。
- `frontend/src/features/nodeForms/AssetGridField.dom.test.tsx`:值编码往返稳定(解析再序列化回到原样)、
  角色角标、`media` 过滤,以及「同一行内尽量满宽」那两个决定宽度的类(`08dcd4eed` 新增 5 条;
  几何证据是真浏览器量的:空格两枚 49.4% → 100%,带角色那版与 8 张那两档逐像素不变)。
- `sync-ratchet-docs.py --check` = 0(两道新棘轮进了 `docs/CONVENTIONS.md` 的清单)。
