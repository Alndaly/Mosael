# MiniMax H3 适配器

## 用途

把表演母版编译成 MiniMax H3 可执行提示词。H3 的提示词包装与 Seedance 不同；先选模式，再写对应字段。

## 当前约束快照

- 成片 4–15 秒、24 FPS、原生立体声音频。
- 常用画幅包括 21:9、16:9、4:3、1:1、3:4、9:16；首尾帧模式通常跟随输入图比例。
- 提示词不超过 7,000 字符。
- 简单首尾帧入口使用 0–2 张图片。
- 全参考入口最多 9 张图片、3 个视频、3 个音频、合计 12 个文件；视频和音频各自受单段与总时长限制。

这些是当前工作流快照。若用户准备实际提交，且当前 H3 界面显示不同限制，以界面为准。

## 选择模式

- 无素材：T2VA。
- 一张图定义开头：I2VA。
- 两张图分别定义开头和结尾：FL2VA，默认连续镜头完成中间变化。
- 一张图只定义结尾：L2VA。
- 混合图片、视频、音频，或需要编辑/续写/分离素材职责：全参考模式。

每个输入素材只能承担清晰职责：身份/外观、场景、产品、风格、动作、节奏、镜头、源视频编辑、声音或音乐。不得把所有素材写成泛化灵感。

## 所有语言共用的格式规则

用户选择中文或英文，只决定固定字段内的正文语言，不改变 H3 的格式。以下内容在中文提示词中也必须原样保留：

- 英文字段名及其顺序；
- `<Picture N>`、`<Subject N>`、`<Video N>`、`<Audio N>`；
- `[Shot N]` 与后续镜头的 `MM:SS.mmm` 时间格式；
- `(S1)`、`(S2)` 与 `<d>[Language] ...</d>`；
- I2VA、FL2VA、L2VA 的英文帧对齐句；
- Ref2VA 的英文任务类型和 retention marker。

不要因为用户要求中文而输出 `【参考素材说明】`、`【核心设定】`、`【画面过程】`、`【不要出现】` 等自定义包装。禁止项应自然写进主描述中，不能添加 H3 不支持的独立 negative prompt 字段。

## T2VA / I2VA / FL2VA / L2VA 输出

中文和英文成品都严格使用以下字段顺序：

```text
integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...
```

I2VA 在最前面添加：

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
```

FL2VA 在最前面添加，并把 `N` 与 `S.SS` 替换为实际末镜头和总时长：

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.
```

L2VA 在最前面添加：

```text
How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.
```

对齐句之后留一个空行。T2VA 没有对齐句。

若用户选择中文，在 `integrated_multimodal_description`、`overall_soundscape` 和 `non_diegetic_music` 的冒号后写中文正文；字段名和顺序不翻译。单条提示词放在一个 `text` 代码块中，代码块内不加“最终提示词”等标题、解释、JSON、表格或额外字段。

中文 T2VA 结构示例：

```text
integrated_multimodal_description: [Shot 1] 写实电影风格，中景建立人物、环境与初始动作……

overall_soundscape: 房间底噪、自然呼吸和衣料摩擦保持清晰……

non_diegetic_music: N/A
```

中文 I2VA、FL2VA、L2VA 同样先放对应的英文对齐句，空一行后再放三个固定字段。

## 全参考模式

无论正文语言，严格按以下顺序输出：

```text
subject_definitions:
...

summary:
...

retention_analysis:
...

detailed_description:
[Shot 1] ...

overall_soundscape:
...

non_diegetic_music:
...
```

标签含义：

- `<Subject N>`：需要跨镜头追踪的人、物、环境、服装、风格或动作主体。
- `<Picture N>`：具体首帧、关键帧、尾帧、构图或分镜锚点。
- `<Video N>`：被编辑/续写的源视频，或时间、镜头和运动参考。
- `<Audio N>`：复制或参考的独立音频、源视频音频。

同一标签全程保持同一含义。中文输出时可以在冒号和固定 marker 之后使用中文解释，但六个字段名、方括号任务类型和 marker 不翻译。`retention_analysis` 对可见内容只使用 `fully_preserved`、`partially_preserved`、`attribute_transfer`、`weak_reference`；音频只使用 `fully_copy`、`partially_copy`、`reference`、`weak_reference`。

## 镜头和时间

- 第一镜写 `[Shot 1]`，不加起始时间。
- 后续镜头写 `[Shot N] At MM:SS.mmm, the camera cuts to...`，时间严格递增。
- 只有视点、状态、空间或时间发生实质变化时才切镜。
- 单镜头用连续的动作阶段表达活人感，不用伪装成切镜的时间标题。
- FL2VA 默认用一个连续镜头从首帧可信地抵达尾帧；除非用户明确要求，不增加中间切镜。
- 相机指令写清运动类型；只有确有意义时再补幅度与速度。

## 活人感压缩策略

H3 最长 15 秒，不能把 30 秒 Seedance 表演逐句缩短后硬塞进去。压缩顺序：

1. 保留人物目标、触发和结尾关系变化。
2. 保留一个保护动作作为表演基准。
3. 保留一次理解延迟、一次最关键的非自愿泄露和一次选择。
4. 保留爆发后的回收或余波。
5. 删除重复微动作、第二次情绪升级、装饰性运镜和不影响因果的环境描述。

一段 15 秒关系戏通常只承载一次完整转折。多轮揭示应拆成多个生成段，而不是牺牲聆听和反应时间。

编译节奏时遵守 SKILL.md 的“默认实时动作，限制慢动作偏向”。上述理解延迟只在剧情确有需要时保留，轻松人像不强加完整反应链。未明确要求慢动作时，在主描述中简洁写明“正常实时动作，动作自然完成后允许停留”，并同步清理时间轴中的过度减速和逐项等待指令；不新增字段或独立负面提示词。保持用户指定切点，用自然停留承接余下时间，不将少量动作均匀拉长到整段。

## 对白与声音

- 为每个说话角色建立稳定的 `(S1)`、`(S2)`。
- 只有实际说出的文字放进 `<d>[Language] exact original words</d>`，不得擅改原文。
- 画外音写清 `says in an off-screen voiceover`，并说明画面中人物嘴唇闭合。
- 环境、动作与非语言人声放在 `overall_soundscape`。
- 观众听见、场内人物听不见的配乐放在 `non_diegetic_music`；无配乐时写 `N/A`。
- 对白、现场音乐和画内播放声属于镜头内声音，不要重复写进非叙事性配乐。

## 检查

- 模式、时长、画幅和素材数量兼容。
- 首帧/尾帧标签与实际镜头和时间对齐。
- 人物身份、服装、道具、声音 ID 和素材职责没有串线。
- 对白能在镜头内完成，且仍留出聆听、理解和余波。
- 三段或六段字段顺序正确，声音层没有错放。
- 中文提示词只翻译字段内正文，没有翻译或替换字段名、标签、对齐句、任务类型、retention marker 与镜头格式。
- 最终单条提示词只有一个 `text` 代码块，内部没有解释、表格、自定义中文章节或独立负面提示词字段。
- 最终字符数不超过 7,000。
