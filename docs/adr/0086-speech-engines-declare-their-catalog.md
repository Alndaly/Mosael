# 语音引擎在契约上声明目录信息，播客由 Registry 交出，公共接口不转出任何一家 Adapter

- 状态：Accepted（2026-10-28）；音色那一半（`builtin_voices`、`AccountVoiceCatalog`、`account_voices`）已由 [ADR 0087](0087-voice-option-catalog-and-ref.md) 取代为音色目录 `voices(context) -> list[VoiceOption]`
- 相关：[ADR 0010](0010-provider-contracts-adapters-registry.md)（Provider 的契约 / Adapter / Registry 三层）

## Context

ADR 0010 定下：`app.ai.providers` 是领域使用供应商的稳定公共 Interface，领域 Module 不直接选择具体 Adapter。
`test_provider_architecture` 也一直守着「domain 不 import `adapters`」。

但这条只在名义上成立。公共 Interface 原样转出了具体厂商的东西，领域层照样写死了每一家：

- 五个语音 Adapter 类（Edge、OpenAI、百炼、CosyVoice、火山）。`voices/engine_catalog.py` 读它们的 `engine_id`、`label_key`、`VOICES`，
  逐家手写一段引擎目录；「要不要钥匙、能不能调语速、要不要手填音色 id、说明文案」都写死在领域里。
  `voices/speech.py` 的能力表也逐家列了一遍。
- 三张音色表（`EDGE_BUILTIN_VOICES`、`VOLCANO_BUILTIN_VOICES`、`PODCAST_SPEAKERS`）。音色名字、下拉、播客默认发音人都直接读它们。
- 火山播客：`synthesize_volcano_podcast(appid, token, …)`、`PodcastAction`、轮数与字数上限、`split_to_rounds`。
  领域层知道凭据叫 `appid`、放在连接的附加字段里，也知道 vendor id 叫 `volcano-podcast`。
- 火山「按账号现拉音色」：`list_all_speakers(ak, sk)`、`VolcOpenAPIError`。领域层知道要去 `extra` 里取 `ak` / `sk`。
- 另有四个领域根本没用到的转出（`PodcastSynthesisError`、`PodcastSynthesisResult`、`extract_bailian_audio_url`、`is_cosyvoice`）。

结果是：接一家新的语音供应商，要改领域层的四个地方。漏改第二处的表现，是「引擎选得出来，音色下拉是空的」
（百炼刚接进来时就是这样）。

## Decision

1. **语音 Adapter 在契约上声明目录信息**（`backend/app/ai/providers/contracts/speech.py` 的 `SpeechAdapter`）：
   - 在原有 `engine_id`、`label_key` 之外，新增 `needs_key`、`supports_speed`、`needs_voice_id`、`note_key`；
   - 新增 `builtin_voices(model) -> ((id, 名字), …)`。音色随模型变的（百炼）按模型给，认不出的模型回空。
2. **音色随账号变的那几家另实现 `AccountVoiceCatalog.account_voices(连接的附加字段)`**（今天只有火山）。
   拉失败抛契约层的 `SpeechCatalogError`，调用方退回内置清单。
3. **播客是一项独立的能力契约**（`backend/app/ai/providers/contracts/podcast.py`）：
   - `PodcastEngine`：引擎 id、文案、发音人、上限，以及 `synthesize(连接, …)`；
   - `PodcastAction`、`PodcastSynthesisResult`、`PodcastSynthesisError`；
   - 通用的 `split_to_rounds(text, dual=, max_rounds=, max_round_chars=)`。

   火山实现为 `VolcanoPodcastEngine`：凭据怎么从连接里取（appid 在附加字段、token 在钥匙），只有这一家知道。
4. **Registry 汇总并交出**：
   - `speech_engines()`：内置念字引擎，按界面上的先后；
   - `builtin_voice_labels()`：所有内置音色与播客发音人的名字；
   - `account_voices(engine_id, 附加字段)`；
   - `podcast_engine()`。
5. **公共 Interface 只转出契约与 Registry**，不转出任何一家 Adapter 的东西。
   `test_provider_architecture` 新增一条：`app/ai/providers/__init__.py` 不得从 `adapters` 导入。

领域层随之只遍历 Registry 给的东西：
- `engine_catalog.describe_engines`：一个循环替代五段手写；
- 音色列表：「随模型变」按 `MODEL_PREFIXES` 认，「随账号变」按 `account_voices` 认；
- `speech.CAPABILITY`、`voice_labels`；
- 播客合成与试听：`podcast_engine().synthesize(连接, …)`，记账的 vendor 用 `engine.engine_id`。

## Consequences

- 接一家新的念字引擎 = 写一个 Adapter（在契约上填好目录信息）+ 在 Registry 的 `_SPEECH_ENGINES` 里加一行。领域层不用动。
- 引擎在设置页、能力表里的先后改为 Registry 的顺序：Edge、OpenAI、百炼、CosyVoice、火山。播客单独列在最后（它是另一种东西：一次产出一整段对话）。
- 针对某一家实现的测试照旧直接引用 `adapters`（ADR 0010 允许）。补丁跟着调用方实际取用的那个模块走：
  - 播客打在 `adapters/bytedance/volcano/podcast.synthesize_volcano_podcast` 上；
  - 账号音色打在 `adapters/bytedance/volcano/speech.list_all_speakers` 上。
- 本机引擎（克隆、Qwen3-TTS）不是供应商 Adapter，仍由领域层的本机运行时描述，不在这次范围内。

## Rejected alternatives

- **保留门面转出、只在领域里少写几处**：领域「只经公共 Interface」继续名义上成立、实际上认识每一家，问题原样留着。
- **给每一家写一个领域侧的描述对象**：描述和实现分住两处，加一家要改两处，就是现在这个问题换个位置。
- **把播客并进 `SpeechAdapter`**：念一句话和产出一整段多轮对话，在计费、轮次和发音人规则上都不一样。硬并成一个接口，双方都得带一堆用不上的参数。
