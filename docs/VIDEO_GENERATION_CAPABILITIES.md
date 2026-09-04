# 视频生成引擎能力矩阵

> 核查日期：2026-09-04。本文区分「模型原生能力」与「Mosael 已接通能力」；只有后者能进入
> `catalog.py` 并出现在 UI、工作流和智能体的参数描述符中。

## 判定原则

视频模型的产品名不能直接当作接口契约。Mosael 按 `(provider, model, kind)` 精确选择描述符，
因为同一模型经原厂和聚合网关接入时，模型 id、输入字段、素材顺序和限制可能完全不同：

- 原厂 Seedance 2.0 在一个模型 id 上用素材角色区分文生、首尾帧和参考生成；
- Evolink 把相同能力拆成文生、图生、全能参考三个模型 id，标准版和 Fast 共六条路；
- 描述符是 UI、MCP/智能体和提交校验的共同事实源，Adapter 只负责把已通过校验的语义翻译成厂商协议；
- 未经官方文档或真机确认的能力不向 UI 暴露。上游模型会某件事，不代表当前接入协议已经能提交它。

证据等级：**实跑**表示已用真实接口跑到任务终态；**官方文档**表示已核对厂商 API 文档但尚未实跑；
**网关文档**表示能力以聚合平台公开协议为准，不能用上游原厂文档替代。

## 已接通能力

| 接入 / 模型族 | Mosael 已接通模式 | 素材角色与关键约束 | 时长 / 输出 | 证据 |
| --- | --- | --- | --- | --- |
| 火山方舟 Seedance 2.0 / Fast / Mini | 文生、首帧、首尾帧、全能参考 | 首/尾帧各 1；参考图 9、视频 3、音频 3；首尾帧组与参考组互斥；参考音频不能单独提交 | 4–15 秒；标准版 480p–4K，Fast/Mini 480p–720p；可生成同步音频 | 标准版限制实跑，型号差异见官方文档 |
| Evolink Seedance 2.0 / Fast | 文生、首帧、首尾帧、全能参考 | 六个精确模型 id；图生模型 1 图=首帧、2 图=首尾帧；参考模型支持 9 图、3 视频、3 音频，音频不能单独提交 | 4–15 秒；标准版 480p/720p/1080p，Fast 480p/720p；默认生成音频 | 网关文档 |
| Evolink Seedance 2.5 | 文生、首帧/首尾帧、全能参考、视频编辑、视频续写 | 五个模型 id；参考模式 30 图、10 视频、10 音频；编辑/续写要求被处理视频排在数组首位 | 生成 4–30 秒或自动；编辑跟随输入；480p/720p/1080p | 网关文档 |
| 火山方舟 / Evolink Seedance 1.x | 文生、首帧；部分型号首尾帧 | 方舟 1.0 只接首帧；Evolink 1.5 可按两图表达首尾帧 | 方舟 1.0 为 2–12 秒，1.5 为 4–12 秒 | 实跑 + 官方/网关文档 |
| MiniMax H3 | 文生、首帧、首尾帧、全能参考 | 首/尾帧各 1；参考图 9、视频 3、音频 3；首尾帧与参考组互斥 | 4–15 秒任意整数；768P/2K | 实跑 |
| 阿里云 Wan 2.7 | 文生、首帧、首尾帧、视频续写、参考生成、视频编辑 | I2V 支持首帧/尾帧/首片段/驱动音频的白名单组合；R2V 支持参考图/视频与辅助首帧；编辑要求 1 个源视频 | 生成 2–15 秒；含参考视频时最多 10 秒；编辑 2–10 秒；720P/1080P | 实跑 + 官方文档 |
| 可灵 2.x / 3.x | 文生、首帧、首尾帧；3.x 支持同步音频和多镜头 | Omni 的参考图不是普通图片数组：Mosael 会用 2–4 张图创建可复用主体，再在生成中引用主体 id | 2.x 为 5/10 秒；3.x 为 3–15 秒，720p/1080p/4K | 官方文档，尚无密钥实跑 |
| Google Veo（当前 `google:veo`） | 文生、首帧 | 当前 Adapter 只发送首帧；原生音频为模型固有能力 | 4/6/8 秒；720p，1080p/4K 仅 8 秒 | 官方文档，尚无密钥实跑 |
| ComfyUI | 由用户工作流决定 | 当前通过 `workflow` + `workflow_params` 动态注入；不能假设每个工作流都存在首尾帧或参考素材槽 | 工作流自定义 | 本地实跑 |
| Evolink 其他视频路由 | 保守地只开放该网关已确认的文生或首帧参数 | Sora、Grok、Veo、Kling、Hailuo、Wan 的上游原生能力不会自动继承给 Evolink 路由 | 以当前网关描述符为准 | 网关目录 |

## Seedance 2.0 本次修正

Evolink 原先只有 `seedance-2.0-text-to-video`，因此 UI 只能呈现纯文生。现在补齐：

- `seedance-2.0-image-to-video`
- `seedance-2.0-reference-to-video`
- `seedance-2.0-fast-text-to-video`
- `seedance-2.0-fast-image-to-video`
- `seedance-2.0-fast-reference-to-video`

图生模型只显示首帧与尾帧槽，并在提交前保证首帧存在；参考模型只显示参考图、参考视频、参考音频槽，
并在提交前限制份数和「音频不能单独提交」。Adapter 仍统一组装 `image_urls` / `video_urls` /
`audio_urls`，没有为每个上游模型复制一套 HTTP 实现。

## 已确认但尚未接通的能力差距

| 优先级 | 差距 | 为什么没有直接展示 |
| --- | --- | --- |
| P1 | Veo 3.1 的尾帧、最多 3 张参考图、视频续写 | 当前 Google Adapter 只实现首帧；只补 UI 会导致素材被忽略或请求形状错误 |
| P1 | Wan 2.5/2.6 的模型级拆分、自动音频与自定义音频 | 旧型号仍共用保守描述符，Adapter 尚未发送 `audio_url` / 音频开关；需按型号拆协议后再开放 |
| P1 | Wan 2.7 R2V 的参考音色、Video Edit 的音频设置 | 官方协议是嵌套结构，不等同于通用 `reference_audio`；需要新增明确领域角色或专用参数 |
| P2 | Evolink 上 Sora、Grok、Veo、Kling 等更完整的模型级能力 | 聚合端模型 id 与字段约束必须逐个核对，不能从原厂 API 推断 |
| P2 | ComfyUI 工作流的动态素材角色 | 应从工作流输入 schema 映射成角色，而不是给所有工作流硬编码同一组素材槽 |

## 主要来源

- 火山引擎：[Seedance 2.0 能力介绍](https://developer.volcengine.com/articles/7606009619928449070)、[视频生成提示词指南](https://www.volcengine.com/docs/82379/2222480?lang=zh)
- Evolink：[Seedance 2.0 模型与统一任务协议](https://github.com/EvoLinkAI/Seedance-2.5-Gateway-Service)、[首帧 / 首尾帧协议](https://github.com/EvoLinkAI/Seedance-2.5-Gateway-Service/blob/main/docs/image-to-video.md)、[全能参考协议](https://github.com/EvoLinkAI/Seedance-2.5-Gateway-Service/blob/main/docs/reference-to-video.md)
- 阿里云百炼：[Wan 模型总览](https://help.aliyun.com/zh/model-studio/video-generate-edit-model)、[Wan 2.7 图生 / 首尾帧 / 续写](https://help.aliyun.com/en/model-studio/image-to-video-general-api-reference)、[Wan 2.7 参考生视频](https://help.aliyun.com/zh/model-studio/wan-video-to-video-api-reference)、[Wan 视频编辑](https://help.aliyun.com/zh/model-studio/wan-video-editing-api-reference)
- Google：[Veo 视频生成 API](https://ai.google.dev/gemini-api/docs/veo?hl=en)
- 可灵：[Kling 3.0 模型使用指南](https://app.klingai.com/cn/quickstart/klingai-video-3-model-user-guide)
- MiniMax：[视频生成 API 指南](https://platform.minimax.io/docs/guides/video-generation)
- OpenAI：[Sora 视频 API](https://platform.openai.com/docs/api-reference/videos)
- xAI：[视频生成能力](https://docs.x.ai/developers/model-capabilities/video/generation)
