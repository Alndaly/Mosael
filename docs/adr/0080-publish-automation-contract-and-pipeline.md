# ADR 0080 · 自动发布:平台契约 + 判定原语 + 浮层策略,旧数据靠迁移

- 状态:Accepted — 2026-10-24,已实现
- 相关:ADR 0076(发布的内容形状)、ADR 0078(失败取证与人工兜底)、ADR 0006(旧数据用迁移)
- 代码位置:`electron/browser/publish/platformContract.ts`、`electron/browser/publish/platformContracts.ts`、
  `electron/browser/publish/overlays.ts`、`electron/browser/publish/verify.ts`、`electron/browser/publish/fakePage.ts`、
  `electron/browser/publish/publishWorker.ts`、`backend/app/db/migrations.py`

## 背景:一天里六次失败,根子只有四个

2026-10-23 一整天都在发布真机上排查,失败的样子各不相同(找不到 tab、正文没进去、
可见范围设不上、发成功了却判失败、正文被重排、图片缺一张还发出去),但根子只有四类:

1. **平台弹了个东西我们没关**,它把下一步挡住 —— 页面不报错,失败以"某个无关步骤超时"出现;
2. **每一步"做成了没有"各写一套**(小红书 8 处 `waitForFunction`、B站 7 处、抖音 5 处),
   同一件事有 N 种口径:整段比 vs 逐行比、含不含旧草稿、认不认平台的字数计数;
3. **成功判定各写一套**,于是把"发成功"判成"被弹回"(小红书地址里其实写着 `published=true`)、
   或者把"页面上一句早就有的词"判成成功(B站 / TikTok / X 都踩过);
4. **平台事实散在三处**(适配器顶上的入口表、`selectors.ts` 的文案、适配器自己的 `waitResult`),
   加一种形状要同时改三处,漏一处就是上面那些失败。

另一个反复出现的错误是**用运行时分支兼容老数据**(`asset_ids or [asset_id]`、
`content_kind or "video"`、给老执行器保留 `video_path`):它们让"旧形状"永远活着,
读代码的人得同时想两种数据,而真正的旧数据其实可以在启动时一次性搬好。

## 决定

### 1. 平台页面契约(事实只有一处)

`PlatformContract` 只写**事实**,不写流程:

- `entry[kind]`:直连地址 / 要点的 tab / 该选中的 tab / 接受的扩展名 / 拖放提示;
- `fileInput[kind]`:按形状挑文件框(按 `accept` 区分,**不猜**);
- `submitText`:提交那颗按钮;
- `done`:**成功信号**(地址优先、文案兜底)+ `formGone`(编辑表单必须已消失)+ `failTexts`(明确失败原文);
- `overlays`:会挡路的浮层(见第 3 条)。

平台页面上的中文留在 `selectors.ts`(那是**匹配真实站点**的词表,豁免翻译),契约引用它 ——
所以 `platformContracts.ts` 里一个中文字面量都没有(CI 的 `uiTextIsTranslated` 棘轮盯着这条)。

**适配器只留平台特有动作**:小红书正文的逗号成段、抖音的 zone 编辑器、B站的封面、YouTube 的
"列表里出现本次上传的视频 ID"。其余(入口、文件框、提交、成功判定)一律从契约来。

### 2. 判定原语(口径只有一份)

`verify.ts` 收三条口径:

- `textEntered` / `linesEntered`:空白不敏感、取**最长**的编辑器文字、**不许混旧字**、
  **按行按顺序**(重排 = 没进去),平台字数计数可兜底(富文本改标点 / 列表时长度对得上就够);
- `successVisible` / `awaitResult`:**先过 `formGone` 闸**,再看地址(在 Node 里比,`urlMatches`),
  最后才看文案(能穿透 shadow DOM);`awaitResult` 返回**成功 / 失败 / 超时**三种并带原因。

地址判断放在 Node 而不是塞进页面脚本:两边各自可测,也避免"把正则写进注入的字符串"那种拼装。

### 3. 浮层策略(声明式,执行器每步之前统一跑)

`overlays.ts` 的规则写清「怎么认出它」(`detect`)、「怎么关掉它」(`dismiss`:先勾框 → 再点按钮 →
或 Esc)、「关掉之后该消失什么」(`gone`)。`clearOverlays()` **幂等**(没有浮层时一次驱动调用都不做)、
**有界**(最多三轮)、关掉一个就重开一轮(平台会套着弹)。

`publishWorker` 在**每一步之前**跑一遍 —— 适配器不再需要记住"这里可能有个提示框"。
这也是"平台弹层不报错、只是挡住下一步"这一类故障的通用解。

### 4. 旧数据靠迁移,不靠运行时兼容

- `publish_tasks`:空 `asset_ids` 回填成 `[asset_id]`,空 `content_kind` 回填成 `video`,
  迁移末尾**断言**"不该再有 asset_id 非空而 asset_ids 为空的行",有就启动时抛;
- 工作流图:已存的 publish 节点补 `config.content_kind`(节点声明的 default 只管新建);
- 回填之后删掉**所有**运行时回退:`start_publish` 只收 `assets: list[Asset]`,
  `PublishCreate` 只收 `asset_ids` 且 `content_kind` 必填,执行器协议去掉 `video_path`,
  `adapter.supports` 改成必填声明。
- 每条新迁移必须带一条"喂它旧形状数据"的测试(`test_new_migrations_come_with_a_test` 棘轮)。

### 5. 装配是注册表,不是 if 链

`createAdapter` 用 `ADAPTERS` 表;`ADAPTER_SUPPORTS`(静态 `KINDS`)是"适配器支持哪些形状"的
唯一读取处,契约完整性与执行器都读它。

### 6. 契约要有可执行的测试

`fakePage.ts` 提供一个**假页面**(地址 / 文字 / 选择器在不在 / 编辑器内容 / 点过谁 / 交了哪些文件),
`platformContracts.pipeline.test.ts` 用它把「平台 × 形状」**自动展开**地跑一遍:进得去、交得了、
成功认得出(**含 `formGone` 闸门**)、浮层清得掉、正文按行按顺序。新平台 / 新形状会自动多出一组
用例 —— 要么过、要么红,漏不掉。

## 不做的

- **不再给平台加"两种选择器 / 两种成功文案"式的兜底**:那正是把今天的误判藏起来的东西;
- **不把平台特有动作塞进通用流程**(封面、alt 文本、视频 ID 核对留在适配器);
- **不为旧数据写运行时分支**:旧形状只允许出现在迁移里;
- 不用"页面脚本里塞一整段逻辑"的方式做判定:判定要能分别测(Node 侧地址、页面侧文案)。

## 后果

- 加一个平台 = 一份契约 + 一个适配器(只写特有动作)+ 它自己的 `KINDS`;加一种形状 = 契约里多一条
  `entry` / `fileInput` + 适配器实现对应动作,管道测试自动盯住;
- 平台改版导致契约失配时,**CI 先红**;真机上失败也会说出具体是哪一步、缺什么;
- 代价:契约与 `selectors.ts` 之间有一层引用,读的时候要跳一次;判定口径被收敛成三条,
  平台差异如果确实存在(YouTube 的视频 ID),就得在适配器里写清理由,而不是悄悄改口径。

## 实现记录(2026-10-23 → 24)

| 步骤 | 内容 | 提交 |
| --- | --- | --- |
| P1 | 迁移回填 + 删掉运行时兼容分支 | `aacb1ae72` |
| P2 | 浮层策略 + 判定原语,适配器删各自实现 | `05f2b917f` |
| P3 | 平台契约 + 适配器注册表 | `950627522` |
| P4 | 假页面 + 管道测试(平台 × 形状自动展开) | `7a5c2efef` |
| 收尾 | 其余五个平台搬进契约;`formGone` / `failTexts` | `215b3fa92` |

### 之后的增补(2026-10-24)

- **浮层规则学会"按选择器点"**:小红书那个「图片可以编辑啦」的外层容器文字也是「我知道了」,
  按文案点会先命中它、点容器什么都没发生。规则加了 `dismiss.clickSelector`(优先选择器、文案兜底),
  并给规则加了 `id`(适配器要确认"某一条关掉了没有"时按 id 找,不重复页面文案)。
- **平台补齐**:X 图文、TikTok 照片轮播、视频号图文、B站专栏(article)都接上了 ——
  它们各自只新增契约条目 + 适配器里的特有动作,**没有再动通用流程**(见 ADR 0076)。
  视频号与 B站专栏的编辑器都在同源 iframe 里,适配器用 `PageDriver.inFrame`。
- **判定多了一种闸**:`formGone`(编辑表单必须已经消失)—— B站 / TikTok / X 发完不换地址或换到列表,
  只认文案会被页面上早就存在的词命中。
