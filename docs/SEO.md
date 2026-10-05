# 官网与 README 的搜索优化(SEO)

这份文档有两个用处：一是写清代码这一侧已经做好、维护时不能破坏的部分，二是列出只有维护者本人能做的事，比如站长平台、验证码和外链。关键词调研完成于 2026-10，来源见文末。

## 原则

- **只写查得到的事。** 每一句宣传都要在代码、文档或 CHANGELOG 里找得到依据。不写用户数、评分、评价、下载量。还没发版的功能要标注「下一版」，例如 ComfyUI 应用表单。
- **不说「开源」。** 仓库的 [LICENSE](../LICENSE) 是专有许可：源码公开，个人非商业使用免费，商用和再分发需要书面授权。
  - 能用的说法：「源码公开 / 源码可见(source-available)」「个人非商业使用免费(free for personal, non-commercial use)」「自带 API Key(BYOK)」。
  - 「开源剪映替代」「open source CapCut / Descript alternative」这类词虽然有搜索量，用了就是虚假宣传。HN、V2EX 对冒充开源的项目反感很明显。
  - 常见问题里可以回答「Mosael 是开源软件吗」，答案是否定的。`website/test/seo.test.mjs` 会检查对外文案里不出现开源的说法。
- **头部词抢不到，主攻长尾。** 「AI 视频生成」「AI 数字人」「CapCut alternative」的结果页被即梦、可灵、剪映、HeyGen 和大量测评长文占满。小项目现实可做的是这几类：
  - 「工具名 + 客户端 / 桌面版」
  - 「自带 API Key」
  - 「本地 + 具体能力」(照片说话 本地、F5-TTS 图形界面)
  - 「X 的本地替代」

## 代码这一侧(已做好，测试钉着)

| 项 | 位置 | 测试 |
| --- | --- | --- |
| 每页的 title、description、keywords、canonical、hreflang(`en` / `zh-CN` / `x-default`)、Open Graph、Twitter 卡片 | `website/src/lib/seo.ts` 的 `pageMetadata`，每个 `page.tsx` 都调用 | `test/seo.test.mjs`：每个页面路由都调用它；根布局不写会被继承的 canonical 和 Open Graph |
| 文档页搜索标题与关键词 | frontmatter 的 `seo_title`、`keywords`；`title` 仍是 h1 和侧边栏标签 | 每种语言里 `<title>` 不重复，宽度不超出搜索结果的显示范围 |
| sitemap | `website/src/app/sitemap.ts`：首页、社区两页、更新日志、全部文档，以及**插件和工作流详情页**，两种语言都有 hreflang | 列全且不含跳转地址 |
| robots | `website/src/app/robots.ts`：全站放行，只挡 `/<语言>/search.json` | ✓ |
| 结构化数据 | `website/src/lib/structured-data.ts`。首页：Organization、WebSite、SoftwareApplication(价格 0、macOS / Windows、下载地址、许可指向 LICENSE)、FAQPage。文档页：TechArticle 和面包屑。插件、工作流详情：面包屑 | 合法 JSON；没有评分、评价、下载量 |
| 分享卡片 | `website/public/og/mosael-{zh,en}.png`，1200×630，由 `scripts/compose-readme-showcase.py --only og` 从首页实拍截图生成 | 文件存在且尺寸正确 |
| 百度 | `<meta name="applicable-device" content="pc,mobile">`、`Cache-Control: no-transform / no-siteapp`(防止百度转码)、`<meta name="keywords">` | 根布局里有这几项 |
| 不跑 JS 的爬虫 | 所有页面静态预渲染(SSG)，正文、导航、hreflang、JSON-LD 都在服务端 HTML 里；`Reveal` 淡入在 `scripting: none` 时直接显示终态 | — |
| 站长验证码 | 从部署环境读取：`SITE_VERIFICATION_GOOGLE / _BAIDU / _BING / _360 / _SOGOU`，见 `website/.env.example`。**仓库里不写真值** | 没配置的那家不输出 meta；源码里不能出现具体验证码 |

`<meta name="keywords">` 只是给百度的一点补充。百度官方《搜索引擎优化指南》只讲 title 和 description，不提 keywords，所以它没有排名价值，不要往里堆词。

## 关键词地图

每页一个主词、几个次词。改文案时先查这张表，别让两页抢同一个词。

| 页面 | 中文主词 / 次词 | 英文主词 / 次词 |
| --- | --- | --- |
| 首页 `/zh` `/en` | **本地优先的 AI 视频创作软件(Mac / Windows)**；AI 视频生成、AI 剪辑、AI 配音、声音克隆、数字人口播、视频翻译配音、ComfyUI 客户端、自带 API Key、Seedance、可灵 | **local-first AI video studio for Mac & Windows**；AI video generator desktop, AI video editor, bring your own API key, ComfyUI client, Seedance / Kling / Veo, voice cloning, lip sync |
| 下载 `docs/start/download` | **Mosael 下载**；AI 视频软件 Mac 版 / Windows 版、Apple 芯片、百度网盘 | **download Mosael for Mac / Windows**；AI video app for Mac Apple silicon |
| 模型连接 `guides/providers` | **自带 API Key 接入 Seedance、可灵、Veo、万相**；DeepSeek、OpenRouter、Ollama | **bring your own API keys**；Seedance API, Kling API, Veo |
| AI 工作台 `guides/ai-studio` | **文生视频 / 图生视频**；首尾帧、AI 绘图、AI 音乐生成、Seedance 客户端 | **text-to-video / image-to-video desktop app**；Seedance desktop app, Kling API client |
| ComfyUI `guides/comfyui` | **ComfyUI 客户端**；ComfyUI 工作流、ComfyUI 模型库 预览图、LoRA 触发词、本地版「AI 应用」 | **ComfyUI client**；ComfyUI workflows as tools, model library with previews, workflow to app |
| 剪辑 `guides/editing` | **AI 剪辑**；逐字稿剪辑、双语字幕、声音克隆、AI 配音、F5-TTS / CosyVoice 图形界面 | **AI video editor**；transcript-based editing, voice cloning, F5-TTS GUI |
| 数字人 `guides/digital-humans` | **AI 数字人 / 照片说话**；数字人口播、口型同步、视频翻译 改口型 | **talking photo / AI digital human**；lip sync, talking head video |
| 工作流 `guides/workflows` 与 `/workflows` | **AI 视频工作流模板**；带货口播视频、模特上身图、长视频切片、爆款视频拆解、主题生成视频 | **AI video workflow templates**；AI product promo video, long video to shorts, topic to video |
| 画布 `guides/boards` | **AI 无限画布**；分镜画板 | **AI infinite canvas** |
| 3D `guides/scenes` | **3D 分镜预演**；AI 分镜、白模、Blender | **3D previs**；AI storyboard, Blender |
| 发布 `guides/publishing` | **短视频多平台发布**；抖音、小红书、B 站、YouTube | **multi-platform video publishing** |
| 插件 `/plugins` | **Mosael 插件**；ComfyUI 插件、Blender MCP、Manim、Remotion、TikHub | **Mosael plugins**；Blender MCP, MCP server |
| README / GitHub | 与首页一致，另加 GitHub topics(见下) | 同上 |

几类要**回避**的词：

- 「秋叶整合包 / ComfyUI 整合包」：搜的人要的是网盘安装包，意图对不上。
- 「AI 工作流自动化」：结果页是扣子、Dify、n8n，意图对不上，改用「AI 视频工作流模板」。
- 「ComfyUI manager」：指的是 ComfyUI-Manager 插件，意图对不上。
- 「本地 AI 绘画 Mac」：Draw Things 占着这个词。
- 任何带「开源」的说法。

## 只有维护者能做的事

### 1. Google Search Console

1. 添加**网域资源**，用 DNS TXT 验证(推荐)。如果用网址前缀方式，就把 HTML 标签里 `content` 的值填进部署环境的 `SITE_VERIFICATION_GOOGLE`，重新部署。
2. 在「站点地图」里提交 `https://mosael.com/sitemap.xml`。
3. 用「网址检查」逐个请求编入索引：`/en`、`/zh`、`/en/docs/start/download`、`/zh/docs/start/download`、`/en/docs/guides/comfyui`、`/zh/workflows`。
4. 过两到四周看「网页」和「效果」报告：哪些词有展示、没点击，就回来改对应页的 title 和 description。

### 2. 百度搜索资源平台(ziyuan.baidu.com)

1. **先做账号实名认证。** 2023-09 起，非实名账户下的站点不能提交 sitemap。
2. 添加站点 `https://mosael.com`，选「HTML 标签验证」，把 `content` 的值填进部署环境的 `SITE_VERIFICATION_BAIDU`，重新部署。
   - 也可以用文件验证：把百度给的 `baidu_verify_xxx.html` 放进 `website/public/`。
   - **验证通过后不要删掉。** 标签或文件被删，站点会被判定为验证失效。
3. 提交 sitemap：`https://mosael.com/sitemap.xml`。我们的 sitemap 是扁平的，不是索引型，百度能处理。配额由站点质量决定，别指望一次全收。
4. **普通收录 API 推送**：在平台的「普通收录」里拿 token，每天推最重要的几条，配额可能很少。**token 不要提交进仓库。**

   ```bash
   printf '%s\n' https://mosael.com/zh https://mosael.com/zh/docs/start/download https://mosael.com/zh/workflows > urls.txt
   curl -H 'Content-Type:text/plain' --data-binary @urls.txt "http://data.zz.baidu.com/urls?site=https://mosael.com&token=<你的token>"
   ```

5. 「快速收录」只对 VIP 站点开放(要求实名、ICP 备案、运营一年以上等)，现在不用管。
6. 百度排名**不需要 ICP 备案**，只有服务器放在大陆才需要。境外主机也能收录，但抓取会慢一些。域名 DNS 要选稳定的服务商。
7. `/` 会 307 跳到 `/en`，所以给百度报的主入口用 `https://mosael.com/zh`。

### 3. Bing Webmaster Tools(也覆盖 DuckDuckGo、Yahoo)

可以直接从 Google Search Console 导入站点；也可以用 meta 验证，填 `SITE_VERIFICATION_BING`。导入后提交 sitemap。

### 4. 360、搜狗(可选)

两家分别对应 `SITE_VERIFICATION_360` 和 `SITE_VERIFICATION_SOGOU`，各自在站长平台提交 sitemap。

### 5. GitHub 仓库信息(在仓库 Settings 里改)

**Description**(GitHub 搜索和 Google 结果都会显示这一行)：

> Local-first desktop AI video studio for macOS & Windows: generate with your own API keys (Seedance, Kling, Veo, Wan) or ComfyUI, edit on a timeline, clone voices, dub & lip-sync, make talking-photo videos, automate product promos and shorts. 本地优先的 AI 视频创作软件。

**Website**：`https://mosael.com`

**Topics**(最多 20 个，**不要加 `open-source`**)：

`ai-video` `ai-video-generator` `ai-video-editor` `video-editor` `comfyui` `comfyui-frontend` `seedance` `kling` `text-to-video` `voice-cloning` `tts` `ai-dubbing` `lip-sync` `video-translation` `digital-human` `talking-head` `infinite-canvas` `local-first` `electron` `desktop-app`

再上传一张 Social preview 图(Settings → General → Social preview)，直接用 `website/public/og/mosael-en.png`。

### 6. 外链与社区

| 渠道 | 地址 | 怎么做 |
| --- | --- | --- |
| awesome-alternative-uis-for-comfyui | https://github.com/light-and-ray/awesome-alternative-uis-for-comfyui | 最契合，收录 Electron/Tauri 桌面应用，提 issue 或 PR |
| awesome-comfyui | https://github.com/lucianosb/awesome-comfyui | 放进「Projects using ComfyUI」一节 |
| awesome-comfyui(中文) | https://github.com/hua1995116/awesome-comfyui | 同上 |
| Product Hunt | https://www.producthunt.com/categories/ai-video-editor | 首发选一个周二到周四，准备好截图和 30 秒演示视频 |
| Hacker News Show HN | https://news.ycombinator.com/showhn.html | 不要求开源，但要求能直接试用。标题写清是 source-available；只发一次，版本更新不算 Show HN |
| V2EX 分享创造 | https://www.v2ex.com/go/create | 写开发故事，不要硬广，重复发会被移到「推广」 |
| 少数派 Matrix | https://sspai.com/post/40262 | 以开发者身份写，不要伪装成第三方测评 |
| 阮一峰 科技爱好者周刊 | https://github.com/ruanyf/weekly/issues | 投稿软件；标题不要写「开源」 |
| AlternativeTo | https://alternativeto.net | 作为 ComfyUI、Descript、Stability Matrix、RunComfy 的替代品登记，许可选「Free for personal use」，**不要勾 Open Source** |
| AI 工具集 | https://ai-bot.cn | 中文 AI 工具目录，ComfyUI、视频翻译、无限画布等词的结果里反复出现 |
| Reddit | r/comfyui、r/StableDiffusion、r/VideoEditing | 先读版规；r/StableDiffusion 偏好开源和本地项目，要写清许可 |
| 知乎、CSDN、掘金、B 站 | — | 几乎每个中文查询前排都是这几家。写「教程 + 对比」长文，文中链接回对应的官网页面 |

**不要投**只收开源项目的渠道：HelloGitHub、opensourcealternatives.to、openalternative.co。r/selfhosted 面向自托管服务，也不合适。

适合写的长尾文章(每篇链接回关键词地图里对应的页)：

- 用自己的 Seedance / 可灵 API Key，在 Mac 上做带货口播短视频 → `/zh/workflows/product-pitch-short`
- 把 ComfyUI 工作流变成模型和工具，模型库看预览图和触发词 → `/zh/docs/guides/comfyui`
- 本机用 F5-TTS 克隆音色给视频配音 → `/zh/docs/guides/editing`
- 视频翻译配音加改口型，一条工作流从原片到成片 → `/zh/workflows/translated-dub-lipsync`
- 一张照片 + 一段稿子生成数字人口播 → `/zh/docs/guides/digital-humans`
- 英文：*Bring your own API keys: a desktop AI video studio for Seedance, Kling and Veo*；*Turning ComfyUI workflows into tools next to a video editor*

### 7. 统计(可选，这次没加)

已有 GA4，用 `NEXT_PUBLIC_GOOGLE_ANALYTICS_ID` 开关。其他选项都**需要你拍板**，这次一个都没加：

- 百度统计：要嵌一段第三方脚本，国内来源数据比 GA 全。
- Vercel Web Analytics：不用 cookie，部署平台自带。
- 自建 Plausible 或 Umami。

如果只想知道「搜什么词进来」，Search Console 和百度资源平台的报表就够了，不需要加脚本。

### 8. 需要你决定的定位问题

带货口播、模特上身图、账号诊断这些模板面向的是**做生意的人**，而许可禁止商业用途，商用需要书面授权。这些模板引来的流量里，很大一部分会立刻碰到许可问题。建议在官网放一个清楚的「商业授权」入口，比如联系页上的一节或一张价格表，让这部分流量有地方转化。现在只有首页和联系页里的「商业授权与合作」微信入口。

## 来源

- ComfyUI 生态：https://docs.comfy.org/interface/app-mode · https://blog.comfy.org/p/from-workflow-to-app-introducing · https://github.com/Comfy-Org/desktop · https://www.uisdc.com/comfyui-v1 · https://github.com/light-and-ray/awesome-alternative-uis-for-comfyui · https://github.com/lucianosb/awesome-comfyui · https://www.toolmage.com/zh-hans/tool/runninghub/alternatives/
- 视频生成与电商：https://www.volcengine.com/article/41461 · https://docs.volcengine.com/docs/ark/seedance-2-0?lang=zh · https://adlibrary.com/posts/best-ai-ugc-video-generators
- 数字人、语音、翻译：https://aigcpanel.com/ · https://voicebox.sh/ · https://pyvideotrans.com/blog/videotrans · https://github.com/topics/heygen-alternative
- 剪辑与切片：https://alternativeto.net/software/descript/ · https://github.com/topics/opus-clip-alternative · https://www.movavi.com/learning-portal/apps-like-capcut.html
- 画布与工作流：https://ai-bot.cn/infinite-canvas-deep-dive/ · https://www.wireflow.ai/blog/top-flora-ai-alternatives · https://nodetool.ai/alternatives/krea
- 社区规则：https://news.ycombinator.com/showhn.html · https://www.v2ex.com/go/create · https://sspai.com/post/40262 · https://github.com/ruanyf/weekly · https://alternativeto.net/faq/
- 百度：https://ziyuan.baidu.com/college/documentinfo?id=1343&page=3 (搜索引擎优化指南) · https://ziyuan.baidu.com/college/articleinfo?id=3159 · https://ziyuan.baidu.com/college/articleinfo?id=470 · https://ziyuan.baidu.com/wiki/990 · https://www.zhihu.com/question/623426294 · https://byte-port.com/baidu-seo-without-china-hosting-2026/

调研没有拿到搜索量数据，结论是定性的：依据是谁占着结果页、有没有大量「替代 / 推荐 / 对比」类文章，以及 GitHub topic 和社区帖子。上线后以 Search Console 和百度资源平台的实际数据为准，回头修正这张表。
