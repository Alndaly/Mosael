# ADR 0037:克隆音色复刻到百炼 CosyVoice —— 一把嗓子,本机和远端两种念法

## Status

Accepted — 2026-10-05

## Context

配音库里的克隆音色现在只有一种念法:**本机零样本引擎**(F5-TTS / Fish Speech)。一把嗓子 = 一段 5–15 秒的参考音频 +
它的文字(`Voice`),合成时把「参考音频 + 参考文本 + 要念的字」交给本机引擎。代价是先装运行环境、下几 GB 权重,
首次加载十几分钟 —— 大多数人卡在这一步,克隆音色对他们等于不存在。

百炼的 CosyVoice 有**声音复刻**:用一段朗读建一个音色,之后像系统音色一样按字符计费地合成。Mosael 早已接了 CosyVoice 的
合成(引擎 `builtin:alibaba-cosyvoice`,`CosyVoiceSpeechAdapter`),缺的只是「复刻」这一半。1.9.0 付费实测时发现这个缺口,
维护者拍板:不挤进 1.9.0,发版后当新功能做,先写 ADR。

和火山不一样:火山的复刻音色(`S_` 开头)是在**火山控制台**里训练好、Mosael 实时列出来用的(`volcano/speakers.py`)。
这份 ADR 说的是**从 Mosael 里**把配音库已有的一把嗓子复刻上去。

### 真机验证(2026-10-05)

测试素材是 Edge 合成的 15 秒中文朗读,不是真人录音;音色建完即删。

| 问的事 | 结果 |
| --- | --- |
| 参考音频怎么交 | 接口只收地址(文档写「公网可访问」)。**百炼自己的临时存储可用**:按 `model=voice-enrollment` 取上传凭证、直传 OSS,得到 `oss://…`,提交时带 `X-DashScope-OssResourceResolve: enable` —— 和数字人那条路(`dashscope/digital_human.upload_temporary`)同一套,不需要用户自己的对象存储 |
| 建音色 | `POST /api/v1/services/audio/tts/customization`,`{"model":"voice-enrollment","input":{"action":"create_voice","target_model":…,"prefix":…,"url":…}}` → `output.voice_id` 形如 `cosyvoice-v3-flash-<prefix>-<32 位 hex>` |
| 前缀 | 超过 10 个字符直接 400(`prefix should not be longer than 10 characters`);文档另说只收字母和数字 |
| 是不是同步 | **不是**。`query_voice` 先是 DEPLOYING,约 10.6 秒后 `OK`;字段有 `status`、`target_model`、`resource_link`、`gmt_create`、`gmt_modified` |
| 合成 | 现有 `CosyVoiceSpeechAdapter` **一行不改**,`voice` 换成复刻出的 `voice_id` 就念出来了(2.08 秒) |
| 跨模型 | 在 `cosyvoice-v3-flash` 上建的音色发给 `cosyvoice-v2`:400。**音色绑死在建它的那个模型上** |
| 列表 / 删除 | `list_voice` 可按前缀过滤;`delete_voice` 之后列表为空 |

文档里另有几条约束:建音色免费,合成按 CosyVoice 的字符价计;一个账号最多 1000 个复刻音色;**一年内没被合成用过的
音色会被自动删除**;音频推荐 10–20 秒、最长 60 秒、≤10 MB、≥16 kHz、至少 5 秒连续清晰的朗读;北京地域
v3.5-plus / v3.5-flash / v3-plus / v3-flash / v2 都能复刻,新加坡只有 v3-plus。

## Decision

### 1. 一把嗓子仍是一行 `Voice`;复刻是挂在它下面的「远端副本」

新表 `voice_enrollments`:

| 列 | 说什么 |
| --- | --- |
| `voice_id` | 哪把嗓子(外键 `voices`,删嗓子级联) |
| `engine` | 复刻在哪个引擎上(这一版只有 `alibaba-cosyvoice`) |
| `provider_profile_id`、`owner_user_id` | **在谁的账号里** —— 钥匙归人,同一条连接下每个人用自己的 Key,复刻出来的音色只活在那个账号里 |
| `target_model` | 建在哪个模型上(音色绑模型,见上表) |
| `remote_voice_id` | 百炼给的 `voice_id` |
| `status` | `deploying` / `ok` / `failed` / `missing` |
| `last_used_at`、`created_at`、`error` | 最近一次合成用到它的时间(一年不用会被删)、建的时间、失败原因原文 |

`(voice_id, engine, provider_profile_id, owner_user_id, target_model)` 唯一。

不把 `remote_voice_id` 直接加在 `voices` 上:一把嗓子可能在几个人的账号、几个模型上各有一份,一列装不下;而且
那会让「这把嗓子是什么」(参考音频、文字、授权声明)和「它在哪儿有副本」搅成一件事。

**本机的参考音频仍是唯一的来源**。远端副本丢了(一年没用被删、换了账号、换了模型)随时能从它重建,所以副本不需要
备份,也不需要「从百炼拉回来」。

### 2. 选法:CosyVoice 的音色下拉多一组「我的克隆音色」

选了 CosyVoice 引擎时,音色下拉在系统音色之外多一组这个工作区的克隆音色。选中的话,请求带 `voice_id`(和本机
克隆引擎**同一个字段**),`engine_voice` 留空;宿主在合成前把它解析成「这个人的连接 + 当前 CosyVoice 模型」下的
`remote_voice_id`。配音、字幕逐句配音、AI 工作台、智能体语音对话、工作流的配音节点都走 `speak_to_file`,
解析放在那一处,入口不用各自认识复刻。

### 3. 什么时候上传

参考音频离开这台机器、进到第三方账号里,是需要当事人知道的事。所以:

- **第一次**把某把嗓子用到 CosyVoice 上(或在配音库里点「复刻到百炼」)时确认一次:说清这段参考音频会上传到阿里云
  百炼、存在你自己的百炼账号里、一年不用会被百炼删掉、在 Mosael 里删掉这把嗓子会一起删掉远端的。同意记在副本上。
- 之后换了模型、副本被删时**按需重建,不再问** —— 同一把嗓子、同一家、同一个账号,已经同意过。
- **没声明授权的嗓子不能复刻**(`consent_kind == undeclared`,ADR 0028 §5 的同一条线):不知道是谁的嗓子,
  不往外传。

### 4. 复刻和合成的流程

- 适配器层新增 `adapters/alibaba/dashscope/voice_enrollment.py`:`create` / `query` / `list` / `delete` 四个动作,
  错误照百炼原话。临时上传 `upload_temporary` 从 `digital_human.py` 挪到 dashscope 下的共用模块(两处在用)。
- 领域层新增 `voices/remote.py` 的 `ensure_enrollment(db, voice, user, model)`:有 `ok` 的副本就用;没有就上传、
  `create_voice`、轮询 `query_voice` 到 `OK`(实测约 10 秒,上限 2 分钟)。在**配音任务里**做,任务进度写
  「正在百炼上复刻这把嗓子」,不在请求线程里等。
- 前缀用 `m` + `Voice.id` 的前 9 位(十个字符以内,只有字母数字):`list_voice` 时认得出哪条是 Mosael 建的、
  对应哪把嗓子,可以清理没人认领的副本。
- 合成仍走 `speak_to_file` → `CosyVoiceSpeechAdapter`,`voice` 换成 `remote_voice_id`,适配器不动。
- 合成回「音色不存在」(被百炼删了、换了账号):副本标 `missing`,**重建一次**再念;再失败才报错。每次合成成功
  更新 `last_used_at`。
- 在 Mosael 里删掉一把嗓子:先逐个 `delete_voice` 删远端副本,删不掉的(Key 失效、网络)列出来,告诉用户去
  百炼控制台看,本机这行照删。

### 5. 计费

建音色免费,合成照现有的 `billable` 按字符记,不变。复刻这一步也记一条用量(`tts` / `enroll_voice`,标免费):
账上能看到「哪天、哪把嗓子、传到了哪条连接」 —— 这是给人查「我的声音去过哪」用的,不是为了钱。

### 6. 和本机克隆引擎并存

本机克隆引擎(`builtin:clone`)一行不动。同一把嗓子两边都能用:本机直接用参考音频,CosyVoice 用副本。配音库里每把
嗓子显示它在哪儿能念:「本机」「百炼 · cosyvoice-v3-flash」。参考音频时长沿用 5–15 秒(见文末已拍板第 2 项)。

### 7. 测试

- 适配器:请求体、前缀长度、状态值的 payload 测试。
- 领域(假适配器):`ensure_enrollment` 幂等;`missing` 时只重建一次;未声明授权的拒绝;删嗓子时远端删除失败照删本机
  并列出;换模型建新副本、不动旧的。
- 真机:测试素材用 Edge 合成的朗读,不用真人录音;用完 `delete_voice`。

## 这一版不做

- 火山的声音复刻 API、qwen-tts 的声音复刻(`qwen-tts-vc` 一族)、MiniMax 克隆 —— 同一张 `voice_enrollments`
  装得下,等有人要再接。
- 新加坡地域(只有 v3-plus 能复刻):认不出时照百炼原话报错,不预判。
- 「从百炼拉回在控制台建的音色」:那是火山那种做法,CosyVoice 控制台建的音色用户照旧可以手填 id。

## 已拍板(2026-10-05):四项都选 A

1. **上传时机**:每把嗓子第一次用到 CosyVoice 时确认一次,之后按需重建(换了模型、副本被百炼删了)不再问。
   (没选 B「只能在配音库里手动复刻,配音时没复刻过就报错」,也没选 C「不问,直接传」。)
2. **参考时长**:沿用 5–15 秒。15 秒落在 CosyVoice 推荐的 10–20 秒里,本机引擎的约束不动;不另存一份最长 20 秒的参考。
3. **多人部署**:副本跟着钥匙走,每人在自己的百炼账号里复刻一份(和「钥匙归人」一致),不由管理员的账号统一复刻。
4. **目标模型**:跟着这条连接上配的 CosyVoice 模型走,换模型时按需建新副本;不固定 `cosyvoice-v3-flash`。

## Consequences

- 没装本机引擎的人也能用克隆音色配音,代价是每次合成按字符付费、参考音频存进了自己的百炼账号。
- 「一把嗓子」和「它在哪儿有副本」分开以后,以后接火山 / qwen / MiniMax 的复刻只是多一个 `engine` 取值和一个适配器。
- 远端副本可能在 Mosael 不知情时消失(一年没用),所以合成路径必须能自己重建 —— 这也是本机参考音频必须一直留着的原因。
