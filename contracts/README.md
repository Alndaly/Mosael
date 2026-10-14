# 契约(contracts/)

这里放**必须在多个实现之间字面一致的语义**,以语言中立的语料形式表达,由各侧的测试套件分别执行。

不是文档,是可执行的规约:任何一侧改了语义而其它侧没跟上,**所有侧的 CI 都会红**。

## 为什么需要它

有些语义天生只能有一份定义,却必然有多份实现。

### `scene-cases.json` —— 场景契约

「t 时刻画面上有哪些层、什么 z 序、谁是 base、画面播多久。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/playback/sceneModel.ts` | `sceneModel.parity.test.ts` |
| 导出 | `backend/app/media/scene.py` | `backend/tests/test_scene_parity.py` |

**为什么不共用一份实现**:预览要在浏览器里本地同步跑到 60fps,还要处理尚未提交到后端的拖拽草稿;
导出要无头、在后端、并且可以被外部 worker 认领跑在别的机器上(见 [ADR-0002](../docs/adr/0002-claim-report-worker-protocol.md))。
这两个约束各自成立,合起来决定了模型必然存在于两种语言里。**"只有一份实现"不是可选项**,所以一致性
只能靠契约。

**这是有代价换来的教训**。契约诞生之前两侧各自手写、各自有绿测试、语义却相反,产生了用户可见的成片不一致:

- **上层 video 轨静音** —— 预览显示画面,导出把整层丢掉。给画中画轨点一下静音,成片里那层画面就没了。
  (轨道头是**喇叭**图标,语义只关音频,所以预览是对的。)
- **最底 video 轨为空** —— 预览把上层片段当 overlay(cover 取景),导出把它提为 base(遵 fill_mode)。
  同一条时间线两种取景。

两个 bug 都不是谁写错了代码,是**两份实现各自自洽而互不相识**。

### `studio-views.json` —— 界面上能去的页面

前端的 StudioView 和 `mosael://` 深链白名单(`electron/system/deepLink.ts`)必须是同一组。此前各自手写:深链还认
早已不存在的 `kb`,却不认资产、笔记、场景、画板、管理 —— 从官网链过来,应用被唤起却停在原地。两侧各有一条测试比对
这份清单。(智能体的 `open_view` 白名单曾是第三侧,随跳页能力一起撤掉了,见 ADR 0060。)

### `text-layer-cases.json` —— 文字层契约

「哪些片段作为字幕画出来、哪些作为花字画出来。」轨道上两个开关各管一件事:**隐藏**只管字幕显示,
**静音**只管声音。

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/playback/textLayers.ts` | `textLayers.parity.test.ts` |
| 导出 | `backend/app/media/scene.py` 的 `text_layers` | `backend/tests/test_text_layer_parity.py` |

**建立契约之前**:轨道只有一个 `muted`,字幕轨借它表示「不显示字幕」,视频轨上它又顺带把花字藏掉 ——
预览和导出各写了一遍这条筛选,两边碰巧一致,但都和轨道头上那个喇叭图标的意思相反:给一条轨关声音,
字从成片里消失了。现在字幕轨用 `hidden`(眼睛图标),`muted` 只管声音;场景契约管的是素材画面层,
这份管的是画在它们上面的文字。

**几条字幕轨同时有字(双语分两条轨)**:同一时刻各轨在场的字合成**一框**,一道一行(一条字幕自己有几行
就占几行),框整体按字幕样式定位(见下面的字幕契约)。道的顺序 `subtitle_lanes` 就是字幕轨在时间线上的
上下顺序(position 升序),道 0 在框的最上面 —— 字幕轨上没有「原文 / 译文」的标记,新建的字幕轨缺省放在
最下面,所以先有的原文轨默认在上;要换顺序就在时间线上挪轨道。`subtitle_frames` 是导出烧进成片的那几段(在场取
左闭右开,那一框字不变就是同一段);预览不切段,逐时刻用同一条规则合成(`textLayers.stackedSubtitleText`
⇄ `scene.stacked_subtitle_text` / `subtitle_frames`),前端那一侧按段取样比对。于是「分两条轨」和「同一条
轨里写两行」是同一框字、同一个画面。上一版(v2)让第二道换到画面另一头,底部样式下译文跑到了画面顶上。

### `subtitle-cases.json` —— 字幕契约

「同一份 `subtitle_style` 在同一画幅下,字幕框解析出来的几何与用色是什么、这个框放在画面的哪个像素上。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/subtitleStyle.ts` | `subtitleStyle.parity.test.ts` |
| 导出 | `backend/app/media/text_render.py` + `render_executor._subtitle_overlay_pos` | `backend/tests/test_subtitle_parity.py` |

**为什么不共用一份实现**:同上 —— 预览要跟着显示尺寸缩放(字号用 `cqw`、定位用百分比,交给浏览器解析),
导出要在原生帧上无头渲染(px 与 overlay 坐标)。两种写法**在画幅原生宽度上解析到同一个像素值**,
所以语料记的是**解析后的结果**,不是 CSS 写法。

**建立契约之前它是这样的**:圆角 `0.33em`、内边距 `0.16em 0.55em`、行高 `1.45`、最大宽 `86%`、投影 ——
这六组数字在 `Monitor.tsx` 的 `className` 里和 `_subtitle_style_css` 里各手写一遍;竖直定位也是两份,
后端那份的注释就写着「镜像预览 subtitleCss」。**"靠注释提醒对方"不是机制。** 建立契约时两侧恰好还是
一致的,所以这次没有换来 bug —— 它防的是下一次。

**多行的框(双语叠放)**:几条字幕轨同时有字时合成的是一框(见文字层契约),这里量的是整框的位置:
底部样式下框的下沿留在一行字幕时的位置、多出来的行往上长,顶部样式上沿不动、往下长,居中以框的中心为准。
框高是排版排出来的(行数 × 行高 1.45em + 上下内边距),语料把它当输入。预览是一个 DOM 元素、导出 PNG 是
同一套 CSS 渲染的一张图,高度天然一致;libass 回落是一条 Dialogue 用 `\N` 连起来 —— 它的行高是 Fontsize
(32px 时 44.8px)而不是 1.45em(46.4px),一条轨里写两行的字幕本来就差这一点。`backend/tests/
test_bilingual_subtitle_lanes.py` 真渲两条导出路径量像素:分两条轨和一条轨写两行逐像素相同、原文在上,
两条路径的行距差 ≤ 3px、贴边那一行的偏差与单行字幕相同。

### `text-stroke-cases.json` —— 花字描边契约

「描边画在哪、外圈多宽。」同一条花字有三条路径画描边:预览(DOM 上的 `-webkit-text-stroke`)、
导出 PNG(无头 Chromium 跑同一套 CSS)、libass 回落(`\bord`)。

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/textStyle.ts` 的 `outerStrokePx` / `textStyleCss` | `textStroke.parity.test.ts`、`textStyle.dom.test.tsx` |
| 导出 PNG + libass 回落 | `backend/app/media/render_plan.py` 的 `TextStyleSpec.outer_stroke_px`、`text_render._huazi_style_css`、`render_executor._text_style_tags` | `backend/tests/test_text_stroke_parity.py` |

后端那条 parity 除了跑语料,还**真渲**两条导出路径量像素:白芯在不在、外轮廓和修复前差没差、
libass 与 PNG 的外圈一不一样宽。只比 CSS 字符串验不出「字芯被吃掉」—— 那是浏览器画出来才有的事。

**建立契约之前它是这样的**:CSS 是**居中**描边,一半压进字里,霞鹜文楷这类细笔画字体白字黑描边时
白芯只剩不到 1%,字整个变黑;libass 的 `\bord` 是**纯外**描边,同一个存储值画出来的外圈是 PNG
路径的两倍。三份实现各自自洽,互不相识。现在统一成外描边,外圈取存储值的一半(正是居中描边向外
伸出的那部分,已有花字的外轮廓不变,不用迁移),按字号封顶。

### `transcript-sentence-cases.json` —— 断句契约

「转写引擎交来的段落怎么切成一句一行。」剪辑台的逐字稿和生成字幕、工作流的「生成字幕」必须切得一样。

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 剪辑台 | `frontend/src/domain/timeline/transcriptProjection.ts` 的 `transcriptSegmentsForEditing` | `transcriptProjection.parity.test.ts` |
| 工作流 | `backend/app/domain/voices/sentences.py` 的 `sentences_for_editing` | `backend/tests/test_transcript_sentence_parity.py` |

**为什么不共用一份实现**:剪辑台在浏览器里跟着时间线实时投影(切一刀、拖一下就重算),工作流在后台
节点里跑,中间隔着进程边界。**建立契约之前**:工作流直接拿引擎的段落当字幕(一段二三十秒、上百个字),
同一个视频两个入口铺出来的字幕不一样。

### `context-meter-cases.json` —— 上下文水位契约

「一组 pi 消息占了多少 token。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 决定压不压 | `agent-sidecar/src/compaction.ts` | `test/context-meter.parity.test.mjs` |
| 显示还能聊多久 | `backend/app/domain/context_meter.py` | `backend/tests/test_context_meter_parity.py` |

**为什么不共用一份实现**:压缩发生在 Node 侧的 pi 循环里,展示发生在 Python 侧的 HTTP 响应里,
中间隔着一次进程边界;而水位要在「还没开口」时就能看(打开旧会话、刚换模型、上一轮失败),
那些时刻根本没有新的一轮可以回报。

**建立契约时它已经坏了**。`context_meter.py` 的模块注释写着「两份实现必须保持同一套锚点规则,
改一处就要改另一处」—— 而它没做到:后端补上了 `cacheRead`(缓存命中的部分照样占窗口),
sidecar 那份没跟上。开着 prompt caching 时 `input` 只剩新增的一小段、绝大部分记在 `cacheRead` 上,
于是 sidecar 看到的水位只有真实值的零头:**界面显示 90%,压缩迟迟不触发,直到某一轮直接超窗失败**。
契约还顺带抓出第二处:Python 的 `json.dumps` 默认在冒号后加空格、JS 的 `JSON.stringify` 不加,
每个工具入参都系统性差出几个字符。**靠注释提醒对方不是机制。**

v6 补上 `cacheWrite`:pi 上报的 `input` / `cacheRead` / `cacheWrite` 是提示词里互不相交的三段,两侧此前都只
加了前两段。Anthropic 协议(Kimi Code 订阅走的就是它)开着缓存时,新进来的对话正记在 `cacheWrite` 上 ——
水位停在「工具定义 + 系统提示」那么高,压缩迟迟不触发;而 pi 夹 `max_tokens` 时是把它算进去的。

### `transform-cases.json` —— 片段变换契约

「一份 `clip.transform` 读出来是什么(默认、钳制、垃圾值怎么退),关键帧在某进度处采样成什么。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/TransformOverlay.ts` + `keyframes.ts` | `transform.parity.test.ts` |
| 导出 | `backend/app/media/render_plan.py` + `render_executor._kf_sample` | `backend/tests/test_transform_parity.py` |

**建立契约时它已经是四份互不相同的答案**:写入钳到 `scale≤4`、导出读取钳到 `scale≤10`、
关键帧那份 `rotation` 允许 ±3600,而预览**一处都不钳**、数字字符串还会静默退回默认值。
写入那份最严,所以另外几份从来没咬到过 —— 但那是「上游恰好挡住」,不是两侧一致。合法范围
现在只有一份(`domain.sequences.operations.TRANSFORM_BOUNDS`),两侧跑同一份语料。

### `clip-appearance-cases.json` —— 片段外观契约

「一份 `clip.effects` 读出来是什么:圆形蒙版的半径、阴影的开关/颜色/模糊/偏移,缺省与垃圾值怎么退。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/clipAppearance.ts` | `clipAppearance.parity.test.ts` |
| 导出 | `backend/app/media/render_plan.py` 的 `_read_appearance` | `backend/tests/test_clip_appearance_parity.py` |

外观是「画板上拖出来的那组参数」逐帧生效的前提:预览里圆的半径是 `cqw`、导出里是像素,
两边必须解析到同一个默认值表 —— 阴影默认开不开、模糊 24 还是 0,差一点都不只是样式问题,
而是"预览里不是这样"的成片。

### `clip-free-element-geometry.json` —— 自由元素几何契约

「带蒙版或阴影的片段(自由元素)在画幅里占哪一块:导出侧先铺满画幅再裁回来,预览侧必须算出同一块。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/playback/freeElementGeometry.ts` | `freeElementGeometry.parity.test.ts` |
| 导出 | `backend/app/media/render_executor.py` 的 `_appearance_filters` | `backend/tests/test_free_element_geometry_parity.py` |

**这份契约是两次用户可见的事故换来的**:先是成片里的圆比预览小 1.78 倍;修好大小之后,
圆里装的源又是错的 —— 两侧各写了一遍"铺满再裁"的几何,各自自洽,互不相识。
语料里的 `why` 字段留着完整的经过,提醒下一个想"就两行几何,各写一遍就好"的人。

### `clip-shadow-cases.json` —— 片段投影契约

「投影在画面上偏多少、糊多少:偏移按画面像素,σ = blur / 2,都不随片段的缩放、旋转变。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/playback/scenePaint.ts`(canvas shadowOffset / shadowBlur) | `clipShadow.parity.test.ts` |
| 导出 | `backend/app/media/render_executor.py` 的 `_with_shadow` | `backend/tests/test_clip_shadow_parity.py`(真渲一帧量像素) |

**建立契约之前**:预览的 canvas 投影本来就不受变换影响,导出却把投影画在元素自己的坐标里、再连同元素
一起缩放旋转 —— 缩到 0.4 的画中画,成片里的投影偏移只有预览的四成,转 90° 还换了方向;模糊还差一倍
(canvas 的 shadowBlur 是 2σ,导出直接拿它当 σ)。两侧的单元测试各自是绿的,因为没有一条同时看两边。

### `audio-mix-cases.json` —— 混音契约

「t 时刻每条音频轨的增益是多少:音量、变速下的淡入淡出、重叠淡变怎么缩放进片段长度、
独奏关掉谁、闪避什么时候压下去。」

用例可以带一段 `base`:基底视频轨上一段带声视频。闪避的规则两侧都是「标了闪避的轨,给任何一条
没标闪避、此刻有声的轨让路」—— **基底轨两头都算**:它的声音会让音乐让路,它自己标了闪避也会给
配音让路。基底轨一度两头都不算(预览)或只算一头(导出),于是「人声在原片里、音乐标了闪避」
这种最常见的片子里,按下闪避什么都不发生。

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/playback/audioMix.ts`(WebAudio 增益曲线) | `audioMix.test.ts` |
| 导出 | `backend/app/media/render_executor.py` + `render_plan.py`(FFmpeg 滤镜) | `backend/tests/test_audio_mix_parity.py` |

后端那条 parity 直接跑真 FFmpeg 出声再逐采样读回增益 —— 滤镜图写错一个参数,
拿假的求值器是验不出来的。变速 2x 的片段,淡入 1 秒到底占源素材的 1 秒还是成片的
1 秒,两侧答案必须一致,不然用户听到的是两种混音。

### `marker-shortcut-cases.json` —— 画布标记快捷键契约

「一个用户自己绑的快捷键归一成什么串,以及哪些键根本不给绑。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 配置(前端) | `frontend/src/lib/shortcuts.ts` | `markerShortcut.parity.test.ts` |
| 保存(后端) | `backend/app/domain/markers.py` | `backend/tests/test_marker_shortcut_parity.py` |

**为什么不共用一份实现**:归一要在**按下键的那一刻**当场给出判断(冲突就不给配,而"配上去之后
再看谁先响应"的表现是一个时灵时不灵的键);而"同一份文档里没有两个标记绑同一个键"是数据本身的
不变量,不能只由界面守 —— 总有一天会有第二个客户端写进来。

两侧归出不同的串时**都不会报错**,只会错开:界面说「没冲突」而后端拒绝保存,或者两个标记看着
绑了不同的键、存进去却是同一个 —— 而其中一个从此再也跳不到,用户看到的是"这个快捷键坏了"。

### `scene-3d-cases.json` —— 3D 场景契约

「每种物体长什么样(多少块、包围盒多大)、关键帧怎么插值、色温和太阳方向怎么换算。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 工作台(前端) | `frontend/src/features/scenes/sceneMeshes.ts`、`sceneGraph.ts`、`lighting.ts` | `scene3d.parity.test.ts` |
| 白模渲染与 GLB 导出(后端) | `backend/app/domain/scenes/render/` | `backend/tests/test_scene_3d_parity.py` |

**为什么不共用一份实现**:工作台要在浏览器里用 three.js 交互编辑(拖物体、实时看光影、GPU 渲染);
后端要无头渲白模参考帧和运镜视频(numpy 光栅化,可外派给 worker),同一份几何还要写成发往 Blender
的 GLB。三个消费者、两种语言。

**不一致时都不会报错,只会错开**:预览里人是 1.7 米、参考图里 2 米(生成模型照着错的比例出图);
预览里影子朝左、参考图里朝右;运镜在工作台是缓动、在参考视频里是匀速。全都静悄悄。

**这条契约是补上来的**:此前一致性只靠 `meshes.py` 开头那句「逐项对照前端 SceneViewport」——
而仓库里本来就有一条棘轮要求这类话必须点名契约,只是它的措辞表里没有「对照」,所以一直没响。
建契约的同时把这几种写法加进了那张表。

### `workflow-never-run-cases.json` —— 工作流里「一定不会跑」的节点

「这一层图里哪些节点一定不会被执行;哪些会跑的节点引用了它们。」`{{节点.输出}}` 引用即依赖,只管先后、
不管该不该跑:顶层只有开始节点是入口,一个没接进流程的节点每次都被跳过,引用它的下游插值成空串,
工作流照样报成功。后端运行前拦下「会跑的节点引用了一定不会跑的节点」,画布把被引用的那个标成 error、
把那条引用画成错误色的虚线 —— **拦不拦和标不标必须是同一个判据**。

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 运行前检查(后端) | `backend/app/domain/workflows/graph_rules.py` 的 `never_run_nodes` / `never_run_references`(经 `validate_graph`) | `backend/tests/test_workflow_never_run_parity.py` |
| 画布就绪检查与引用虚线(前端) | `frontend/src/features/workflows/analyze.ts` 的 `neverRunNodes` / `neverRunReferences` | `neverRuns.parity.test.ts` |

**为什么不共用一份实现**:画布要在每一次编辑后当场在浏览器里算(角标、就绪清单、虚线的颜色),运行前检查
要覆盖不经过画布的入口(定时任务、智能体、`call_workflow`)。语料里的 `node_types` 是画布认代码字段、
体字段要用的那几格,后端那条测试核对它和真目录对得上。

**建立契约之前**:画布的「未连接到流程」按「从开始节点沿任意连线走得到」判,只是一个黄色提醒;后端
一声不吭。「从主题到完整视频」的「可用的 3D 道具」因此从模板 v8 到 v11 一次都没跑过,布景师拿到的道具
清单永远是空的。引擎判「该不该跑」时有控制边只看控制边 —— 画布那条「走得到」比引擎宽,两边说的
从来不是同一件事。

### `workflow-start-option-cases.json` —— 开始节点的选项参数

「开始节点上哪几个选项参数的值不在选项里。」一个启动参数可以声明一组选项(`param_options`:值、标签、一句说明,
可带前置条件),面板上那一行是下拉;值不在选项里,后端运行前拦,画布就绪检查标 error。

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 运行前检查(后端) | `backend/app/domain/workflows/graph_rules.py` 的 `start_option_violations`(经 `validate_graph`) | `backend/tests/test_workflow_start_option_parity.py` |
| 画布就绪检查(前端) | `frontend/src/features/workflows/analyze.ts` 的 `startOptionViolations` | `startOptions.parity.test.ts` |

**建立契约之前**:分析类模板的「数据来源」是手填的一格,图里先转小写再判「包含 tikhub」—— 打错一个字静默走了
浏览器,画布上什么都不说。语料钉住的几件不显眼的事:空着的不归这条管(必填的由必填说);值按文字比(默认值敲 3
存成数字 3,和选项的值 `"3"` 是同一个)。

### `workflow-output-reference-cases.json` —— 引用了一个节点没有的输出

「这一层图里哪些 `{{节点.输出…}}` 指不到:节点在,而它没有这个输出;或者输出声明了结构(大模型的 JSON Schema),
引用的子字段不在里面。」运行时这种引用插值成空串,下游拿着空值照样跑。后端运行前拦,画布在引用方身上标 error。

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 运行前检查(后端) | `backend/app/domain/workflows/graph_rules.py` 的 `output_reference_problems`(经 `validate_graph`) | `backend/tests/test_workflow_output_reference_parity.py` |
| 画布就绪检查(前端) | `frontend/src/features/workflows/analyze.ts` 的 `outputReferenceProblems` | `outputReferences.parity.test.ts` |

语料钉住的是**哪些不判**:动态输出底下的路径(代码的 output、HTTP 的 json、子工作流 / 插件的整份返回、没给 Schema
的大模型 json —— 键运行时才知道)、没装的插件节点、开始节点(它的输出就是参数,另有一条按这一次的参数判)、Schema
允许别的字段或说不清结构的(anyOf、`additionalProperties: true`)。误报一次,用户就会学会无视这条红。

**建立契约之前**:两侧都只核对「节点在不在」。上游改了输出名、或者手写时拼错一个键,画布全绿、后端照跑,
工作流报成功而那一格是空的。

### `filler-word-cases.json` —— 口癖词表

「哪些词是口头禅,按类别;一个词怎么判。」剪辑台逐字稿面板的「一键去口癖」和口播整理模板交给模型的口头禅候选
用的是同一张表。

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 剪辑台去口癖(前端) | `frontend/src/domain/timeline/transcriptProjection.ts` 的 `FILLER_CATEGORIES` / `fillerCategory` | `fillerWords.parity.test.ts` |
| 口播整理的口头禅候选(后端) | `backend/app/domain/voices/fillers.py` 的 `FILLER_CATEGORIES` / `filler_category` | `backend/tests/test_filler_word_parity.py` |

后端多走一步(只在后端,不在语料里):中文的 token 一个字一个,「就是说」是三个 token,按连续几个拼起来认。

**建立契约之前**:词表只在前端。口播整理给模型的逐字稿只在长停顿附近给词级时间,连续说话被切成一整段时口头禅一个
时间都没有,模型保守地一处都不删 —— 面板上一键能去掉的「嗯」,整理模板删不掉。

### `shared-constants.json` —— 共享常量

几个「两个运行时都要认、而谁也不拥有」的值。不一致时**都不会报错**,只会悄悄错开:发布账号的
登录分区前缀(不一致 = 所有平台的登录态凭空消失)、内嵌视图顶部偏移(不一致 = 露出一条缝,
缝里是 App 自己的顶栏)。测试:`backend/tests/test_shared_constants_parity.py`。

只放**没法单向下发**的常量 —— 能由一侧算好再传过去的(例如面板圆角经 IPC 下发)本来就只有一份。

同一份文件里还有一节 `budgets`:常量说的是「两边必须**相等**」,预算说的是「一边必须**装得下**
另一边」。**跨进程的时间预算属于后者,而它们此前一条都不在契约里** —— 关系只以注释的形式写在
其中一侧(`tools.ts` 那句「590s,压在后端 TURN_TIMEOUT_SECONDS(600s)底下」写得很清楚,
而改 Python 那个 600 的人没有任何理由来读一段 TypeScript 注释)。

错开之后同样没有任何报错,只是等待在两侧的含义悄悄不同:确认卡还亮着而那一轮已判超时;
或者后端还在跑而调用方早已放弃 —— 它占着的独占锁没人知道要等多久,模型却收到一句超时,
于是重试,把同一件事再做一遍。预算写在各自运行时惯用的单位里(TS 用毫秒),契约里标 `unit`,
比较之前换算。要被读到就得是**具名常量的字面量** —— 几处内联的数字因此被提了出来。

### `node-shapes.json` —— 节点形状契约

「一个节点号长什么样。」这一个字符串要在四个地方说的是同一件事:**ComfyUI 工作流文件里的节点号**
(应用表单里那一项的 `node`、「结果取自」的每一项)、**执行图里的节点号**(子图展开出来的 `12:9`)、
**画布上那一层的节点号**(可以是负的 —— 子图输入口就是 `-10`)、以及**助手回复里的 `#12`**。

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 宿主(表单、结果、过桥的标记) | `backend/app/domain/workflow_library.py` 的 `_ANY_NODE` | `backend/tests/test_node_shapes_parity.py`、`test_plugin_workflow_library.py` |
| 桥(标记写进画布前再查一遍,以及 `locate`) | `electron/ipc-contract.cjs` 的 `ANY_NODE` / `CANVAS_NODE` / `NODE_PATH` | `electron/ipc-contract.test.ts` |
| 工作台智能体(`comfy_locate` 的 `node`) | `backend/app/domain/workbench_agent.py` 的 `_NODE_REF` | `backend/tests/test_node_shapes_parity.py` |
| 插件改图(那一步指哪一层) | `plugins/bundled/comfyui/tools/canvas_edit.py` 的 `_PATH` | 同上 |
| 助手回复里的引用 | `frontend/src/features/plugins/workbench/nodeRefs.ts` 的 `NODE_REF` | `nodeRefs.parity.test.ts` |

**为什么不共用一份实现**:四处跑在三种语言、两个进程里 —— 后端进程、Electron 主进程、浏览器,
以及一个**沙盒子进程**(插件)。插件那一侧连 `contracts/` 都读不到(宿主管的是它的 stdio 和几个环境变量),
所以四份正则必然存在,一致性只能靠同一份语料 + 各侧的跑手。

**两次都被抓到的正是「注释型一致性」**:桥那一侧曾经只认顶层节点号,于是维护者那张 18 项的表单里有 6 项
在过桥时被拒(`marks.nodes keys must be top-level node ids`),整条「同步到画布」的链断在那一句话上;
「结果取自」还另有一份只认根图的正则,子图里的保存节点在这一栏里看得见、选它却 422。
两处都写着「和另一侧同一套判据」,而没有人负责去查。

**这份契约还摊出了一处既成的差异**(`divergence`,不改语义):`canvas_path`(`{0,16}`)收裸的 `12`,
`subgraph_path`(`{1,16}`)不收 —— 「更宽」说的是**下界**,深度上限两侧相同(16 段,ADR 0042 §6,
另有 `subgraphs.MAX_DEPTH = 16` 背书)。桥那一侧把它拆成了两条正则(`CANVAS_NODE` + `NODE_PATH`),
合起来覆盖的和 `canvas_path` 一样 —— 所以那不是漏了一条,是分成了两份。

### `shared-constants.json` 的 `protocol` 一节 —— 宿主 ↔ 插件

同一份文件里还有第三节 `protocol`:宿主和它拉起来的**插件子进程**之间那套形状 ——
应用表单的六项上限(几项、几个可选值、几个结果、名字多长、说明多长、一张图几张表单、哪几项是「图级」的)
和 `shared_tables` 的三个名字。

**它不是「谁下发谁」**:宿主先查一遍、插件写进去之前再查一遍,而两边都看不见对方 ——
插件在沙盒里,连 `contracts/` 都读不到。错开时同样一声不吭:多出来的项被宿主**静静截掉**
(而插件已经在界面上说过「这张表单有 24 项」),或者插件替宿主拒掉一项它其实收得下的东西;
`shared_tables` 那三个名字错一个字母,插件就以为宿主收不下共享表,退回逐格写全 —— 36 个工具的清单
撞上 1MB 的线,**整份不收**。

### `mask-cases.json` —— 蒙版形状运算契约

「同一份源图小样、同一组参数(阈值 / 反选 / 扩张 / 羽化)算出来的蒙版,逐字节是哪一串。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 编辑器画布(前端) | `frontend/src/lib/maskPixels.ts` | `maskPixels.parity.test.ts` |
| 素材库「生成蒙版」与智能体那条路(后端) | `backend/app/media/masks.py` | `backend/tests/test_mask_parity.py` |

语料是 5 份 7×5 的源图小样(硬边、正中一个白点、斑驳灰度、彩色、alpha 分界)+ 24 条用例,期望值**逐字节**
给全(每条 70 个十六进制字符 = 35 格),两侧各跑一遍对同一串。彩色那份是照着 Rec.601 那条路挑的:
「眼睛看着亮、按加权算却是暗的」的纯红 / 纯蓝都在里面,还有一条阈值**正好切在纯绿亮度上**
(`0.587 × 255` 两侧算的是同一个双精度数)。

**为什么会漏掉**:两侧的文件头各写了一句「两边该切出同一串字节」,却各测各的 —— 后端半径那一处是
`int(round(radius))`(Python 的半数取偶:`round(0.5) == 0`、`round(2.5) == 2`),前端是 `Math.round`
(半数进位):`feather = 0.5` 时后端一格都不羽化、编辑器羽化了一格;`2.5` 一边 2 格一边 3 格。
`feather` 是**浮点**,三条入口(素材库对话框那个输入格、HTTP schema、MCP 工具签名)都能把 `.5` 送进来,
于是同一组参数出来两张图 —— 而两侧的单元测试当时都是绿的。

**同一个形状的第二处(`grow`)**:`grow_mask` 那一句此前是 `int(radius)`(**向零截断**:`0.5 → 0`、
`2.5 → 2`、`-1.7 → 1`),而契约定的规则是半数进位 —— 今天三条入口都送不进小数(grow 在 HTTP schema
与 MCP 签名上都是 `int`,素材库对话框那格先 `Math.round`),所以这一组是**预先钉住**的:哪天有人把
grow 放成 float,规则与用例都已经在那儿。`grow` 的两条性质与 `feather` 不同,语料的注释里各写着:
①截断**不是**半数取偶,所以每一个 `.5` 都分岔(`feather` 那边只有「奇数 + 0.5」分岔,`1.5 / 3.5` 是对照组;
`grow` 这边 `1.5` 真分岔);②`grow` 带符号,负半径同样偏小(`-1.7` 该是收缩 2 格,截断给 1 格;`-1.5` 才是对照组)。

**取整表现在也是语料的一部分**,而且是两张:`rounding` 那一栏逐条写着 `feather → reach`,两侧的测试都断言
「用小数半径」与「用那一格整数半径」算出同一张图。能分出两种取整的只有「奇数 + 0.5」那几条
(`0.5 / 2.5 / 4.5 / 6.5`),`1.5 / 3.5` 是**对照组** —— 它们以前也是绿的,所以光看它们绿说明不了取整对齐了。
`grow_rounding` 是同一种条目形状的第二张表(`grow → reach`,负数的 `reach` 是窗口半宽、方向看符号),
**只有后端读** —— 前端没有扩张那一步;不并进 `rounding` 是因为前端那份循环按 `feather` 读它,并进去
要么把前端拖进 grow,要么让前端在那几行上**空跑**成一个永远绿的断言。两张表钉的是同一条规则
(`reach = floor(x + 0.5)`),后端测试逐行核过。

**滑动窗口 vs 前缀和**:前端一格一格加减(`blurAxis`),后端前缀和相减(`_box_blur_axis`),每趟都落回
float32。「斑驳」那份小样就是照着这一格挑的:羽化后的值紧贴半整数(甚至正好落在 `.5` 上)。两侧算出的
字节与语料逐格相同,也就说明这两条路在 float32 落回上同值。

**`grow ≠ 0` 的用例只有后端跑**:编辑器没有扩张 / 收缩那一步(素材库对话框把 grow 交给后端算)。
两侧的测试都写着「跑不动的用例**正好**是 grow ≠ 0 那一组」—— 新加一条前端跑不了的用例会红,而不是静默少跑。

## 怎么保证"该进契约的都进了"

`backend/tests/test_cross_runtime_claims_name_a_contract.py`:凡是源码里写下
「Mirrors the frontend」「必须与…一致」「锁步一致」这类话的地方,**必须在同一段注释里点名
`contracts/xxx.json`**,否则 CI 红。

它挡不住有人换一个全新说法 —— 这是一条措辞扫描,不是定理。但七处历史证据里,作者**每一次
都自己写下了这句话**,只是没人负责去查。它把"得有人记得"降级成了"得有人换个词"。

**它此前在插件那一侧是瞎的,而原因不是措辞**:扫描根里没有 `plugins/` ——
于是宿主 `workflow_library._ANY_NODE` 那句「跨语言共用不了一份正则」在范围内、插件
`canvas_edit._PATH` 说的同一件事在范围外。现在 `plugins/bundled` 在 `ROOTS` 里了。
「哪几个词算承认了有两份」也补了一个**跨语言** —— 插件与宿主说这件事时用的就是它。

它仍然挡不住的那一半(说清楚,免得当成万能):插件那边有一句自己发明的说法
「和这里是同一套判据,两侧的跑手读同一份语料」,表里没有「同一套判据」这个词。
把它加进去会**同时**扫到四处**不是**这个意思的地方(`generationCapabilities.ts` 那句
「和后端 validate_text_inputs 是同一套判据」是同类的真话、而另外三处只是局部复用),
于是要么建一堆不属于这一轮的契约,要么把豁免名单撑大 —— 两者都比「这次不收」更糟。
**下一个改判据的人仍然可能绕过它**,这一点没有变。

## 改语义的正确顺序

1. **先改 `contracts/*.json`**
2. 跑两侧测试,**看着它们一起红**
3. 再改两侧实现,直到一起绿

反过来做——先改实现、再补语料——就把语料降级成了实现的复读机,它将不再能防住任何东西。

## 什么该进契约,什么不该

**该进**:多个实现必须逐字一致、且不一致会被用户看见的语义。

**不该进**:只有一份实现的东西(直接单测就好);以及**刻意允许两侧不同**的东西——
典型是**调色**:导出走 ffmpeg 的 `eq`/`curves`/`lut3d`,预览是 CSS/canvas 近似。
这是有意的取舍而非缺陷(见 `frontend/src/features/editor/monitorFilters.ts` 的说明与
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) 的「预览与导出」一节),把它写进契约只会逼两边
互相迁就到都变差。

## 契约钉不住什么:同一个实现,两个调用方

契约管的是**两份实现**。它管不了**一份实现、两个调用方各喂一份不同的输入**——而那类漂移
更难发现:两份实现至少代码长得不一样,看得见;两个调用点长得几乎一样,连 diff 都看不出问题。

已经发生过一次。`/api/assets/{id}/transcript` 的响应要转成可投影的段落,逐字稿面板和「生成
字幕」各写了一份映射,后者把 `tokens` 写死成 `[]`。同一份稿子:逐字稿页 **156 句**,字幕轨
**几条一分钟的巨块**——因为没有词级时间戳时投影会退到按标点猜句子的兜底路径,而那条兜底
路径当时还认不了中文句号。用户看到的两个数字来自同一个接口、同一个投影函数。

**判据**:凡是「用户在两个地方看到同一份数据」,先问一句——**中间那层映射有几份?**

**修法不是加一条比较两者的测试**(那需要先容忍两份存在),而是让第二份不存在:一个导出的
映射函数,加一条结构性测试钉住"只有它"。见
`frontend/src/domain/timeline/transcriptProjection.singleSource.test.ts`——它扫源码,凡是调
`projectTranscript(` 的文件都必须从 `transcriptSegmentsFromApi` 拿段落,并且别处不得再出现
手写的 `tokens:` 映射。和上面那条措辞扫描同一个性质:挡不住有人换个全新写法,但挡得住这次
这种复制粘贴,而它把"得有人记得"降级成了"得有人绕开"。
