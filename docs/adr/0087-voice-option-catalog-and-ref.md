# 音色是一等概念：契约上的音色目录，存储上唯一的音色选择

- 状态：Accepted（2026-10-28）；分四步实施，见文末，尚未开始
- 相关：
  - [ADR 0010](0010-provider-contracts-adapters-registry.md)：Provider 的契约、Adapter、Registry 三层
  - [ADR 0028](0028-digital-humans.md)：数字人与授权声明
  - [ADR 0037](0037-cosyvoice-remote-voice-clone.md)：克隆音色的远端副本
  - [ADR 0086](0086-speech-engines-declare-their-catalog.md)：念字引擎在契约上声明目录信息
- 术语：见 CONTEXT.md「供应商」一节的念字引擎、音色、音色选项、音色目录、音色选择

## Context

ADR 0086 把「有哪些念字引擎、各自要不要钥匙、能不能调语速」收进了契约。
「用哪把嗓子」这一格没收，它今天仍是一串没有类型的字符串，散在六处，各存一种形状：

| 存放处 | 形状 |
|---|---|
| 合成参数（字幕配音、`voice_identity`） | `engine` / `voice_id` / `engine_voice` / `engine_model` / `clone_engine` / `clone_model` |
| 智能体朗读偏好 `AgentVoicePref` | `engine` / `engine_voice` / `engine_voice_resource` / `engine_model` / `provider_profile_id` / `voice_id` |
| 这台机器的默认 `VoiceDefaultConfig` | `engine` / `voice` |
| 工作流节点配置 | `engine` / `voice`；`voice` 有时是引擎音色 id，有时是克隆音色的 `voices.id`，按引擎猜 |
| 人物资产 `entities.attributes` | `voice_engine` / `voice_id` |
| 播客 | 发音人 id 列表 |

由此带来四个问题：

1. **音色依赖模型，选择却不记模型。**
   - 百炼的音色按模型给；CosyVoice 复刻出的音色绑死在建它的模型上，发给别的模型就是 400。
   - 默认那一对只存「引擎 + 音色」，模型另由 `ProviderDefault["tts"]` 或「连接下第一个 tts 模型」解出。
   - 两边各自变化时，默认音色和解出的模型会对不上，而没有任何地方校验这一对。
2. **单家协议细节漏进了公共形状。**
   - 火山合成要带音色所属的「资源族」，只有账号音色清单知道它。
   - 于是它成了数据库列 `engine_voice_resource`、合成请求字段和公开 API 的 `TtsVoiceOut.resource_id`。
   - 这正是 ADR 0086 要消除的那一类东西：领域层认识某一家。
3. **四个音色来源没有共同接口，领域层逐个手工合并。**
   - 内置音色是 Adapter 的类方法；账号音色是另一个 Protocol。
   - 本机预置音色在运行时里；克隆音色在领域表里。
   - 再加一种来源（某家的「我的音色」、另一家的复刻），就要再改领域层。
4. **给人挑的信息只有 id 和名字。**
   - 没有语言、性别、风格，也没有试听。
   - 火山账号音色、百炼按模型的几十个音色铺进下拉之后，只能靠名字猜。

## Decision

### 1. 契约：`VoiceOption` 与 `VoiceCatalog`

位置：`backend/app/ai/providers/contracts/speech.py`。

```python
@dataclass(frozen=True)
class VoiceOption:
    id: str                      # 引擎自己的音色 id；克隆音色是 voices.id
    label: str
    source: str                  # builtin | account | preset | cloned
    languages: tuple[str, ...] = ()   # BCP 47，如 ("zh-CN", "en-US")；不知道就留空，不猜
    gender: str = ""             # female | male | neutral | ""
    styles: tuple[str, ...] = ()      # 供应商给的风格 / 情感标签，原样
    models: tuple[str, ...] = ()      # 适用的模型（或模型族前缀）；空 = 这个引擎的所有模型
    preview_url: str = ""        # 供应商给了试听才有；不自己合成试听
    extra: Mapping[str, str] = {}     # 不透明，只有这一家 Adapter 解释（火山的资源族在这里）


class VoiceCatalog(Protocol):
    def voices(self, context: VoiceCatalogContext) -> list[VoiceOption]: ...
```

- `VoiceCatalogContext` 带着模型、这条连接的附加字段，以及按需取密钥的入口。
  按账号现拉的来源要用它，内置清单忽略它。
- 下面三个来源都实现 `VoiceCatalog`，取代今天的 `builtin_voices(model)` 和 `AccountVoiceCatalog.account_voices`：
  - **内置音色**；
  - **账号音色**（火山）：拉失败抛 `SpeechCatalogError`，调用方退回同一引擎的内置清单；
  - **本机预置音色**（Qwen3-TTS）。
- 字段**宁缺不猜**：供应商没说语言，就不按音色名推断。界面对缺的那一格不画筛选项。

### 2. 克隆音色由领域层并进同一份清单

克隆音色（`Voice`）是工作区的领域数据：本机参考音频是唯一来源，还带着授权声明。它不进供应商契约。

- 领域层的音色列表函数（`backend/app/domain/voices/`）是**唯一**的合并点：Registry 给的 `VoiceCatalog` 结果，加上工作区里的克隆音色。
- 克隆音色以 `source="cloned"` 的 `VoiceOption` 出现。
- 能复刻的远端引擎（CosyVoice）上，它照旧经远端副本（`VoiceEnrollment`，ADR 0037）念；副本的有无、状态不进 `VoiceOption`。
- 公开 API 只有一个音色选项的形状（`VoiceOptionOut`），`resource_id`、`cloned` 两个特判字段删除：
  - `cloned` 由 `source` 表达；
  - 资源族进 `extra`。

### 3. 存储：`VoiceRef` 是「选了哪把嗓子」的唯一形状

```python
@dataclass(frozen=True)
class VoiceRef:
    engine: str               # 宿主能力 speech 的候选 id：builtin:volcano、builtin:clone、插件连接 id
    voice: str = ""           # 引擎音色 id ……
    cloned_voice: str = ""    # …… 或克隆音色 voices.id，二者恰好一个
    model: str = ""           # 选择时这把嗓子对应的模型；空 = 这个音色不绑模型，按引擎解析
    connection: str = ""      # 走哪条连接；空 = 这个人在该引擎上的那一条
    extra: Mapping[str, str] = {}   # 从 VoiceOption.extra 原样带过来，只有那一家 Adapter 读
```

- **住在领域层**（`backend/app/domain/voices/`），以 JSON 一列落库。
  序列化和解析只有一处，合法性校验也只有一处：
  - 音色属不属于这个引擎；
  - 适不适用这个模型；
  - 克隆音色有没有授权声明。
- 写入时校验：设默认、存偏好、保存工作流节点时。合成前再校验一次：这一刻的目录可能已经变了。
- **语速不在其中**：它是念法，不是嗓子，各处照旧单独存。
- **模型绑定的音色必须带模型**：
  - 选中一个 `models` 非空的选项时，界面一并写下当时的模型；
  - 模型被删、或不再适用这个音色时，按「这把嗓子用不了」报错，不悄悄换模型。
- 下面这些全部改存 `VoiceRef`：
  - 合成参数；
  - `AgentVoicePref`、`VoiceDefaultConfig`；
  - 工作流节点、画板条目的音色配置；
  - 人物资产的音色；
  - 智能体工具的参数 schema。
- 以下旧的列与字段删除，不保留双读：
  - 数据库列：`engine_voice`、`engine_voice_resource`、`engine_model`、`voice_id`、`provider_profile_id`；
  - 合成参数：`clone_engine`、`clone_model`；
  - 人物资产属性：`voice_engine`、`voice_id`。
- 本机克隆引擎的 F5 / Fish 二选一（今天的 `clone_engine` / `clone_model`）并进 `model`，由本机念字 Adapter 解释。
  编码在第 4 步落定，写进本 ADR。

### 4. 默认只有一层「念哪把嗓子」

- 配音的默认就是一个 `VoiceRef`（含模型）：
  - 部署级：`VoiceDefaultConfig`；
  - 个人：`AgentVoicePref`、「能力提供方 → 配音」。
  两层的优先级照旧（`backend/app/domain/voices/defaults.py`）。
- `ProviderDefault` 的 `tts` 这一格**删掉**：
  - 它今天只在一处生效：`model_id_for` / `model_id_for_family` 里「全局默认正好指在这条连接上就用它」那一步
    （经 `backend/app/domain/voices/target.py` 与引擎目录）；连接列表上「这条连接的默认模型」那一格也会读到它；
  - 模型改由 `VoiceRef.model` 给出。
  - 迁移把已有的 `tts` 默认模型写进同一个人、同一引擎的 `VoiceRef.model`，再删行。
- `podcast` 默认照旧（`backend/app/domain/generation/voiced.py` 用它挑播客连接）。
  播客的发音人是同一种 `VoiceOption`（`PodcastEngine.speakers` 改为返回它），但一次选好几位，不是一个 `VoiceRef`。

### 5. 本机念字引擎进 Registry

- F5-TTS / Fish Speech（克隆）和 Qwen3-TTS（预置）实现同一个 `SpeechAdapter` + `VoiceCatalog`。
- 就绪判断（解释器跑得起来、权重在盘上）作为 Adapter 上的 `ready()` 钩子。
- Registry 一次交出全部念字引擎。
- `speech.CAPABILITY.builtins` 不再在领域层手写本机那几条。ADR 0086 留下的这块缺口就此补上。

## Consequences

**接一家新的念字引擎**：写一个 Adapter，实现 `SpeechAdapter` + `VoiceCatalog`，再在 Registry 加一行。
音色下拉、默认、工作流节点、人物资产都不用改。

**数据形状变化**，全部走迁移，不写兼容分支：
- **数据库**：`AgentVoicePref`、`VoiceDefaultConfig`、`ProviderDefault(tts)`、人物资产属性、库里存着的工作流定义与画板条目，
  各一步一次性迁移。合并前在真库副本上试跑。
- **工作流文件**（社区分享、导入导出）：`mosael_formats.workflow_file` 的 `VERSION` 升到 2，加一条升级链
  （照 `plugin_manifest_upgrade` 的写法）。读入 v1 文件时把节点里的 `engine` / `voice` 升成 `VoiceRef`。
  升不了的（指向别人工作区里的克隆音色）留空并标出来，导入时让人重选，不猜。
- **公开 API**：`TtsVoiceOut` → `VoiceOptionOut`；所有收音色的请求体收一个 `voice: VoiceRef`。
  前端随之改一处选择器，所有入口共用。

**火山的资源族**只在火山 Adapter 里出现：从它的 `VoiceOption.extra` 来，经 `VoiceRef.extra` 回到它自己手里。

**字幕配音的 `voice_identity`**（判断「这一句是不是同一把嗓子念的」）改为对 `VoiceRef` 加语速取规范化序列化。
已有配音记录上的旧串随迁移重算。

## Rejected alternatives

- **只给现有几处各加一个 `model` 列。**
  修了第 1 个问题，留下六种形状和单家字段。下次再加一格，还要改六处。
- **把所有供应商的音色同步进一张本地表。**
  账号音色随账号变，内置音色随供应商上新。本地表要么天天同步，要么过期。
  现拉 + 内置清单已经够用，不缺这层缓存。
- **把克隆音色也做成供应商契约的一个来源。**
  克隆音色带授权声明、归工作区、本机参考音频是唯一来源，它是领域数据。
  放进 `ai/providers` 会让契约层认识工作区和授权。
- **`VoiceRef` 里塞语速。**
  同一把嗓子在对话里念快一点、在成片里念慢一点，是常见用法。
  合在一起，「是不是同一把嗓子」就要先剥掉语速才能比。

## 实施步骤

每一步单独提交，跑全量门禁：

1. **契约**：`VoiceOption` / `VoiceCatalog` / `VoiceCatalogContext`。远端 Adapter 改为实现它，删掉 `builtin_voices` 与 `AccountVoiceCatalog`。
   领域的音色列表改为只遍历 Registry + 克隆音色，公开 API 换成 `VoiceOptionOut`，前端选择器随之改。这一步不动存储。
2. **`VoiceRef` 与迁移**：值对象、校验，数据库与人物资产迁移，`ProviderDefault(tts)` 迁移后删除，合成参数与 `voice_identity` 改形。
3. **工作流与画板**：节点配置、画板条目、智能体工具 schema 改收 `VoiceRef`；`workflow_file` 升到 v2 并加升级链。
4. **本机念字引擎进 Registry**：落定本机克隆在 `model` 里的编码，写回本 ADR。
