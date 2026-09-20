# Changelog

This file records user-visible release highlights. GitHub Releases contains the complete generated
commit list and downloadable artifacts.

## [1.4.1] - 2026-09-21

### 智能体在你自己的 Blender 里建模

- 看场景结构、看视口画面、跑建模代码,再把结果收回 Mosael 的 3D 场景。
- **它看得见自己改出来的东西**:`view_scene` 与工具结果里的图片让它改完就能自己核对,而不是闭着眼睛一路改下去 —— 建模这件事没有"看一眼"就没法收敛。
- Blender 相关的能力是**插件**,不是内核的一部分:权限那一侧不认识 Blender 是什么,每张确认卡自己声明属于哪一档,确认卡的文案也和内核分开。
- 发送到 Blender 的 GLB 改由后端生成,所以智能体也能发送场景,而不是只有你在界面上点才行。

### 代码执行分成沙箱与不隔离两条路

- 沙箱里跑(算个数、处理一段文本)和**不隔离地在你电脑上跑**(`run_host_code`:装东西、动文件)是**两档权限**。对前者放开不会连带放开后者 —— 一个能力可以自成一档,谁和谁分开由那几张卡自己说了算。

### 3D 白模进工作流

- 新增「搭建 3D 白模场景」「渲染白模参考」两个节点,智能体同样能用;白模渲染在后端跑,所以工作流可以拿一个 3D 场景当生成参考。
- 官方模板「从主题到完整视频」升到 v6:三视图、场景设定图、3D 白模、首尾帧与运镜参考。
- 3D 场景页的属性栏和智能体栏可拖宽,和剪辑页同一套拖拉条。3D 几何、插值与光照进了契约,三份实现跑同一份语料。

### 工作流:引用即依赖,付过钱的生成不会被本地超时掐掉

- 生成节点能指定用哪一组素材,参考清单也能**整组**接进来,而不是一个个连线。
- 一个节点 `{{…}}` 引到谁,就等谁落定再开始 —— 此前引用和依赖是两件要各自声明的事,漏一个就读到空值。
- **付过钱的远端生成只在远端真的完成、或你自己取消时才结束**(ADR-0019)。循环里一项失败之后不再开始新的付费迭代,而是把失败全部报出来。
- 执行历史不再因为一条失败原因而整片消失;视频编码失败时报的是真正出问题的那一行。

### 被时间线引用的素材可以直接删了

- 引用它的片段**留在原位**变成「素材已删除」占位:位置、时长、变换、关键帧一样不动。时间线上是斜纹警示 + 断链图标,监视器上是一块写着「素材已删除」的红屏,右栏说清下一步该怎么办。
- **导出会明确拒绝**并点名是哪个素材,而不是静默地少一段 —— 成片短了一截,等发出去才发现是最坏的结果。
- 此前接口直接拒绝:「素材正在时间线中使用,请先从时间线移除」。而你手上往往有十几条序列,想删一个素材得先自己一条条翻出每一段。

### 智能体能删素材和项目

- 走新的「永久删除」权限档:一次一批(上限 20 —— 不是性能上限,是**读得完**的上限),卡上写清一共几个、都叫什么、连带影响多少个片段。删项目会说明里面的素材不会被删、会回到工作区。
- **这一档永远不会被自动放行**:删除没有可枚举的放行判据,「帮我清理一下」不该变成一次无人值守的删除。

### 模型的上限不再靠猜

- 内置一张**查证过的**上限表(60+ 条,覆盖 OpenAI / Anthropic / DeepSeek / Gemini / Grok / Kimi / GLM / 通义 / MiniMax / 豆包,以及常挂在中转或本机后面的开源权重)。供应商的 `/models` 不报上限时用它,而不是一律按 128K 猜。
- 模型设置里新增「最大输出 Token」,并把「模型上限」和「不填时实际发多少」分开显示 —— 这两个数经常不一样。
- 修复「模型已用完本轮输出额度」:思考 token 和正文共用这份额度,而此前对 1M 窗口的模型只给 16,384,一轮思考还没说完就被截断。

### 更快

- 页面改成按需加载,**主包从 4.20 MB 降到 0.28 MB**:打开一次素材库,不再先解析工作流的图编辑器、笔记的富文本内核、代码高亮和图表。
- 跑过的数据库迁移开始记账,启动不再每次从头跑一遍。

### 安全

- 计价规则的**读**也要过工作区的门 —— 此前别的工作区的计价规则能被读到。

### 其它修复

- 剪辑台:「在此切一刀」「存下这一帧」并进时间线工具栏,监视器还回一整块高度;工具栏那把剪刀不选中片段也能用(切播放头下的那一段)。
- 智能体:删掉的素材在对话里收成一行,生成出来的素材现在真的显示了;引用胶囊在消息气泡里看得见了(此前和气泡同色);「引用文档」按钮不再比同排的暗一截。
- 素材缓存失效改用最短前缀:在剪辑页导入一段素材,首页和 AI 工作台的列表会跟着刷新,不再停在旧数据上。
- 修复 Google 免费翻译 429;工作流的配置字段按引擎能力启用;对话连接下拉不再读档案行上不存在的字段。
- 停靠栏之间只有分割线、没有缝,拖柄在每一页都压在线上;描边按钮不再长成输入框,控件高度只有一个出处。

## [1.4.0] - 2026-09-16

### 视频译配：一条工作流从原片到译配成片

- 新增官方工作流「视频译配 · 字幕与配音」：逐句转写 → 逐句翻译 → 按**原时间码**铺译文字幕 → 逐条配音并变速压回原段落长度 → 导出。
- **逐句翻译，不是整篇翻译**。配音要对得上画面，每一句就必须知道自己是第几秒到第几秒，而那个时间码只存在于原始段落里。整篇丢给翻译再切回句子，切点不可能和原来一致（译文的句数本来就和原文不一样），于是每句都往后错一点，越到后面错得越多。
- **靠变速塞回原长度，不是靠裁剪**。同一句话译成另一种语言长度天然对不上；裁掉尾巴等于把话说一半，留空则对不上口型。变速改的是片段自己的倍速（渲染时 atempo），无损、可撤销、事后还能在检查器里逐条微调。
- 工作流新增「生成字幕」和「字幕配音」两种节点，画布上可以单独使用。

### 一个任务只响一次

- 一次译配此前会弹十几条"完成"：每句配音、导出后顺手排的预览代理，都成了独立的顶层任务，各自弹一条，还会发系统通知。现在任务执行时建出来的任务都归到它名下，任务中心只报这一次；逐句的合成在任务详情里看得到，取消字幕配音也会一并停掉它们。
- 预览代理成功时不再提示，失败才说。
- 做完只由任务中心说一次。配音面板、字幕配音不再各自再弹一条。
- 每种任务叫什么、要不要提示、做完刷新哪些数据、点"前往"去哪一页，都改由后端统一声明。此前前端几张表对不上，有些任务显示成笼统的"任务"。

### 修复：工作流的语音节点只剩一个引擎

- 「引擎」下拉里除了「克隆音色」什么都没有，音色跟着也是空的。原因是「这个引擎现在能不能用」只长在克隆那一条上，其余引擎压根没回答过这个问题，而只列可用引擎的那个下拉按它过滤。现在每个引擎都说得出：不要 Key 的（Edge）随时能用，要 Key 的看你配没配那条连接。

### 插件节点的下拉终于有东西可选

- 插件节点（画布上「插件」那一组）的「用哪个连接」「用哪个工具」此前在前端按节点类型查表，而插件节点的类型是装了插件之后才有的——那张表永远覆盖不到它，下拉里一个选项都没有。现在选项从哪来由后端随节点声明一起发下来，发布账号、可调用工作流、对话连接与模型同理。
- 模型名这类字段可以在下拉之外手填（新模型上线往往早于目录更新），这一条现在也由声明说了算。
- 「调用工作流」的清单里不再列出它自己（自调一定成环）。

### 英文界面里不再冒出中文

- **从模板建的工作流**：画布上那一排节点名此前永远是中文，现在跟着界面语言走（图建好之后就是你的了，随时能改名）。官网上可下载的模板文件也分中英两份。
- **跑失败时那句话**：失败原因此前是写死的中文，现在按你界面的语言显示；历史任务也跟着变，因为任务记的是「哪一条原因 + 哪几个数据」，而不是当时那句话。
- **模板卡片**的名字、介绍、步骤、前置条件此前在应用、官网、后端各写一份，现在只有一份。

### 插件可以自己处理多语言

- 清单里任何给人看的文字都能写成 `{"zh": "…", "en": "…"}`（此前就支持），现在**按主语言匹配**：写 `en-US` 也认得出是英文；还能用 `default_locale` 声明你的原文是哪种语言，挑不到时先退到它。
- 工具**跑出来**的文字（摘要、失败原因）由插件自己定语言：每次调用都会告诉它读的人在用哪种语言（进程插件读请求体里的 `locale` 或 `MOSAEL_LOCALE`，MCP·http 读 `Accept-Language`）。

### 工作流节点的下拉不再是英文代号

- 「原声」下拉里此前摆着 `duck` / `mute` / `keep` / `separate`，中文界面里也是这样。现在每一项都有中英文名字，值仍是英文的（存进配置、执行时认的是它）。HTTP 方法这类术语照原样显示。

### 含插件节点的工作流，确认卡按最高一档开

- 插件节点跑的是第三方的代码、发第三方的请求，但它的类型是运行时才知道的，此前不在「会伸到应用外面」那张表里——一张含插件节点的图只按「可能花钱」开卡。现在默认按最高一档，卡上也会点名；折叠进子图同样躲不掉。

### 译配选「分离原声」不再整段静音

- 选了 `separate`（丢人声、留背景音）时，原片那一段此前在成片里没声音，画面也可能丢。现在画面留在原处、原片自己的声音关掉，背景音对齐放到一条音频轨上。和剪辑台的「分离音频」是同一个操作，可以撤销。
- 「原声怎么办」（压低 / 静音 / 保持 / 只去掉人声）此前只有工作流能选；剪辑台的字幕配音和智能体配音现在也能选，确认卡上会写明原声会怎样。

### 字幕配音也能在对话里让智能体做

- 让智能体「把这条时间线的字幕配上音」，它会开一张确认卡再动手。
- 卡上写清**这一步影响几条字幕**、会不会压回原长度、原声动不动 —— 它是花钱的动作，而「整条字幕轨」可能是 3 条也可能是 300 条。条数由执行时的同一个函数数出来，卡上说的和待会儿真做的不会分叉。

### 3D 场景卡片有了缩略图

- 从场景数据直出的俯视平面：每个物体按自己的颜色画它压在地面那块，圆柱和球画成椭圆，相机的运镜画成一条虚线。
- 没走截图那条路 —— 截图会停在「上次保存那一刻」和数据脱节，而且列表页给每张卡起一个 WebGL 上下文，五张卡就是五个。

### 目录认不出的模型，参数可以自己写下来

- 内置那张表只装我们查证过的模型。手填的别名（`gpt-image-2-client` 就是 gpt-image-2）、经另一条中转配的同一个模型，此前在生成界面上**一个参数都没有**，而你没有任何地方可以说明白。现在可以给这条连接写一份参数组，在模型行上按能力（image / video）分别指过去。
- **不按模型名跨供应商猜**。实测同一个 `qwen-image-edit`：阿里自家只收一张参考图、没有尺寸；经 evolink 则收 14 张还能选尺寸 —— 猜过去的参数会被端点当场拒掉。所以要么目录认得，要么你在这里说。
- 写一份参数组是「参数按什么来」那一格底下的一个动作，就地换掉同一个对话框的主体；保存后新建的那份**已经选中**。此前是「管理参数组」链接 → 参数组库弹窗 → 编辑器弹窗三层叠着，而且建完还得回来再选一次。
- 表单由后端的字段描述驱动：勾出哪几个旋钮、每个旋钮有哪几档、一开始停在哪一档、这个端点的硬限制和请求形状上的怪脾气，四组各自说得出自己管什么。保存时只校验形状，校验不了「这个端点真的支持吗」—— 那一条只有端点自己知道，界面上照直说。

### 认不出参数时不再沉默

- 一个模型「真的没有参数」和「我们不认识它」是两回事，而此前界面把两者显示成同一个样子：什么都不摆。
- 现在每条通道说得出**自己会发哪几项**（请求是我们自己构造的，这一点不需要查证），于是认不出模型时界面会说：这条通道发得出 `size` · `num_images`，但没人验证过这个模型收哪些取值 —— 指一个「和它一样」的模型就都有了。
- 同时拆掉了界面凭空造值那条路：没有可选值时不再自己编出 `1024x1024`、`5 秒` 这种清单。编出来的值发出去会被端点拒掉，而用户以为那是我们查证过的。

### 分离人声与背景音

- 译配要替换的是说话声，而原片里说话声和背景音乐混在同一条轨上 —— 整轨静音会把音乐一起带走。现在可以把一段音频或视频**拆成人声和背景音两份新素材**，原素材一个字节不动。
- 入口在素材库（音频、视频素材的菜单）、剪辑台片段右键、工作流的「人声分离」节点，也可以让智能体做（确认卡）。同一个能力，一份实现。
- 配音节点的「原声怎么办」多了「分离」一档：装了分离引擎就只静音人声、保住背景音乐，没装就退回整轨静音，不让一条本来能跑完的流程失败。官方译配模板用的就是这一档。
- 引擎在本机跑（Demucs），装在自己的独立环境里 —— 和转写共用一个环境时两边的 torch 版本会打架。装是设置里显式的一步：几个 GB、几分钟到几十分钟，不该藏在第一次点「分离」后面。一段长素材在 CPU 上要跑十几分钟，所以分离总是排成任务，有进度、能取消、失败说得出原因。

### 降噪

- 音频、视频素材可以**降噪**，产出一份新素材，原素材不动；视频保留画面，只换声音。入口在素材库、剪辑台片段右键、工作流的「降噪」节点，也可以让智能体做（确认卡）。
- 内置引擎不用装任何东西，去掉空调、风扇、电流声这类持续的底噪，音乐不受影响。它**先量出这段音频的噪声有多大再下手** —— 写死一个阈值的话，噪声比它响就一点都降不动（实测 −31 dB 的白噪声原样留着），比它轻就把说话声当噪声削掉。三档强度实测把停顿里的噪声压低约 6 / 12 / 20 dB，说话段响度不变。
- 以说话为主的录音可以选两个开源语音模型：**DeepFilterNet**（效果最好，键盘、碗碟、嘈杂人声这类一阵一阵的噪声实测压低约 34 dB，说话声失真最小；在「设置 → 本机引擎 → 降噪」下载一次，约 30 MB，按固定 SHA-256 校验，对不上就不装）和 **RNNoise**（随应用带着，不用装，轻量些）。它们用的是官方发布的独立程序和 ffmpeg 自带的滤镜，不需要 torch —— DeepFilterNet 的 Python 包和新版 torchaudio 不兼容，实测装不上。
- 这两个语音模型都会把音乐当成噪声去掉，所以默认从不选它们；对话框、设置页和确认卡上都会标出「会去掉音乐」。
- 只想要人声、其余全部不要，用「分离人声与背景音」取人声那一份 —— 那不算降噪，不在降噪的选项里。
- 顺带修正：人声分离取声音时先降成了 16 kHz 单声道（借的是转写那条路），拆出来的背景音再进成片时音质已经没了。分离和降噪现在都保留原采样率和声道。

### 三套官方工作流

- **从主题到完整视频：口播对上画面了。** 此前每镜的口播接在上一段口播后面，而口播长短不一 —— 第 n 段落在前 n−1 段口播时长之和上，越往后和画面错得越多。现在放在这一镜画面实际开始的那一秒；比镜头长时加速塞进去（最多 1.5 倍，再快就听不清），分镜提示词也按语速给每镜口播定了字数上限。
- **口播与访谈智能整理：先降噪。** 底噪同时拖累转写（整理方案是照着逐字稿切的）和成片。用内置降噪，不用装、不动背景音乐；降噪只换声音，按逐字稿切的每一刀仍落在原处。
- **视频译配：说清原声怎么处理的。** 选了「拆掉人声、保留背景音乐」却没装人声分离引擎时，流程会退回整轨静音 —— 背景音乐也跟着没了。现在完成通知和输出里会写明实际做了什么，以及装好引擎后重跑可以保住音乐。模板简介里「原声只做闪避」、「翻译不需要对话模型」这两句过时的说法一并改正。
- **从主题到完整视频：各镜同时生成，并给口播配上字幕。** 视频生成是整条流程最慢的一步，此前逐镜排队；现在最多 3 镜同时生成（画面和口播一起），再按镜头顺序接上时间线。字幕跟着口播实际落下的起止；整片没有口播时不出字幕、也不让流程失败。
- 「遍历循环」可以设**同时跑几项**（1–4），结果仍按原顺序；不写输出时每项结果带着它自己那一项。「生成字幕」可以按字段路径从任意对象列表取起止和文本，并可在没有可用段落时跳过。
- **修复：挂在条件分支上的节点，另有一条数据连线时会在分支不成立时照跑。** 数据连线只该决定取值。整片生成里没有口播的那一镜会因此拿着空素材去接口播，整条流程失败 —— 上一版口播对齐的改动正好踩中。
- **语音节点只有一格音色。** 「语音合成」「字幕配音」此前把音色存成两个字段、按引擎显示其一,两个字段一前一后 —— 换引擎时音色那一格上下跳,看起来像两个音色框。现在是「引擎 → 音色」两格,音色清单跟着引擎变(克隆 → 配音库,其余 → 那个引擎的音色);火山音色的资源号由后端自己查。节点字段的现查清单改由后端声明来源(`options_from`),编辑器不再为某个节点写特例。已添加的旧工作流需要在语音节点上重选一次音色。
- 「把素材接到时间线」节点可以指定**放在第几秒**，也可以给一个**最长时长**（太长就加速塞进去）；「字幕配音」节点多输出原声的实际处理方式。

### 东西放在找它的人会去找的地方

- **设置页按用途重新分组**：个人与工作区 · AI 供应商（只放云端连接）· 智能体 · 本机引擎（转写 / 配音与音色 / 人声分离 / 安装源）· 连接与系统。人声分离不再挂在「转写模型」下面；pip 镜像有了自己的一页 —— 它被转写、克隆、分离三处共用，此前却只出现在声音克隆的表单里；出站代理和失败重试合成「网络」一页。
- **AI Studio 多了「音频」**：念一段文字、做一期播客都在这里，产物进素材库，下方列出最近几条可以就地试听。此前它们挤在剪辑台的配音栏里，而产物根本不碰时间线。
- **剪辑台的「配音」页只管这条时间线**：给字幕配音的表单搬到这里（原来藏在字幕页的一个弹层里），范围跟着时间线上的选中走；字幕页每一条旁边的配音按钮变成「选中它、切过来」。选引擎、选声音在两处是同一套控件 —— 此前各写一份，一边能换克隆引擎、调语速，另一边不能。
- **⌘K 能跳到所有页面**：命令面板原先自己抄了一份页面清单，漏了笔记、3D 场景、画板和管理控制台。现在侧栏和命令面板读同一份声明。
- 开放注册和邀请码在管理控制台里；「最后一个管理员不能收回」的说明回到成员列表下面，开关为什么是灰的有了解释。

### 智能体问你的时候会等着

- 岔路口上智能体用选择卡把选项摊开时，这一轮现在**停在那儿等你挑**，你的答案作为工具结果回到它提问的那个位置 —— 不再是问完自己接着跑、等你选完再靠一条「我选好了…」把它叫醒。
- 等待有上限；到点还没答不算失败，它会按自己的判断继续，而你之后作答，答案仍然会送到。
- 顺带修掉那条「我没写过却出现在输入框上方队列里」的消息：它是选择卡的回执，此前撞上智能体正忙就排进了队列。

### 修复

- **官方译配模板翻译到第一句就整条失败**。工作流的翻译节点一句一次调用、且不重试，同一个 429 在批量翻译里会退避重试、在这里当场失败。新增整轨一次翻完的「批量翻译」节点（并发、共用一条会重试的连接、顺序不变），模板里的循环拿掉；模板改用你自己配的 AI 引擎 —— 实测免费的 Google 端点对这台机器的出口 IP（直连与代理）都是整段封禁。翻译节点也补上了选连接、选模型两格。
- **译配完原声还在**。闪避把原声压到约 −10 dB，那是给「旁白盖在环境音上」的档位；译配是另一种语言的说话声替换说话声，压低的结果是观众同时听见两个人说话。配音节点新增「原声怎么办」：压低 / 静音 / 保留 / 分离。
- **配音压不住原声，成片里两个人同时说话**。设闪避时只挑音频轨，而原片整段在视频轨上、音频轨是空的 —— 标记落在一条没有片段的空轨上。再往下一层，基底视频轨的声音根本没有闪避通路。实测原声在成片里的增益 0.996（−0.03 dB），修后 0.304（−10.35 dB）。
- **生成成功了，生成历史里却看不见它**。没点名会话时现开一条却不设归属，而列表按「我的或共享的」过滤 —— NULL 谁都看不见，包括创建它的人。图不丢，丢的是那条带着提示词、参数和花费的记录。五个入口里四个中招。
- **导出写的那个文件是中转，不是成品**，成功／失败／取消三种结局都没清掉，攒在 `~/.mosael/exports` 里。
- **客户端说「我不知道这是什么」时，一切图片被当成了视频**。`application/octet-stream` 恰恰是命令行、扩展、机器人上传时最常发的那一个，而 iPhone 照片默认就是 HEIC。
- **智能体轨迹面板会偶尔整轮空白**：流重置排在工作线程第二行，而 POST 在线程起来后就返回，界面在那个窗口里连上就拿到 done=true。
- **上下文占用条从来就不动** —— 消息那一项恒为 0。
- 笔记编辑器：代码块里写 Markdown 会把自己拆掉、表格里的竖线让那一格裂成两格、粘进来的 Markdown 不认、占位符压在代码块上；代码块的间距、配色和语言选择器重做。
- 画板：每次自动保存都白重建一次画布；离开视野的视频卸掉 `<video>`。
- 链接导入：失败时说得出是哪一条、为什么；已经挑了登录身份的人不再被劝去挑一个。
- 浏览器节点「等待超时」现在说清等的什么、等了多久、当时停在哪一页，并带上那一刻的页面。
- 磨玻璃开启后页面级表面的分隔线随背景漂移，紫色背景上只剩 1.01 对比度。
- 发布构建的第一次 codesign 撞上包刚铺完就整个红掉，且每次都停在同一个二进制上，看着像那个文件坏了。
- **智能体正忙时打的字排在输入框上方，那一条却和输入框不一样宽**；窗口一窄（分屏、侧栏）更明显。
- 确认卡右上角的权限徽标被长摘要挤成一列竖排 —— 而那两个字是你点「允许」之前唯一会看的东西。
- 停用一条连接之后，那一行右侧的图标比别的行错开一格。
- 展开连接时「正在加载模型」是一条贴边的文字，现在是三条占位行。
- 模型设置弹窗此前四段平级、同一件事说两遍；双能力模型的「生成」组头也说了两遍。

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
