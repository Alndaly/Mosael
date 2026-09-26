# 音频生成能力矩阵

> 核查日期：2026-09-25。音频(音乐、BGM、歌曲、音效、给视频配声)是生成的第三种,见
> [ADR 0022](adr/0022-audio-is-a-generation-kind.md)。本文区分「供应商原生能力」与「Mosael 已接通能力」;
> 只有后者进 `backend/app/domain/generation/catalog.py`,出现在界面、工作流与智能体的参数描述符里。
>
> **证据等级:全部是「官方文档」,没有一家真机跑过** —— 没有密钥可核,而这些接口按次收钱。第一次真跑时要
> 像视频那边(`tests/test_capabilities_match_reality.py`)一样逐项重核上限。

## 宿主词汇

| 键 | 含义 | 各家怎么接 |
| --- | --- | --- |
| 提示词 | 怎么唱 / 什么声音:风格、流派、情绪、乐器、速度 | Suno 自定义模式进 `style`;火山纯音乐进 `Text`;可灵视频配声进 `sound_effect_prompt` |
| `lyrics` | 要唱的字(长文字,`[Verse]` / `[Chorus]`) | 上限 `max_lyrics_chars`;Lyria 按文档拼进提示词 |
| `instrumental` | 纯音乐 | 给了就不能有歌词,而且要有描述(提交前拦) |
| `duration_seconds` | 时长,**可选** | 多数音乐模型按歌词定曲长;不给就不发 |
| `vocal_gender` / `title` / `bgm_prompt` / `model_version` / `asmr_mode` | 各家特有 | `parameter_schema` / `parameter_choices` 声明,界面按宿主文案命名 |
| `source_video` | 要配声的那段视频 | 可灵只收链接(`url_only_roles`) |
| `reference_audio` | 参考音频(照着它的风格 / 音色) | 百炼 AudioGen(≤3 段) |
| `reference_image` | 图生音乐 | Lyria(≤10 张) |

描述符上的音频专属格子:`max_lyrics_chars`、`default_instrumental`、`lyrics_excludes_prompt`、`requires_prompt`、
`requires_lyrics`、`prompt_optional`、`outputs_per_request`。

## 已接通

| 接入 / 模型 | 模式 | 关键约束 | 协议 | 文档 |
| --- | --- | --- | --- | --- |
| Google `lyria-3.5` / `lyria-3-pro-preview` / `lyria-3-clip-preview` | 歌曲、纯音乐、图生音乐 | 无结构化参数;clip 固定 30 秒;可附 10 张图 | `generateContent`,同步 | [指南](https://ai.google.dev/gemini-api/docs/generate-content/music-generation)、[模型](https://ai.google.dev/gemini-api/docs/models/lyria-3.5) |
| Evolink `suno-v5.5-beta` / `v5` / `v4.5plus` / `v4.5all` / `v4.5` / `v4` | 歌曲、纯音乐 | 简单模式描述 ≤500;自定义模式 style ≤1000(v4 ≤200)、歌词 ≤5000(v4 ≤3000);只有 v5.5 收时长 10–360 秒;一次两首 | `POST /v1/audios/generations` + `GET /v1/tasks/{id}`,异步 | [Suno](https://evolink.ai/docs/en/api-manual/audio-series/suno/suno-music-generation) |
| 可灵 `kling-text-to-audio` | 音效 | 描述 ≤200 必填;时长 3–10 秒必填 | `/v1/audio/text-to-audio`,异步 | [文生音效](https://kling.ai/document-api/api/video/audio-generation/text-to-audio) |
| 可灵 `kling-video-to-audio` | 给视频配音效 / 配乐 | 视频 mp4/mov、3–20 秒、≤100MB、只收链接;描述与 `bgm_prompt` 各 ≤200、可空 | `/v1/audio/video-to-audio`,异步;取单独音轨(wav 优先) | [视频生音效](https://kling.ai/document-api/api/video/audio-generation/video-to-audio) |
| 百炼 `fun-music-v1` / `fun-music-preview` | 歌曲、纯音乐 | 仅北京地域、需申请;v1 歌词会覆盖描述(两段都给时拦);preview 描述必填 | `/api/v1/services/audio/music/generation`,同步 | [Fun-Music API](https://help.aliyun.com/zh/model-studio/fun-music-api) |
| 百炼 `qwen-audio-3.1-tts-next` | 音效、环境声(也能出语音) | 描述 ≤3000;参考音频 ≤3 段;单次 ≤120 秒,无时长参数 | `/api/v1/services/audio/tts/SpeechSynthesizer`,同步 | [AudioGen API](https://www.alibabacloud.com/help/en/model-studio/audio-generation-api) |
| 火山 `GenSongForTime` / `GenSongV4` | 人声歌曲 | 30–240 秒;歌词和描述只给一段;`ModelVersion` v4.0 / v4.3 / v5.0 | OpenAPI(AK/SK 签名,服务 `imagination`)+ `QuerySong`,异步 | [人声歌曲](https://www.volcengine.com/docs/84992/2091679) |
| 火山 `GenBGMForTime` / `GenBGM` | 纯音乐 / BGM | 描述只收中文;v5.0 30–120 秒(价目页写「60s 以内」,两页不一致) | 同上 | [纯音乐](https://www.volcengine.com/docs/84992/2100970) |
| 插件(`kind: "audio"`) | 由插件声明 | `lyrics` / `instrumental` 映射到宿主控件,其余进 `parameter_schema` | 插件协议(ADR 0020) | [PLUGIN_MANIFEST](PLUGIN_MANIFEST.md) |

## 计量与价目

- 用量:`audios`(交回几首)、`lyrics_characters`、`audio_seconds`(供应商回报的计费秒数优先,否则按登记后探测的
  真实时长;**不**记请求里的时长)。计价单位:`audio`(按首)、`audio_second`(按秒)、`request`。
- 已收挂牌价(`backend/app/domain/price_reference.py`,2026-09):Lyria 3.5 / 3 Pro $0.08/首、Clip $0.04/首
  ([价目](https://ai.google.dev/gemini-api/docs/pricing));百炼 Fun-Music v1 ¥0.002/秒、preview ¥0.005/秒
  ([价目](https://help.aliyun.com/zh/model-studio/model-pricing));火山后付费 ¥0.002/秒
  ([计费](https://www.volcengine.com/docs/84992/1404661))。
- 没收:可灵音效(0.25 单位 / 积分,一家两币);AudioGen(按 token 报价、按时长计费,
  换算没写);火山资源包(包价);Evolink 上的 Suno(中转价)。

## 查过但没接

| 供应商 / 能力 | 为什么 |
| --- | --- |
| OpenAI | 没有音乐 / 音效接口,只有语音合成([audio 接口](https://developers.openai.com/api/reference/resources/audio)) |
| Google Lyria RealTime(`lyria-realtime-exp`) | WebSocket 流式、实验性、价目页未列;不是「提交一次、拿回一个文件」的形状 |
| Vertex AI `lyria-002` | 要 OAuth / ADC,不收 API Key;而 Gemini API 上已有 Lyria 3 / 3.5 |
| 火山方舟 ARK | 模型列表里没有音乐模型(音频只有 TTS / ASR) |
| MiniMax 音乐(`music-3.0` / `music-2.6` / `music-cover`)与歌词生成 | 2026-08-20 起不再向新用户开放([音乐生成](https://platform.minimax.cn/docs/api-reference/music-generation)),价目页标「已下线」。曾接入过,2026-09-26 撤掉,存着的引用由迁移 `remove-minimax-music-models` 清掉 |
| 火山 `GenLyrics` | 生成的是文字,不是音频;可作为以后的「写词」辅助 |
| Evolink `suno-persona` / Seed-Audio / Qwen TTS | persona 是保存音色的管理动作;另外两个是语音合成 |
| 百炼万相的视频配音 | 声音在视频里一起出,不单独产出音频文件 |

## 还没确认的

- Suno 完成态 `result_data` 的确切形状(文档有两种说法;Adapter 以 `results` 为准,兜底读 `result_data`)。
- 可灵音频接口是否还收 AK/SK 签的 JWT(文档现在推荐控制台 API Key;两种 Adapter 都支持)。
- 百炼两个音频模型在旧域名 `dashscope.aliyuncs.com` 上是否可用(文档说旧域名「仍然完全可用」,没实测)。
