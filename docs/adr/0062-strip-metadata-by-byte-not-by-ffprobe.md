# ADR 0062:清除元数据 —— 默认只剥自己的隐私,验收只看字节

## Status

Accepted — 2026-10-16。维护者拍板:导出/保存时一个勾选项 **+** 一个可编排的节点/工具,**两个都做**;
provenance(AI 生成标记)单独一个开关、默认关、写明后果。本文档实现后端引擎与节点/工具/路由那一半;
前端的「导出时勾选」是下一步(接口形状见 §8)。

## Context

### 为什么需要它

素材发出去之前,画面之外还跟着一堆东西:**拍摄地点**(QuickTime 的 `©xyz` / 3GPP 的 `loci`)、
**设备与软件**(型号、固件、录制 App、编码器版本)、**账号与 ID**(作者、版权人、序列号)、
**封面图**,以及**数据轨**(GoPro 的 GPMF 遥测、时间码、定时元数据)。这些都不在画面上,用户也看不到。

而最麻烦的一层是 `ffprobe` **根本不显示**的:

| 层 | 藏在哪儿 | 里面是什么 |
| --- | --- | --- |
| **SEI** | H.264 的 NAL 类型 6 / H.265 的 39、40,载荷类型 5(`user_data_unregistered`) | x264 会把整条命令行写进去(`cabac=… ref=… me=…`),ffmpeg 写 `Lavc63.1.102`,不少机型写固件版本和序列号 |
| **DSE / 填充** | AAC 的 `raw_data_block`,元素号 4(`DSE`)和 6(`FIL`) | 有设备把账号、序列号、型号塞这儿;ffmpeg 自己的 AAC 编码器把版本串写进**填充字节**(实测) |
| **compressorname** | `stsd` 里图像样本入口那 32 字节 | 编码它的软件(`Adobe Premiere Pro 2024`、`Lavc63.1.102 libx264`) |

这一层正是 [reelbench-skills](https://github.com/eternityspring/reelbench-skills) 的 `video-scrub`
(Apache-2.0,只借方法与判据)指出的:输出和源在画面上**逐字节相同**(picture 是 copy 不是重编),
难在 `ffprobe` 看不见的那三层,所以它用**字节级门**验收而**不是**信 `ffprobe`。ADR 0061 的 Context
里已经点到过这个技能;这一篇是把它落地。

### 今天不做会怎样

- 用户点「导出」拿到一份带 GPS 和机型串的 mp4,自己完全不知道;
- 想做对的人只能装别的工具、或者干脆重编码一遍(画质掉一层)。

## Decision

### 1. 引擎放 `domain/assets/scrub/`,和别的「素材派生物」并排

`app/domain/assets/scrub/`:它产出的是一份**派生素材**(和转 GIF、降噪、分离、蒙版同一类),
所以跟它们住一起;不挂进 `domain/shots`(那条是"读画面里的东西",和这条没有交集)。
ffmpeg 那层薄封装仍在 `app/media/`。

**为什么不是新的 `domain/media` 包**:包级依赖棘轮(`tests/test_import_layering.py`)只许环变小,
而这条新包会同时连上 `assets`(登记派生素材)与 `workflows`(节点 executor),把新成员卷进那个
已有的包级环里。放进 `assets` 既没有新增包边,也在语义上就是它该在的地方。

模块分工:

| 模块 | 管什么 |
| --- | --- |
| `policy.py` | 默认剥什么、provenance 为什么单独、支持到哪一步 —— **拍板结果都在这里** |
| `mp4.py` | MP4/QuickTime 的盒子与样本表;只做**等长**的原地改写 |
| `nal.py` | H.264/H.265 的 NAL 与 SEI |
| `aac.py` | AAC 帧里的 `DSE` 与填充元素 |
| `engine.py` | 三步:重封装 → 原地改码流 → 自证 |
| `gates.py` | 十道门,全部靠扫字节 |
| `report.py` | 对账文本 |
| `task.py` | 领域编排:派生素材登记、对账落盘、后台任务 |

### 2. 默认剥掉的**确切清单**

按维护者的原话分成四类(名单在 `policy.DEFAULT_STRIP_KEYS`,对账文本按这四类逐条点名):

- **拍摄地点(GPS)**:`location` / `location-eng` / `©xyz` / `loci`(3GPP 定位盒) /
  `com.apple.quicktime.location.*` / `GPS*`。
- **设备、软件**:`make` / `model` / `©mak` / `©mod` / `©swr` / `com.apple.quicktime.make|model|software` /
  `encoder` / `©too` / `Lavf` / `Lavc` / `libx264` / `x264` / `GoPro` / `handler_name` /
  `ENCODER` / `ENCODER_SETTINGS` / `WritingApp` / `com.android.version`。
- **账号 / ID**:`artist` / `©ART` / `©aut` / `©cpy` / `author` / `comment` / `description` / `title` /
  `album*` / `genre` / `date` / `copyright` / `performer` / `serial*` / `com.apple.iTunes` /
  `iTunSMPB` / `iTunes` / `ID3`。
- **封面**:`covr` 盒子、`attached_pic` 那条流。

外加**数据轨**:只留 `vide` / `soun`,其余 handler(`meta` / `tmcd` / `text` / `sbtl` / `subt` /
`clcp` / `camm` / `mett` / `urim` / `hint` / `auxv`)一律不进输出 —— GoPro 的 GPMF 遥测、时间码、
定时元数据、字幕、附件都在这里。

**码流层默认剥**(§4 是做法):H.264/H.265 的 `user_data_unregistered` SEI、AAC 的 `DSE`
与**写过东西的**填充元素、`compressorname`、以及所有不属于 AI 生成标记的 `uuid` 盒子
(Adobe XMP 等)。

**默认保留**:`major_brand` / `minor_version` / `compatible_brands` / 时长这些播放必需的技术字段;
以及所有**技术性 SEI** —— `pic_timing`、`recovery_point`、`mastering_display_colour_volume`(HDR)、
`content_light_level_info`(HDR)、`alternative_transfer_characteristics`、
`user_data_registered_itu_t_t35`(**HDR10+ 与隐藏字幕就住在这儿**)。这些是画面的一部分,不是元数据;
剥掉它们会让 HDR 掉档、字幕消失。对账文本会把它们逐条点名("看到了、按设计保留")。

### 3. provenance(AI 生成标记)是**另一个**开关,默认关

C2PA 的清单在 MP4 里是一个顶层 `uuid` 盒子(`63327061-0011-0010-8000-00aa00389b71`,里面包 JUMBF),
视频这边还可以再写一份同 UUID 的 `user_data_unregistered` SEI。

**它和"你的隐私"是两件事**:前者是别人用来知道你放了什么,后者是你**必须**放、用来告诉别人
"这段是 AI 生成的"。所以:

- **默认关** —— 默认那一趟只动你自己的隐私,AI 生成标记原样保留。
- **打开要写明后果**(`policy.PROVENANCE["consequence_zh"]`,节点、确认卡、对账文本三处都引同一句):
  > 打开会把 AI 生成标记(C2PA 清单)一并抹掉,输出看起来和一段从未被 AI 碰过的素材一样。
  > 那不是「去掉你的隐私」,是**抹掉「这段是 AI 生成的」这个声明** —— 在要求标注 AI 生成的平台
  > 或地区,这可能让发布违规。关掉时这些标记原样保留。
- **两个开关不许合一个**:`provenance` 只影响"要不要清 AI 标记",一点点都不影响 §2 那份清单。

一个实现上的坑:`ffmpeg` 的 mp4 muxer **把所有顶层 `uuid` 盒子都丢掉**(实测,`-c copy` 也一样)。
所以默认那一趟不是"不去动它",而是**把 C2PA 的盒子原样追加回输出文件尾** —— 放文件尾是刻意的:
顶层盒子顺序没有约束,放在前面会把 mdat 往后推、`stco` 里每个 chunk 偏移就都错了。

**在 Mosael 里不许洗白**:清掉文件里的 C2PA 不等于库里也当它没生成过。派生素材照样继承父素材的
`ai_generated`(`domain/assets/lineage`,ADR 0028 的 AI 标识是另一件事)。

### 4. 码流层:**等长原地改写**,不是"抽掉再重封装"

抽掉一个 SEI NAL,样本长度就变了,`stsz` / `stco` 得整份重算,于是"画面载荷逐字节等于输入"
这条验收根本立不住。所以三处改写**都是等长的**:

- **SEI → 填充 NAL**。H.264 用类型 12、H.265 用类型 38(按规范就是给解码器丢的),载荷写 `0xFF`,
  **字节数一个不差**。实测:换完之后逐帧解码的 MD5 与输入一致。
  一段 SEI NAL 里如果既有要清的、又有要留的(比如 C2PA 按默认开关保留),就只把要清的那几段载荷
  按内容抹成 0 —— 定位不到的会记进对账文本("没敢动"),不假装清掉了。
- **AAC 的 `DSE` → 等长填充元素**。这里有一段算术:`FIL` 恒为 `7 + 8u` 比特(≡7 mod 8),
  `DSE` 恒为 `16 + 8n` 比特(≡0 mod 8)—— **一个填充换不掉一个 `DSE`,八个才行**
  (`8 × 7 = 56 ≡ 0 mod 8`)。所以用八个填充元素凑出**一模一样**的比特数,元素连同它的字节一起没了,
  而样本长度、容器样本表一个字节都不动。`DSE` 太短(载荷 ≤ 4 字节)放不下八个填充元素时,退化成
  **原地清零**并在对账文本里写明是"清零"不是"摘除"。
- **填充元素里非零的填充字节 → 清零**。按定义填充字节就是填充;ffmpeg 的版本串就在这里。

**AAC 那半会自证**:改完之后把输入输出的音轨各解一遍,比 PCM 的 MD5。不一样就**整体回滚**
(原始字节在手),报告里写"没敢动"。宁可少清,不可错清。

**做不到的说清楚**:`DSE` 要走到它,得先跳过它前面的元素;而 `SCE`/`CPE` 的帧内数据是 Huffman 编码的,
跳过去等于写一个完整的 AAC 解码器。所以只解析**帧首那一段**(`DSE` / `FIL` / `PCE` 连着排的前缀),
走到第一个音频元素就停;其余位置用**启发式报出来**(字节对齐、载荷像文本的 `DSE` 形状),
但**不清**,并写明这是启发式、可能误报。

### 5. 保证:**画面与声音逐字节不变**

一句能兑现的承诺,分三层说:

- **画面**:每个样本里 **VCL NAL(type 1–5 / 0–31)的字节与输入完全相同** —— 没有解码、没有编码,
  连重排都没有(`-c copy`)。这是"没有重编码"的硬证据,由 G6 逐样本钉住。
- **声音**:每个访问单元**只在被点名清掉的那几段字节上不同**,其余逐字节相同(G7 按引擎记录的
  区间比对)。没有可清的帧内元素时,它整份逐字节相同。
- **解码结果**:G9 把输入输出各解一遍,画面逐帧 MD5 相同、音轨 PCM MD5 相同。

**输出一律是 MP4。** 输入容器的键在非 MP4 一族(Matroska 等)上读不出来,所以"输入里原本有什么"
那一节会不全;但重封装之后落在 MP4 上的码流层照做,输出一定去掉了。

### 6. 支持与不支持(**实测**,不是照抄文档)

| 编码 | 容器层 | 码流层 | 说明 |
| --- | --- | --- | --- |
| **H.264(`avc1`/`avc3`)** | ✅ | ✅ 完整 | SEI 层按上述做法 |
| **H.265(`hvc1`/`hev1`)** | ✅ | ✅ 完整 | 前缀 SEI(39)/ 后缀 SEI(40),同一套 |
| AV1 / VP9 / VP8 / MPEG-4 / ProRes | ✅ | ❌ | 值在 OBU / 私有头里,不在这一版:报告里点名"编码不支持按字节重写" |
| 加密(`encv`/`enca`) | ❌ | ❌ | 直接拒(`scrubErr_encrypted`):载荷里读不出画面,谈不上"画面逐字节相同" |
| 无视频轨 | ❌ | ❌ | 直接拒(`scrubErr_notVideo`) |

容器:**输入**任意 ffmpeg 读得动的都收;**输出**一律 MP4。碎片化 MP4(`moof`)由重封装那一步
收成正片,之后照常。`co64` / `stz2` 都认。

### 7. 十道门:**全部靠扫字节,一道都不信 `ffprobe`**

| 门 | 查什么 | 硬/软 |
| --- | --- | --- |
| G1 | 输出里没有容器元数据盒子(`udta`/`ilst`/`loci`/`©xxx`/`Xtra`)与具体标签值;不该留的 `uuid` 盒子已不是 `uuid` | 软 |
| G2 | 只剩画面和声音的轨;轨数、时长与输入一致 | 软 |
| G3 | 输出里没有**非空**的 user-data SEI;默认开关下 C2PA 的 SEI 必须还在 | 软 |
| G4 | `stsd` 图像样本入口那 32 字节 `compressorname` 全零 | 软 |
| G5 | 音频帧首没有 `DSE`、没有写过东西的填充元素 | 软 |
| **G6** | **逐样本比 VCL NAL 的字节:一模一样** | **硬** |
| **G7** | **逐样本比音频访问单元:只差被点名清掉的那几段** | **硬** |
| G8 | 每轨样本数、每个样本长度、时间基、总时长逐项相同 | 软 |
| **G9** | **输出能整份解出来;逐帧画面 MD5 与音轨 PCM MD5 与输入一致** | **硬** |
| G10 | 全程最大的单次读取远小于文件本身(没有整份读进内存) | 软 |

**硬门红了说明产出不可信:文件删掉、不登记、不留半成品**(`scrubErr_gateFailed`)。软门红了照样交,
但一字不落地写进对账文本第一屏。启发式**不当门** —— 会误报的东西当门,门就永远是红的。

测试钉住两件事:正常路径**十道门全过**;以及**故意留一处脏数据时对应的门会红**
(`test_g1/g3/g4/g5/g6_goes_red_...`,另加一条"把画面真的重编码一遍 → G6 红")。

### 8. 入口:节点 + 路由 + 工具,前端那一半的形状

**工作流节点 `scrub_metadata`**(`wfCat_asset`,`spends: False`):

| 输入 | 类型 | 说明 |
| --- | --- | --- |
| `asset_id` | template, required, media=video | 要清的视频素材 |
| `provenance` | string, `no` / `yes`,默认 `no` | 文案里写明 §3 那段后果 |

输出:`asset_id`(新素材)、`report`(对账文本,string)、`removed`(计数,json)、`gates_ok`(boolean)。

**REST**(和"素材派生物"同一条做法,后台任务,`job_catalog` 里登记为 `scrub_metadata`):

```
POST /api/assets/{asset_id}/scrub     body: {"provenance": false}   → JobOut
GET  /api/assets/{asset_id}/scrub-report → {asset_id, status: "none"|"ready", markdown}
```

**前端「导出时勾选」需要的形状**(下一步做,后端已经就位):

- 请求体就是 `ScrubAssetRequest`(目前只有一个 `provenance: bool = False`);
- 返回 `JobOut`(照 `/convert-gif`、`/shots` 那条既有形状),`kind === "scrub_metadata"`;
- 任务 `result` 里有:`asset_id`(新的干净素材)、`source_asset_id`、`report`(整套对账 Markdown,
  可直接给「查看对账」用)、`gates`(十道门的逐条结果)、`gates_ok`、`removed`(计数)、
  `provenance`、必要时 `warnings`;
- 界面上那个开关旁边**必须**写 §3 那句话;勾选状态不要和后端默认值打架(默认 `false`);
- 任务图标已在 `frontend/src/components/jobs/jobKinds.tsx` 里登记(`scrub_metadata: Eraser`);
- 「来自」那一块用新的派生操作 `scrub`(文案 `assetLineageOpScrub` 中英都已加);
- 打开的对账文本读 `GET /api/assets/{asset_id}/scrub-report`,**没清过是 `status="none"` 不是 404**。

**智能体工具 `scrub_video_metadata`**(`effect="confirms"`,权限档 `edit`、成本 `none`):会改用户的东西
(多出一份素材、整份写一遍盘),所以开确认卡;能对话也能编排。工具描述里写清 `provenance` 的后果。

### 9. 一次清除产出一份**对账文本**

这是这条能力的价值所在,照 reelbench `half.txt` 那个态度:一份能逐条读的清账,四节 ——

1. **清除前发现了什么**:轨、数据轨、容器标签、容器元数据盒子、`uuid` 盒子、`compressorname`、
   SEI(按载荷类型 + UUID)、AAC 帧内元素、AI 生成标记在哪儿;
2. **清掉了什么**:逐项 + 计数(SEI 换了几条、DSE 换了几个、填充清了多少字节、`uuid` 收留/丢弃几个、
   `udta` 就地改了几个);
3. **清不掉的、以及为什么**:不支持的编码、AAC 帧首之外定位不到的元素、被回滚的音轨改动、
   默认保留的 SEI 类型、以及 §3 那段 AI 标记的后果;
4. **门禁结果**:十道门逐条 + 结论。

落在源素材旁边的 `<stem>.scrub-report.md`,同时进任务结果与节点输出。

### 10. 一条实现上的注意:`udta` 会被重封装留下一个空壳

ffmpeg 重封装后仍会写一个**空的** Apple `udta/meta/ilst`(handler `mdirappl`)。里面确实什么都没有,
但留着它等于给下一个往里面塞东西的程序留了位置,门禁(扫 `udta`)也会红。做法是把这个盒子的类型
**就地改成 `free`**、内容清零 —— 等长、偏移不动,读的人按填充跳过。

## Consequences

- 素材发出去之前可以一键去掉地点、设备、账号、封面和遥测,画面画质**一个比特都不掉**;
- 清单、判据、门和对账都在仓库里,不是"某个工具大概做了什么";
- 默认不动 AI 生成标记;要动必须显式打开,并且后果写在用户看得见的三处;
- **做不到的说得出来**:不支持的编码、AAC 帧首之外的元素、被回滚的改动,都进对账文本;
- 代价:输出一律 MP4(换容器);AAC 帧内元素只在帧首那一段可靠,其余只能启发式提示;
- 下一步:导出/保存时的那个勾选项(形状见 §8)。
