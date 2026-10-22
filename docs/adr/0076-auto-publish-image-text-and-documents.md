# ADR 0076 · 自动发布:从「只发视频」扩到图文与文档

- 状态:Proposed — 2026-10-22
- 相关:ADR 0021 / 0044(确认卡与效果)、ADR 0032(宿主能力)、ADR 0075(Computer Use)
- 代码位置:`backend/app/domain/publish/`、`electron/publish/`、`frontend/src/features/publish/`

## 要解决什么

发布域现在只有**一种**内容形状:**一份视频素材**。

- 任务表:`PublishTask.asset_id` 指向一份素材,`asset_name` 存显示名(`db/model_slices/publish.py`);
- 执行器:`PublishAdapter.uploadVideo(videoPath)` 是接口里唯一的上传动作(`electron/publish/adapters/shared.ts`);
- 入口:发布页只搜 `kind: ["video"]`(`PublishView.tsx` 的 `useAssetSearch`)、工作流 `publish` 节点只有一个 `asset_id`(`domain/workflows/node_types.py`)、智能体 `publish_asset` 同样只有一个 `asset_id`(`mcp_server.py`);
- 平台注册表:`PUBLISH_PLATFORMS` 每条只有标题上限和发布选项,没有「这个平台能发什么形状」。

但账号池里已经支持的这些平台,实际能发的内容远不止视频:

| 平台 | 现在能发 | 页面上的事实 |
|---|---|---|
| 小红书 | 视频 | 创作页**默认就是图文**,适配器要主动点「上传视频」才切过去(`XiaohongshuAdapter.openCreatorPage` 里写着) |
| 抖音 | 视频 | 投稿页有视频 / 图文两种作品 |
| 微信视频号 | 视频 | 发表页有视频 / 图文两种 |
| Bilibili | 视频 | 投稿中心还有专栏、动态 |
| X | 文字(+ 图,尚未接) | 一条帖子最多 4 张图 |
| TikTok | 视频 | 有 photo mode(图文轮播) |
| YouTube | 视频 | Studio 之外还有社区帖子 |

也就是说,**账号类型(platform)和作品类型(content kind)是两件事**,现在被压成了一件事:只要账号是「抖音」,发布就只能是视频。这不是平台的事实,是我们数据模型的限制。

## 决定

### 1. 内容形状进模型:三种 kind

- `video`:一份视频素材(现在的样子,不变);
- `image-text`(图文):1–N 张图片 + 标题 + 正文/文案;
- `document`(文档):以一份 **document 素材**(PDF / Word / PPT / 长文导出)为主体发布。

**平台声明自己认哪几种**:`PUBLISH_PLATFORMS[platform]["kinds"] = ("video", "image-text", …)`,以及各自的 `max_images` / `body_max` / `document` 限制。三处消费同一份声明:后端校验(不认的 kind 直接 422)、前端只列可选项(选账号后表单跟着收窄)、执行器按 kind 挑适配器方法。禁止任何一处自己再列一遍平台清单。

### 2. 任务形状:仍是「一条任务 = 一个发布单元」

`PublishTask` 增加:

- `content_kind`(默认 `"video"`,老数据不用迁移);
- `asset_ids`(JSON 数组):图文就是多张图,视频仍是一张;`asset_id` 保留并继续写**第一份**,老读者(列表、作品查询)不用改;**读的一侧优先 `asset_ids`,为空回退 `[asset_id]`**;
- `body`(Text):正文 / 长文,平台没有正文栏就是空串 —— 现在正文塞在 `platformOptions.description` 里,是「发布选项」混进了「内容」,顺手归位;
- `media_meta`(JSON):图片顺序、每张的 alt/说明(平台支持时用)。

`start_publish` 仍是**所有入口的唯一实现**(发布页、工作流节点、智能体确认卡),参数从 `asset: Asset` 变成 `content: PublishContent`(`kind` + `assets` + `title` + `body` + `tags` + `options`),归属闸(`sharing.ensure_usable`)、标题上限、禁用账号这些校验一处都不搬。

### 3. 适配器接口按内容形状走,不再写死视频

`PublishAdapter` 把 `uploadVideo(videoPath)` 换成:

- `uploadImages(paths: string[])`:按平台的图片入口(文件 input 的 `accept`、图文 tab、多选);
- `uploadDocument(path: string)`:只有声明了 `document` 的平台实现;
- `fillBody(body: string)`:正文 / 长文(富文本编辑器各有各的打字方式,复用现有的 `typeOrFill` + 降级);
- `uploadVideo` 保留为 `video` 的入口(内部可拆成 `uploadMedia`),但**适配器不自己判断 kind** —— 由 worker 按任务声明挑调用哪个。

装配仍只有 `createAdapter(platform, driver, task)` 一处;每个平台的适配器声明 `supports: readonly ContentKind[]`,由测试和后端注册表交叉核对,**对不上的那一边红**。

### 4. 账号池:能力跟着账号类型显示

账号池(`domain/browser` 的档案 + `PublishAccount`)本身不改:一个账号还是「一个平台 + 一份登录态」。但界面上:

- 账号旁显示它能发哪几种内容(小标签,不新增结构层);
- 发布表单:先选账号/平台 → 只列这个平台认的 kind(单选:视频 / 图文 / 文档)→ 素材选择器按 kind 换(`video` 单选视频、`image-text` 多选图片并可排序、`document` 选文档);
- 标题上限、正文长度、图片张数从平台声明里取,**不在前端再抄一份**。

### 5. 入口统一

- 发布页:表单加「内容类型」;
- 工作流 `publish` 节点:`asset_ids`(模板:可写一个 id、多个 id 用逗号/JSON、或上游产出的列表)+ `content_kind` + `body`;`asset_id` 继续认(视频老图不坏);
- 智能体 `publish_asset` 工具:`asset_ids: list[str]`、`content_kind`、`body`;`asset_id` 单数保留为简写。确认卡摘要写明「发什么形状、几份素材、发到哪个账号」(ADR 0044 的措辞规矩:卡上必须说清要发生什么);
- 工作流 / 智能体 / 发布页三处都落到同一个 `start_publish`,新增字段的校验也只有一处。

### 6. 安全与失败

- 图文与文档仍然是 **external** 档:默认问人,「本会话始终允许 / 自动放行 / bypass」照旧走确认卡体系(ADR 0044);
- 文档素材只在本地读取、交给平台的文件 input;**不解析文档里的链接、宏、脚本**;
- 文档转图片(若某个平台没有文章形态)只转**页面图像**,不执行任何内容;
- 失败原因沿用 `publishErr_*`(按语言翻),新增的只能加 key,不在适配器里拼句子;
- 截图/证据:`docs/validation/` 记录每一次真发(平台侧条目类型正确)。

## 推进顺序(每一步都能独立发布)

1. **小红书图文**:创作页默认就是图文,适配器只需不点「上传视频」+ 多图上传 + 正文;先在开发机上真发一条「仅自己可见」;
2. **抖音图文**:投稿页切换 + 多图 + 标题;
3. **微信视频号图文**:发表页的图文入口;
4. **X / TikTok 图片**:多图上限(4 / 平台声明)、alt 文本按平台能力;
5. **Bilibili 专栏 / 动态 + 文档类**:先定「文档在平台上是什么形态」(见待确认);
6. **YouTube 社区帖**:要先确认 Studio 里有没有稳定的创建入口,没有就不做。

每步完成的标准:后端注册表声明、前端表单、适配器实现、模拟页面单测四处一致,并在真实账号上真发一条(私有可见)核对。

## 不做的

- 定时发布(平台自己就有,且它跟着平台时区走);
- 一次任务多发多个账号(那是工作流串几个节点的活);
- 草稿箱 / 多版本;
- 长文排版器(用平台自己的编辑器,我们只负责填进去);
- 图片处理(裁切、加水印)不属于发布域,先由生成 / 编辑节点做好。

## 待确认(维护者拍板 / 实测)

1. **「文档」到底是什么形态**:是平台的长文/专栏(B站专栏、公众号文章),还是把文档渲染成图片轮播(1 页 1 图)发到小红书/抖音?默认建议:**有文章形态的走文章,没有的转图片轮播**,并在任务上记 `converted_from=document`;
2. 视频号图文入口是否与 `platform/post/create` 同页(需要真机一次);
3. TikTok photo mode 是否还能从创作者页稳定进入;
4. YouTube 社区帖子是否有稳定入口(没有就从顺序里删掉,别硬做);
5. X 的一条帖子最多 4 张图、正文 280 字:图文任务是否按「一条帖子」约束,还是允许拆成多条(默认:一条任务一条帖子,拆多条交给工作流)。

## 后果

- 发布域从「视频管线」变成「内容管线」,但**形状只有三种**,且平台能力只有一份声明 —— 加一个平台内容类型是改注册表一行 + 适配器一个方法,不是三处各加一段;
- 老数据、老调用方不必迁移:`content_kind` 默认 `video`、`asset_id` 继续写,读的一侧有回退;
- 风险集中在 RPA 适配器(平台页面是活的):每个 kind 的上线都以「真机真发一条」为验收,不靠选择器猜测;
- 与 ADR 0075 的关系:Computer Use 让「页面改版时人工兜底」变得可行(截图看、点一下),但本 ADR **不依赖**它 —— 发布执行器仍是独立的浏览器自动化。
