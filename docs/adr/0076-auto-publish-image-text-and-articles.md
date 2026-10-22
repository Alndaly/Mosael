# ADR 0076 · 自动发布:从「只发视频」扩到图文与文章

- 状态:Proposed — 2026-10-22(同日按维护者要求逐个平台核实了真实能力,见「事实核对」)
- 相关:ADR 0021 / 0044(确认卡与效果)、ADR 0032(宿主能力)、ADR 0075(Computer Use)
- 代码位置:`backend/app/domain/publish/`、`electron/publish/`、`frontend/src/features/publish/`

## 要解决什么

发布域现在只有**一种**内容形状:**一份视频素材**。

- 任务表:`PublishTask.asset_id` 指向一份素材,`asset_name` 存显示名(`db/model_slices/publish.py`);
- 执行器:`PublishAdapter.uploadVideo(videoPath)` 是接口里唯一的上传动作(`electron/publish/adapters/shared.ts`);
- 入口:发布页只搜 `kind: ["video"]`(`PublishView.tsx` 的 `useAssetSearch`)、工作流 `publish` 节点只有一个 `asset_id`(`domain/workflows/node_types.py`)、智能体 `publish_asset` 同样只有一个 `asset_id`(`mcp_server.py`);
- 平台注册表:`PUBLISH_PLATFORMS` 每条只有标题上限和发布选项,没有「这个平台能发什么形状」。

但账号池里已经支持的这些平台,实际能发的内容远不止视频 —— 下面是**逐平台核对过的事实**
(2026-10-22,来源见文末;标「待真机」的还需要在真账号的创作页上确认一次):

来源可信度:① 官方(平台自己的帮助页 / 官方新闻)② 二手整理,仍需在真账号创作页上核对一次。

| 平台 | 视频 | 图文(短) | 文章 / 长图文 | 文档(PDF/Word/PPT) |
|---|---|---|---|---|
| 抖音 | ✓① | ✓① **图文**:≤35 图、单图 ≤50MB、jpg/jpeg/png/webp(不支持 gif) | ✓① **文章**:标题 ≤30 字、摘要 ≤30 字、正文 ≤20000 字、话题 ≤5、封面必填、可定时;入口 `creator-micro/content/post/article` | ✗ 没有文档上传 |
| 小红书 | ✓① | ✓① **笔记**:≤18 图、单图 ≤32MB、正文 ≤1000 字、jpg/jpeg/png/webp(不支持 gif/live) | ✓① **写长文**:标题 ≤64 字、正文按字数计数(界面未标上限)、有「一键排版」;入口 `publish/publish?target=article` | ✗ |
| 微信视频号 | ✓ | ✓① 助手端可上传 **≤18 张图片发表图文**(手机端 ≤20;描述 ≤1000 字);**超过 18 张会变成视频** | — | ✗ |
| Bilibili | ✓ | ✓① 动态(发布框在 t.bilibili.com;图数待核) | ✓① 专栏入口已真机确认(「专栏投稿」→ `upload/text/new-article`);字数/图片上限是二手整理(200–20000 字、标题 ≤40、单图 ≤3MB、每日 ≤5 篇、**发布后不能编辑**),仍要人眼核 | ✗ |
| TikTok | ✓ | ✓① 照片轮播:≤35 图、单图 ≤50MB(Studio 页原文;标题 90 / 描述 4000 待界面核) | ✗(无长文) | ✗ |
| YouTube | ✓(含 Shorts) | ✓① 社区帖子:文字 + ≤10 图(GIF 也算;频道要先「启用我的社区」) | ✗ | ✗ |
| X | ✓ | ✓② 帖子:≤280 字(Premium 长帖 ≤25000 字符)、图片 1–4 张 | ✓ Articles / 长文(**待真机**:入口与图片规则) | ✗ |

### 真机核对(2026-10-22,用 Mosael 自己的浏览器池逐个账号打开创作页)

用发布账号的浏览器档案登进各平台创作页,读到的是页面自己写的话:

- **TikTok(已登录)**:Studio 上传页有「**Videos | Photos**」两个 tab;Photos 页原文
  「Upload up to 35 photos per post」「Up to 35 photos, max 50 MB per photo」,格式
  JPG/JPEG/PNG/WebP,推荐比例 16:9 / 4:3 / 3:4。视频页原文「Maximum size: 30 GB, video
  duration: 60 minutes」。**照片轮播入口就在 Studio,不需要另找**。
- **YouTube(已登录)**:Studio 的「创建」菜单是「上传视频 / 开始直播 / **发帖** / 新建播放列表 /
  新建播客」;发帖页支持「图片 / 图片投票 / 文字投票 / 知识问答 / 视频」,拖图区原文
  「**最多拖动 10 张图片或 GIF**」,且频道要先点「**启用我的社区**」——这个频道当前是关的。
  Studio 左侧也有「社区」入口。
- **Bilibili(已登录)**:视频上传页顶部导航是「视频投稿 / 短剧投稿 / **专栏投稿** / UP动画 /
  互动视频投稿」;视频大小「16G 以内、时长 10 小时以内」(粉丝 ≥1000 解锁 64G)。点「专栏投稿」
  实际跳到 `member.bilibili.com/platform/upload/text/new-article`,但编辑器在自动化浏览器里
  没渲染出正文(SPA 没起)——**专栏的字数/图片上限仍需人眼在真页面上确认**。动态发布在
  `t.bilibili.com` 首页的发布框(有「选择话题 / 发布」),图片张数待核。
- **X(已登录)**:发帖页文件选择器的 `accept` 是
  `image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime`,`multiple` 为真;
  **`x.com/compose/article` 是 404**(「This page doesn't exist」)——Articles 的入口不在这个猜出来的
  地址上,要从 Premium 菜单/发帖器里找到真实入口再说。图片 ≤4 张仍是文档口径,未在界面上验到。
- **抖音(已登录,2026-10-22 21:0x 真机)**:创作中心「作品发布」下四个 tab ——
  **发布视频 / 发布图文 / 发布全景视频 / 发布文章**。
  - 图文:页面原文「最多支持上传 **35 张**图片」,单图 ≤**50MB**,格式 jpg/jpeg/png/webp
    (**不支持 gif**),建议比例 3:4 / 4:3;文件 input 为 `multiple` 且 `accept` 含
    png/jpeg/jpg/bmp/webp/tif。
  - 文章(长图文):点「我要发文」进入编辑器
    `creator.douyin.com/creator-micro/content/post/article?from=publish_page&media_type=article&type=new`,
    计数器实测为 **标题 0/30、摘要 0/30、正文 0/20000、话题 0/5**;封面(文章头图)**必填**;
    可见性三档(公开 / 好友可见 / 仅自己可见)、可定时发布;编辑器里还有「AI 配图 / AI 生成」。
    —— 行业报道说的「≤8000 字 + ≤30 图」是早期口径,**以这里的编辑器计数为准**。
- **小红书(已登录,同日真机)**:左侧四个入口 —— **上传视频 / 上传图文 / 写长文 / 发播客**。
  - 图文:上传后右上角计数 **1/18**(图片上限 **18 张**),单图 ≤**32MB**,格式 jpg/jpeg/png/webp
    (**不支持 gif、live**),正文 **0/1000**;标题输入框的 placeholder 是「填写标题会有更多赞哦」,
    界面**不显示**标题字数上限(按 20 字对待,发一条真笔记时再核)。
  - 写长文:进入后标题 `textarea` 的 `maxlength=64`(计数 0/64),正文是 contenteditable,
    只有「字数:N」计数、**界面不标上限**,并提供「一键排版」;地址
    `publish/publish?from=tab_switch&target=article`。
- **视频号**:档案仍未登录(`logged_in=false`),需要维护者登录一次才能核「图文入口」与
  「超过 18 张会形成视频」这句话在助手端是否同样成立。

**结论一:没有哪个平台接受"上传一份文档"。** 文档类目只能**转换**成平台认的形态:有文章形态的
(抖音长图文、小红书长文、B站专栏、X 长文/Articles)转成文字 + 配图;没有文章形态的(视频号、
TikTok、YouTube 社区帖)只能转成图片轮播(一页一图)。这是上一版 ADR 把 `document` 当成一种
"平台作品类型"的错误,现在纠正。

**结论二:同一平台的三种形态往往是不同的创作页。** 抖音视频/图文在 `content/upload`,长图文在
「高清发布 → 发布文章」;B站视频在 `upload/video/frame`,专栏在专栏编辑器;YouTube 视频在 Studio,
社区帖子在频道的「创建 → 帖子」。适配器不能假设"同一个入口换一个 tab"。

也就是说,**账号类型(platform)和作品类型(content kind)是两件事**,现在被压成了一件事:只要账号是「抖音」,发布就只能是视频。这不是平台的事实,是我们数据模型的限制。

## 决定

### 1. 内容形状进模型:三种 kind

- `video`:一份视频素材(现在的样子,不变);
- `image-text`(图文):1–N 张图片 + 标题 + 正文/文案;
- `article`(文章 / 长图文):标题 + 长正文 + 配图,发到有文章形态的平台(抖音长图文、小红书长文、
  B站专栏、X 长文)。**平台没有文章形态时不做**,不拿图文去凑。

`document` **不是作品类型,是输入类型**:一份 document 素材在**创建任务之前**就要被转换 ——
正文抽出来当 `article` 的正文、页面渲染成图片当 `image-text` 的图,并在任务上记
`converted_from=document`,让用户看得出"发出去的是转换后的样子"。转换发生在发布域之外
(素材/文档域),发布域只认上面三种真实下发得出去的类型。

**平台声明自己认哪几种**:`PUBLISH_PLATFORMS[platform]["kinds"] = ("video", "image-text", "article")`,以及各自的 `max_images` / `title_max` / `body_max`(抖音图文 30 图、小红书 18 图 / 1000 字、视频号 18 图 / 1000 字、B站专栏 200–20000 字 / 标题 40、TikTok 35 图 / 90 + 4000、YouTube 10 图、X 4 图 / 280)。三处消费同一份声明:后端校验(不认的 kind 直接 422)、前端只列可选项(选账号后表单跟着收窄)、执行器按 kind 挑适配器方法。禁止任何一处自己再列一遍平台清单。

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

1. **小红书图文**:创作页默认就是图文,适配器只需不点「上传视频」+ ≤18 图 + 正文(≤1000 字);
   先真发一条「仅自己可见」;
2. **抖音图文**:投稿页切换 + 多图 + 标题(图数待真机);
3. **微信视频号图文**:助手端的 ≤18 图(多了会变视频 —— 适配器要挡住并提示);
4. **X 图片 / TikTok 照片轮播**:X ≤4 图、TikTok ≤35 图(标题 90 / 描述 4000),alt 文本按平台能力;
5. **文章类**:抖音长图文(8000 字 / 30 图,PC「高清发布-发布文章」)→ B站专栏(200–20000 字、
   不可编辑 —— 发布前必须让人看全文)→ 小红书长文(待真机)→ X 长文(待真机);
6. **YouTube 社区帖**(≤10 图):先确认频道的「创建 → 帖子」有稳定入口,没有就不做。

每步完成的标准:后端注册表声明、前端表单、适配器实现、模拟页面单测四处一致,并在真实账号上真发一条(私有可见)核对。

## 不做的

- 定时发布(平台自己就有,且它跟着平台时区走);
- 一次任务多发多个账号(那是工作流串几个节点的活);
- 草稿箱 / 多版本;
- 长文排版器(用平台自己的编辑器,我们只负责填进去);
- 图片处理(裁切、加水印)不属于发布域,先由生成 / 编辑节点做好。

## 待确认 / 待真机核对

1. **小红书长文的正文上限**:编辑器只显示「字数:N」不标上限 —— 发一篇真长文时看它从多少开始拦;
   另外标题 20 字的上限在图文编辑器里也没显示,同样待真笔记核对;
2. **抖音文章的正文配图张数**:编辑器能插图(AI 配图 / 头图),但它对**正文内插图**的张数没在页面上
   写死,发一篇时再核;
3. **视频号图文入口**:是否在 `platform/post/create` 同页、以及「超过 18 张会形成视频」这个坑
   在助手端是否同样成立(该档案当前未登录);
4. **B站动态的图片张数**(专栏的 200–20000 字 / 标题 40 / 每日 5 篇 / 不可编辑已核对);
5. **TikTok 照片轮播的创作者页入口**:API 口径是 ≤35 图(标题 90 / 描述 4000),Studio 里是否
   同样稳定可自动化;
6. **YouTube 社区帖子的入口**:在频道的「创建 → 帖子」,不在 Studio;需要频道资格。没有稳定入口
   就从顺序里删掉,别硬做;
7. **X 长文/Articles 的入口**:Premium 账号才有的形态;普通帖子按一条 ≤4 图 / 280 字约束,
   拆多条交给工作流。
8. **文档转换的归口**:由于没有平台接受文档文件,转换(抽正文 / 渲染页面)放在素材域,发布域只收
   三种真实形态。要不要在发布页给「从文档新建图文」这个入口,是 UI 的事,不影响域模型。

## 后果

- 发布域从「视频管线」变成「内容管线」,但**形状只有三种**,且平台能力只有一份声明 —— 加一个平台内容类型是改注册表一行 + 适配器一个方法,不是三处各加一段;
- 老数据、老调用方不必迁移:`content_kind` 默认 `video`、`asset_id` 继续写,读的一侧有回退;
- 风险集中在 RPA 适配器(平台页面是活的):每个 kind 的上线都以「真机真发一条」为验收,不靠选择器猜测;
- 与 ADR 0075 的关系:Computer Use 让「页面改版时人工兜底」变得可行(截图看、点一下),但本 ADR **不依赖**它 —— 发布执行器仍是独立的浏览器自动化。

## 事实核对的来源(2026-10-22)

- 抖音长图文(8000 字 / 30 图 / 背景音乐,PC「高清发布-发布文章」):
  [科技日报](https://www.stdaily.com/web/gdxw/2025-12/26/content_453850.html)、
  [TechWeb](https://www.techweb.com.cn/twclient/article/2025-12-27/2969876.shtml)
- 微信视频号素材要求(助手端 ≤18 图、手机端 ≤20、超过 18 张形成视频、描述 ≤1000 字):
  [视频号官方帮助页](https://findeross.weixin.qq.com/cgi-bin/mmfindernodelivecrmwebbroker-bin/helper-center/pages/DCbKPGzZkvVHcIr6)
- 小红书笔记字数 1000、图片 ≤18(2025 年的现状,长文另说):[少数派](https://go-post.sspai.com/post/95712)
- B站专栏(200–20000 字、标题 ≤40、单图 ≤3MB、每日 5 篇、发布后不可编辑):[OmniGoAI 整理](https://juejin.cn/post/7663435750385532979)
- TikTok 照片轮播(≤35 图、标题 ≤90 字、描述 ≤4000 字):[Sked Social 2026 规格](https://skedsocial.com/blog/schedule-tiktok-photo-carousels)
- YouTube 社区帖子(≤10 图):[YouTube Help](https://support.google.com/youtube/answer/7124474?hl=en)
- X(每帖 ≤4 图、≤1 视频、Premium 长帖 ≤25000 字符):[SocialEcho 规则核对](https://www.socialecho.net/tc/free-tools/platform-content-rules-checker/x/thread)
