# Changelog

This file records user-visible release highlights. GitHub Releases contains the complete generated
commit list and downloadable artifacts.

## [1.3.1] - 2026-09-11

### 智能体对话里可以 `@` 东西了

- 输入框里打 `@` 直接引用素材、笔记、画板、工作流：正文写的是名字，id 走结构化字段发给模型。名字会重、会改，拿它当标识迟早出事；而把一串十六进制塞进句子会把真正的话挤没。
- 发出去之后气泡里仍然是胶囊，点开就打开对应的素材或页面 —— 不是一串被抹平的 `@名字`。点的那一刻才去问「它还在不在」，删掉的直说删掉了，而不是跳进一个空页面。
- 引用清单会告诉模型每一项该用哪个工具去读；跨工作区的 id 一律当作不存在。

### 思考模式按各家实际支持的来

- 各家的思考参数不是同一套词，猜错一个值就是整轮 400。改成按供应商查表，只声明查证过的：Kimi k3 一直思考、只收低/高，OpenAI GPT-5.x 的关闭是 `reasoning_effort: none`。
- 关不掉的模型不再摆一个点了没用的「关闭」，改成「模型默认」—— 我们确实没关掉它，只是没提要求。
- 这条连接发不出档位时给一个占位的禁用输入，说得出为什么，而不是留下一个底下什么都没有的标题。

### 界面修复

- **深色下菜单里的分组线看不见**：它取的是页面那层的分隔色，而菜单画在更浅的浮层上，实测对比 1.013 —— 画了等于没画。改成贴着所在表面算，菜单、命令面板、通知与任务面板的分隔线一并回来。
- 生成页的「引擎参数」栏和对话页右侧的检查器统一成一套：十几个平铺的字段收成引擎 / 出片规格 / 输入素材 / 调参四块，标题行不再跟着滚，控件回到同一套高度、底色和焦点样式。
- 插件市场加载时的占位块此前和它踩着的浮层几乎同色（对比 1.07），看起来像「什么都没加载」。
- 设置页各 tab 的表单回到同一套刻度；空状态占住整节正文并居中，字号轻一级；供应商未配置时是一格说得出话的「未设置」，不再是一条读起来像坏了的横线。
- 数据与诊断页末尾那条底下什么都没有的横线没有了 —— 分割线改由相邻的两节自己画，走 portal 的对话框不再算作一节。
- 场景与 Blender 面板里几个指向开发分支的链接改回文档站，此前点进去都是 404。

### 稳定性

- 删掉画板上的节点时一并删掉挂在它上面的连线：留下一根两端悬空的线会让**整张画板存不下去**，而用户只看到「画板没能保存」，和刚删掉的那个节点对不上号。序列化时再兜一道。
- TTS 引擎的安装判定不再把没下完的分片算作进度：那截字节既不能加载，也不代表进度到手，此前会出现「量到 1.40 GB / 需要 0.90 GB」却判未装好的自相矛盾。诊断日志现在点名是哪个残片、多大、什么时候写的，并说清它不会自动清理。
- 智能体正忙时排队的消息，发给模型的那一份此前会丢掉 `@` 引用。
- 挂了笔记再发送，气泡里不再一点痕迹都没有。

## [1.3.0] - 2026-09-10

### 选项一多就能搜

- 模型、音色、字体、LUT、发布平台、供应商模型、工作流的上游输出……凡是清单长度由你的账号和素材决定的下拉，超过一定条数自动带搜索框；短清单保持原样，不平白多出一行输入。
- 字体选择器仍然按各自的字体渲染每一行 —— 字体是用样子挑的。
- 具名输出那一列不再摆花括号：存的仍是 `{{…}}` 模板，屏幕上读到的是 `source_video.asset_id`。

### 画布协作

- 团队讨论从居中对话框改成右侧侧栏：讨论说的就是背后那张画布，对话框打开的一瞬间把它要讲的东西盖住了。不再分「清单 + 详情」两栏，每条讨论就是完整的一张卡，读下去即可。
- 工作流页新增讨论中心，与创意画板共用同一份 —— 此前只能在画布上一个个点开评论钉找。
- 「在画布中查看」会避开右栏停靠或悬浮的面板；在视口中心加标记同理，不再落在智能体底下看不见。
- 标记清单去掉重复的「添加标记」：加标记是工具条的事。

### 素材与画布

- 素材筛选栏收成一行，按「这是哪一类动作」分三段；未滚动时透明，吸顶时半透 + 高度模糊，跟着滚动淡入而不是突然铺一层底。
- 画布上的浮窗收成同一种材质：透得出来，而且有影子；停靠成右栏时也保留影子，不再一块浮着一块贴着。
- 触控板平移横穿合成器不再当场停住 —— 整块面板此前都挂着 `nowheel`。
- 画板的模型选择器按内容取宽并设上限，不再把「参数」推到行尾。

### 智能体

- 输入框里的附件和笔记引用收成一排：图片视频带缩略图、点开走全局灯箱可翻页；文本附件和笔记点开看到的就是真正发出去的那段字。
- 对话时间线里工具调用、思考块和「正在思考」共用同一个左缘、图标栏与字号。

## [1.2.0] - 2026-09-09

### 3D 场景与动画

- 统一工作台与完整物体时间线：相机和普通物体共用关键帧插入、拖动、多选、删除和撤销；移除重复的走位与记录视角入口。
- 自由视角、机位视角和全局动线同步预览；全屏保留建模助手、Blender、生成、导出及属性编辑。
- 场景列表保留详情导航，补齐右键与多选；右栏整体 section 可折叠，属性直接展开，统一单行时间线与面板间距，添加物体使用 ghost 按钮。
- 场景帧支持图片生成；视频可使用首尾帧或运镜预览。增加灯光预设、灰模参考、压缩模型支持及流式模型存储。
- Blender MCP 支持发送模型与相机轨道、接回当前场景或新场景，以及直接获取当前 Blender 场景。

### 画布协作

- 工作流与画板的评论、标记使用独立模式，支持 Esc 退出及各自的一键显示隐藏；每张画布仅打开一个标记编辑器。
- 评论支持编辑与交互式成员提及；修复相邻评论点无法点击、标记模式撤销后连线消失的问题。
- 文档正文和内嵌图片可拖动节点，模式切换保持标题栏高度；统一标记弹窗布局与操作按钮。

### 发布前修复与文档

- 阻止删除镜头仍在使用的相机或其祖先组，避免场景保存失败。
- 修复 Blender 发送时缺失相机帧转换、可选 FOV 为空、首帧前错误外推、接回插值节奏及已不存在的相机父组引用。
- 修复灰模选项未传递，以及嵌套摄像机辅助模型混入参考帧和 GLB 导出。
- 浏览器池按环境能力处理 WebAuthn 与多凭据选择；macOS 正式包接入 Developer ID 签名、描述文件与 Apple 公证，Touch ID 从安装包的有效签名读取钥匙串权限，不再依赖运行时环境变量。
- 更新中英文指南、3D 与协作文档、发布说明及真实界面截图/录屏。

## [1.1.0] - 2026-09-07

### 笔记与知识库

- 新增工作区笔记与知识库：Tiptap 编辑、Markdown 导入导出、行内引用、版本记录和回收站；智能体回答支持可跳转的笔记与网页来源。
- 工作流支持搜索、读取和创建笔记；无限画布可引用固定版本的文档，并将正文传给文案、图片、视频及配音节点。

- 笔记引用默认打开最新正文，引用版本可主动查看；列表新增多选、快捷键连选、右键菜单，以及批量收藏、导出、移入回收站、恢复和彻底删除。

- 笔记图片支持选中后就近编辑链接与替代文字；代码块增加语言选择、明暗主题语法高亮和一键复制，保留 Markdown 与撤销操作。

- 笔记工具栏增加正文与 H1–H6 选择器，随光标同步段落样式，并统一列表选中状态与正文层级。

### 剪辑

- 「生成字幕」现在沿用逐字稿的词级时间戳：同一份稿子在逐字稿页和字幕轨上的断句一致，不再把整段切成一条一分钟的字幕；中文句号后不跟空格也能正确断句。

### 从逐字稿与字幕生成文档

- 逐字稿的「保存到笔记」在未选中片段时导出**全文**（此前只导出播放头所在的那一句）；字幕页新增同样的入口，双语字幕的原文与译文一起写入。
- 正文可选两种形状：「正文」把连着说的句子并成段落，适合当稿子；「带时间戳引用」每句一个引用块，适合回看时对回视频。两种共用同一份来源。
- 往笔记追加内容不再打断正在编辑这篇文档的人：追加会并进当前草稿，而不是让对方的自动保存撞上冲突提示。

### 修复

- 智能体的自动放行判断此前因为一个未定义的变量从未真正执行过，每次都静默退回人工确认；现在可以正常工作。

- 笔记引用默认打开最新正文，引用版本可主动查看；列表新增多选、快捷键连选、右键菜单，以及批量收藏、导出、移入回收站、恢复和彻底删除。

- 笔记图片支持选中后就近编辑链接与替代文字；代码块增加语言选择、明暗主题语法高亮和一键复制，保留 Markdown 与撤销操作。

- 将触控板／鼠标切换移到 3D 视图工具栏，使用垂直居中的纯图标按钮一键切换，并扩展到工作流、子图和无限画布；设备选择统一记忆，平移与缩放行为同步切换。

- 3D 视图适配触控板双指平移、捏合缩放和 Shift 环绕，保留可记忆的鼠标模式，防止手势误缩放应用。

- 修复 3D 物体无法使用 macOS 删除键移除的问题，增加列表删除入口；搭建与运镜步骤的下一步操作固定在右侧底部。

- 笔记工具栏增加正文与 H1–H6 选择器，随光标同步段落样式，并统一列表选中状态与正文层级。

- 3D 页面统一为轻量步骤页签与固定工具栏，面板沿用全局主题和圆角；镜头留白跟随界面背景，保持场景渲染颜色不变。

- 3D 工作台与视图支持独立全屏、Esc 退出和嵌入环境回退；保存状态紧随场景名称展示。

- 笔记工具栏、正文和列表统一主题边界；低频操作收进菜单，修复回收站选择错位和标签输入中断。
- 3D 工作台按搭建、运镜、生成分步展示，增加常用运镜预设、视角说明和独立的高级参数设置。

- Added an editable 3D scene workspace with primitives, parameterized rooms and stairs,
  GLB/glTF import, transforms, materials, lights, revision history and camera keyframes.
- Added deterministic MP4 camera-preview exports, first/last-frame and reference-video
  handoffs to creative boards, and scene editing tools for the user's selected chat model.
- Consolidated note formatting, save status and view controls into one document toolbar.

## [1.0.0] - 2026-09-07

### Stable release

- Promoted the completed 1.0 feature set to the stable channel with versioned macOS Apple Silicon
  and Windows x64 installers; 1.0.0 is the latest stable update.
- Includes the unified frosted interface, redesigned editor and media previews, global bundled
  fonts, agent voice, workflow scheduling, plugin connections and multi-worker publishing.
- Updated all 40 bilingual website guides and current product captures, with a layered README
  showcase, controllable recordings and verified documentation links.

## [1.0.0-beta5] - 2026-09-07

### Changed

- Unified window navigation, buttons, filters, dialogs and menus; softened separators and introduced
  translucent blurred overlays that preserve custom backgrounds.
- Rebuilt the editing workspace with compact toolbars and adaptive panels; redesigned video/audio
  previews and contained long media titles and timeline-menu names.
- Refreshed all active website screenshots, GIFs and screen recordings in Chinese/English and
  light/dark themes, and updated the bilingual guides, homepage and README media.

### Added

- Added global interface font selection with bundled Chinese/English combinations, including
  Space Grotesk, Newsreader, Caveat and Kalam, with live previews in Appearance.
- Added Appearance and Scheduled Tasks guides, controllable MP4 documentation players, and
  capture provenance/integrity checks.

### Fixed

- Kept asset menus exclusive and corrected canvas mention-menu positioning and generation forms.
- Restored dragging in empty floating-window headers, fixed released connection curves, and
  centered selected workflow nodes in the unobscured canvas when an assistant panel is open.
- Removed panel headings duplicated by mode tabs and aligned action-button sizes and list edges.

## [1.0.0-beta4] - 2026-09-06

### Added

- Added agent dictation, spoken replies, interruptible hands-free conversations, and navigation from
  tool-result references; voice input no longer creates temporary media-library assets.
- Added plugin OAuth authorization, remote worker connections, multiple publishing workers, and
  child-task visibility in scheduled runs and workflow history.

### Fixed

- Restored Baidu Netdisk imports and uploads from the plugin tool panel by passing the selected
  workspace, and corrected OAuth declarations, result limits, and parameter descriptions.
- Preserved cancellation across workers, scheduled children, nested workflows, and browser publishing;
  persisted worker ownership leases so abandoned jobs settle instead of remaining active indefinitely.
- Matched upper-track effects, playback speed, audio gain, fades, solo, and ducking between editor
  preview and export, including speed-aware workflow timeline operations.
- Rejected non-finite numeric API inputs, enforced workspace ownership in workflow nodes, validated
  nested workflow configurations, and corrected nested canvas frame movement.
- Restored workflow speech synthesis with either cloned or engine-provided voices and improved the
  bundled examples, plugin controls, and workflow canvas responsiveness.

### Upgrade notes

- Code nodes now require Docker with Linux containers and the pre-pulled `python:3.13-alpine` image.
  Code runs without host mounts or network access, with bounded memory, processes, time, and output.
- Custom external job workers must adopt the claim/heartbeat/report lease protocol. Update desktop
  and backend components together; see `docs/adr/0002-claim-report-worker-protocol.md`.

## [1.0.0-beta2] - 2026-09-04

### Added

- Added synchronized screen-and-camera recording, optional system-audio capture, remembered camera
  mirroring, explicit device-permission recovery, and a floating controller that keeps recordings alive
  while navigating the rest of Mosael.
- Added circular and rounded-rectangle clip masks plus configurable drop shadows, with matching preview,
  project persistence, undo, and FFmpeg export behavior.
- Added data backup and diagnostics settings, startup migration-plan validation, safer database restore and
  upgrade handling, and relocatable local-backend launch paths.
- Added a workflow community, end-to-end topic-video and transcript-cleanup workflows, immutable workflow
  version history, and complete per-node execution history and output inspection.
- Added optimistic revision conflict detection, actor-attributed activity events, and Notion-style spatial
  discussions on Infinite Canvas with mentions, direct deletion, and author-controlled dragging.

### Changed

- Exposed Seedance 2.0 reference and first/last-frame video modes, stabilized media-reference slots, and
  previewed audio references with the correct media interaction.
- Made workflow node metadata and official data bindings authoritative, localized node ports consistently,
  and limited executable revisions to changes that can affect a run.
- Preserved ASR punctuation, exposed transcription-engine selection, and reduced structured transcript
  analysis payloads while retaining the time-coded evidence needed by the model.
- Replaced technical plugin function identifiers with human-readable tool names and descriptions.
- Split Settings, workflow canvas presentation, provider definitions, process protocols, and API clients
  along their domain boundaries without changing persisted user data.

### Fixed

- Gave the macOS development shell its own Mosael bundle identity and re-signed it after branding, so privacy
  permissions register under Mosael instead of an invalid generic Electron identity; packaged identity is unchanged.
- Removed browser-provided default/communications aliases from recorder device menus, preventing duplicate
  system-default entries and two simultaneous selected states while preserving explicit physical devices.
- Kept screen and camera streams attached to the live preview when the recorder changes from its setup dialog
  into the floating controller, preventing both preview panes from turning black during an active recording.
- Prevented requested system-audio capture from silently degrading into a mute screen recording when the macOS
  sharing picker returns no live audio track, and now explains how to retry with audio sharing enabled.

- Preserved raw LLM responses and parser diagnostics when structured output fails, accepted wrapped JSON,
  handled unsupported response formats, and retained the full successful-to-failed workflow event history.
- Stabilized workflow focus, inspector layout, current revisions across restarts, bounded version-history
  refreshes, node-output framing, and the official video-pipeline bindings used by bundled workflows.
- Fixed Infinite Canvas comment-mode click-through, accidental comment creation after drags, canvas scrolling
  across comment nodes, comment draft focus and dragging, overlay dismissal, reference-slot focus, and node
  interaction inside full-bleed overlays.
- Restored nested image-preview interaction and kept media details visible beneath previews.
- Unified Settings spacing ownership, typography, colors, radii, list/header rhythm, and bounded Team Activity
  to an internally scrolling region instead of letting it grow with the event history.
- Restored long-running AI Studio conversations by budgeting in-turn tool results, returning a compact workflow-node
  catalog, rejecting one-token truncation fragments, and reporting only the current turn's usage; unknown cloud models
  now default to a 128K context window while local endpoints retain a conservative fallback.
- Kept AI Studio and embedded-agent headers inside narrow panels by allowing long session titles to shrink and truncate
  without pushing tabs or window controls beyond the panel edge.

## [1.0.0-beta1] - 2026-09-03

### Changed

- Consolidated compatibility handling around one rule: owned data migrates once to the current shape,
  while mixed-version desktop components are not supported; the documented direct-upgrade floor is v0.1.0.
- Migrated legacy board job/error state into the current `run` object at startup and removed the matching
  frontend dual-read branches, the obsolete TTS source migration, and the generation-model type alias.
- Stopped guessing that workspaces named “Workspace” or “默认工作区” are system defaults, preserving names
  exactly as their owners entered them.
- Desktop navigation accepts only the registered `mosael://` protocol.
- Updated the homepage hero and editing chapter to use the supplied current editor capture, and added a
  dedicated media-management chapter with the supplied library and recording view.
- Extended the release gate to build the browser extension and bilingual website, and kept beta tags as
  GitHub prereleases instead of replacing the latest stable release.

### Fixed

- Portaled the documentation search modal outside the blurred floating header so its dimming layer and
  click-away target cover the full viewport, and added a rhythm-matched divider below the app rail logo.
- Extended inner-page hero backgrounds behind the floating navigation instead of leaving a separate page-color
  strip above Workflows, Plugins, and plugin details.
- Removed redundant screenshot shells from homepage product chapters and tightened the Mosael wordmark asset so
  footer alignment, navigation sizing, and closing-brand spacing follow the visible artwork rather than transparent padding.
- Increased footer group and link spacing so the lower navigation remains easy to scan in both languages.
- Normalized Settings section rhythm and full-width form rows, with the current password separated from
  the new-password pair so account editing follows the same hierarchy as the other settings pages.
- Serialized creative-board autosaves, waited for server confirmation before clearing pending state, and
  retained the latest canvas for a later retry after a failed write.
- Released AI sidecar steering channels on provider errors, callback failures, timeouts, and aborts as well
  as successful turns, preventing stale sessions and child processes from lingering.

## [0.27.6] - 2026-09-02

### Changed

- Rebuilt the Mosael website around a centered editorial hero, a larger product stage, open full-width
  chapters, and a more distinctive violet-to-coral brand rhythm across light and dark themes.
- Reworked the product story and bilingual headline around a continuous creative path from scattered ideas
  to a finished story, while keeping the real Infinite Canvas, editor, agent, and workflow captures central.
- Carried the same open, lightly divided visual language through Workflows, Plugins, plugin details,
  documentation, mobile navigation, not-found pages, and the footer instead of enclosing every section in a card.
- Replaced the edge-attached site bar with a fixed translucent capsule that floats over the homepage color,
  and removed the redundant Infinite Canvas navigation tab.

### Fixed

- Corrected active navigation matching so Product is highlighted only on the homepage and Docs stays active
  across every documentation route.
- Prevented the mobile navigation overlay from being clipped by the blurred header container.
- Replaced the unusable generation composer state with direct model-configuration actions in both the composer
  and engine panel when no image or video generation model is available.

## [0.27.5] - 2026-09-02

### Fixed

- Restored the plugin marketplace by replacing its retired website endpoint with a reachable
  published registry.
- Prevented marketplace requests from inheriting AI-provider retry behavior, so an unavailable feed
  now reaches a clear error state instead of leaving the dialog on loading placeholders for multiple
  retry cycles.

## [0.27.4] - 2026-09-02

### Changed

- Rebuilt the bilingual Mosael website around a flowing product-story timeline, with a calmer
  warm-white and violet visual system, deliberate editorial spacing, and responsive navigation.
- Gave Infinite Canvas, timeline editing, the AI agent, and visual workflows equal prominence using
  current product captures, while keeping the local-first promise and KindaHuaX attribution clear.
- Removed the outdated knowledge-base claim and the nonexistent product X account from website copy.

## [0.27.3] - 2026-09-02

### Changed

- Strengthened the visual hierarchy across Settings with a clearer page, section, item, and
  supporting-copy type scale, plus more deliberate row and section spacing.
- Kept controls, dividers, and the flat panel structure unchanged so the denser information remains
  familiar while becoming easier to scan.

## [0.27.2] - 2026-09-02

### Changed

- Replaced the macOS menu-bar and Windows notification-area icons with the supplied Mosael mark,
  using native 1×/2× resources sized for persistent system status surfaces.
- Made the Windows tray mark follow the system appearance with dedicated dark-on-light and
  light-on-dark variants, while macOS uses a template image for automatic menu-bar contrast.

## [0.27.1] - 2026-09-02

### Changed

- Standardized empty collections on the workflow-page pattern: the board, Browser Pool, publish,
  media, plugin, scheduler, and supported settings states now center within their true remaining
  content height, while list-only toolbars stay hidden until they are useful.
- Kept settings section headers visually separate from their content and removed the extra frame
  around a scheduled task's bound workflow.
- Replaced the AI Studio model picker with a direct configuration action when no chat model exists,
  and aligned expanded thinking and loading markers with their text.

### Fixed

- Resolved inherited default-provider model metadata before calculating context usage, so a new
  Kimi K3 conversation uses its real catalog window instead of incorrectly reporting only half of
  the fallback window as available.

## [0.27.0] - 2026-09-02

### Added

- Extended the Chrome Side Panel from three hard-coded sites to every HTTP(S) video URL recognized
  by the installed yt-dlp extractor registry, while preserving native caption adapters for YouTube
  and Bilibili.
- Added a lightweight authenticated URL-support endpoint and optional Browser Pool identity selection
  for restricted, signed-in, proxied, or region-sensitive imports and automatic transcription.
- Added a registry-wide contract test that checks every canonical yt-dlp extractor sample without
  making network requests.

### Changed

- Renamed the product, application packages, desktop shell, backend, website, browser extension,
  plugin format, workflow format, environment variables, deep links, and documentation to Mosael.
- Replaced the previous mark with the supplied Mosael identity: separate light and dark app icons
  now follow the active theme, while the supplied wordmark appears in the README and website.
- Refined the bilingual README, website, and sign-in copy around the shared “ideas find their
  timeline” voice, and added the author's X profile to the main project touchpoints.
- Added one-time compatibility migration for existing local data, Electron user data, environment
  overrides, browser-extension sessions, frontend preferences, plugin manifests, workflow files,
  and deep links created before the Mosael rename.
- Separated backend import/transcription capability from in-page playback capability: custom,
  embedded, or protected players can still be imported when yt-dlp supports them, while seek and
  frame controls remain disabled unless a usable HTML5 video is present.
- Replaced site-specific manifest host lists with explicit HTTP(S) page access, required for generic
  player discovery and clean video-frame fallback capture.

### Fixed

- Replaced opaque yt-dlp 403, 412, login, geo, and IP-block failures with guidance to select a
  matching Browser Pool identity or proxy.
- Routed every image presentation surface through the browser-compatible preview endpoint, fixing
  broken HEIC/HEIF rendering in asset details, the editor compositor, compare view, boards, AI
  galleries, frame slots, and agent tool results while preserving original-file downloads.
- Replaced the asset-detail dialog's browser-native audio controls with the shared Mosael audio
  player, keeping playback, seeking, elapsed time, mute, and autoplay behavior consistent.

## [0.26.10] - 2026-09-02

### Added

- Added Pornhub video-page support with Mosael transcription fallback and stable source-URL
  recovery, so completed transcripts are reused instead of generated again.
- Added word-level transcript navigation for Mosael ASR results while preserving readable
  sentence grouping and sentence-level fallback for legacy data.

### Fixed

- Changed current-frame import to prefer decoded video pixels and exclude HTML playback controls;
  cross-origin media now uses a temporary overlay-free capture fallback.
- Hardened Bilibili subtitle fetching against translated pages, expired resources, and CORS/network
  failures, with localized error states instead of raw `Failed to fetch` messages.
- Replaced remaining native selects and shadow-heavy extension styling with the shared Tailwind and
  shadcn/ui treatment.
- Made direct agent messages and queued-message draining share one atomic session claim, preventing
  rare duplicate turns when a new message arrives as the previous turn finishes.

## [0.26.9] - 2026-09-02

### Added

- Added playback-synced bilingual subtitles to the Chrome Side Panel, preferring site-provided or
  YouTube translation tracks before using Mosael translation.
- Added one-click Mosael download and speech transcription when a video page has no captions.
- Added a localized React Side Panel that follows Chrome or can be pinned to Simplified Chinese or
  English, using Tailwind CSS v4 and shadcn/ui controls.

### Fixed

- Fixed Chrome rejecting account connections with `Failed to execute 'fetch' on 'Window': Illegal invocation`.
- Replaced raw empty YouTube JSON failures with a clear no-caption state and kept undelimited cues
  active for playback following.

## [0.26.8] - 2026-09-02

### Added

- Added a Chrome 116+ Side Panel extension for YouTube and Bilibili transcripts, timestamp seeking,
  transcript translation, current-video import, and visible-player frame capture into the Mosael
  media library.

## [0.26.7] - 2026-09-02

### Added

- Added the AI assistant to the editor and made the shared workspace assistant a docked column by
  default, with an optional floating mode.
- Made the assistant's current conversation title the header control, with searchable conversation
  switching and creation/deletion kept in the same compact surface.
- Added a richer animated startup state while the desktop shell connects to the backend.

### Changed

- Reworked transcript sentence rows so timestamps, speakers and the first text line align, long text
  wraps in full, and contextual actions no longer reserve empty width.
- Flattened settings sections and lists, using separators instead of nested card borders.
- Split jobs, notifications, scheduler, workflows and boards into domain-owned backend models,
  schemas and frontend API modules while preserving the public assembly entry points.

### Fixed

- Preserved workflow, board, scheduler, plugin and media detail context during reload instead of
  flashing each section's list page first.
- Prevented the editor assistant from covering the workspace when opened.

[1.0.0-beta2]: https://github.com/Alndaly/Mosael/releases/tag/v1.0.0-beta2
[1.0.0-beta1]: https://github.com/Alndaly/Mosael/releases/tag/v1.0.0-beta1
[0.27.6]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.6
[0.27.5]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.5
[0.27.4]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.4
[0.27.3]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.3
[0.27.2]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.2
[0.27.1]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.1
[0.27.0]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.0
[0.26.10]: https://github.com/Alndaly/Mosael/releases/tag/v0.26.10
[0.26.9]: https://github.com/Alndaly/Mosael/releases/tag/v0.26.9
[0.26.8]: https://github.com/Alndaly/Mosael/releases/tag/v0.26.8
[0.26.7]: https://github.com/Alndaly/Mosael/releases/tag/v0.26.7
