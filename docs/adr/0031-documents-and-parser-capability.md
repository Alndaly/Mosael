# ADR 0031:文档进素材库、智能体能读 —— 本地解析 + 插件解析(MinerU),解析是一项「宿主能力」

## Status

Accepted — 2026-09-28。维护者拍板:

- 解析结果是**素材的派生物**,「存成笔记」是一个明确的动作(不自动建笔记);同一份文档可以留几份解析。
- 本地解析用纯 Python 库;**本机装了 LibreOffice 就用它**给 pptx / docx 渲页面图,没装就只有文字和插图。
- **先做文档解析**,数字人的可灵 / HeyGen / Hedra 排在它之后。

## Context

用户:「我希望进一步完善文件导入体系,比如 pptx、docx 等常见文件格式,现在智能体甚至无法引用、解析这些常见文件……
除去本地的解析方式以外,请你补充 MinerU 插件……请仔细思考一下该如何优化插件架构。」

### 今天的样子(读代码得出)

- **素材只有三种:图片、视频、音频。** `media/probe.guess_kind` 判不出图片、音频的一律当**视频** —— 一份 pptx
  传上来进的是「视频」,还会去起一个视频代理转码任务(`importer.import_file` → `start_proxy_job`)。
- **后端没有任何文档解析**:没有 pdf / docx / pptx / xlsx 的依赖,也没有一行读它们的代码。
- **智能体读不到**:`analyze_asset` 只收图片、视频(`analysisErr_unsupportedKind`);附件标记 `[附件 asset_id=…]`
  只对图片带视觉;笔记(`notes`)是 Markdown,智能体能读,但文档进不了笔记。
- **插件已有「替宿主做成什么」**(`provides`):`public_url`(素材外链)、`generation`(当生成供应商)、`tools`。
  每一项的宿主侧各写一套:外链有自己的设置页和 `plugin_capability_defaults`,生成有自己的连接同步
  (`host_capabilities.register`)。插件收文件(`format: "asset"` → 本地副本路径)、交文件(`artifact(s)`)、流式进度
  这几样底座是现成的。

### 别人怎么做(2026-09 查的公开资料)

| 产品 | PDF | docx / pptx / xlsx |
| --- | --- | --- |
| Claude(API / claude.ai) | **每页转成图片 + 抽出的文字一起给模型**,图表、版式、扫描件都看得到;每页约 1.5k–3k token([PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)) | 内置 Agent Skills(docx / pptx / xlsx / pdf)在代码沙箱里读:pptx 用 `markitdown` 出「每页一段」的文字,要看版式时 `soffice` 转 PDF 再 `pdftoppm` 出每页图;docx 用 `pandoc -t markdown`,要看版式同样转 PDF 出图;复杂的直接解 zip 读 XML([pptx skill](https://github.com/anthropics/skills/tree/main/skills/pptx)、[docx skill](https://github.com/anthropics/skills/tree/main/skills/docx)) |
| OpenAI(Responses API / ChatGPT) | 同一思路:**抽文字 + 每页图片**都进上下文(视觉模型)([File inputs](https://developers.openai.com/api/docs/guides/file-inputs)) | ChatGPT 走检索(切块)或代码解释器 |
| Codex | 本机沙箱里的 agent,自己跑 shell / Python 读;官方有读写 PDF、表格、docx 的 skills([Codex](https://openai.com/codex/)) | 同左 |

共同点三条,也是这份决定的骨架:

1. **两份表示并用**:可检索、可引用的**文字(Markdown)**,加上保留版式的**页面图像**(给视觉模型看图表、截图、排版)。
   只有文字会丢掉 PPT 的一半意思;只有图片既贵又不能搜。
2. **先便宜后贵**:原生数字文档(docx / pptx / xlsx / 有文字层的 PDF)本地库直接抽,又快又免费;扫描件、复杂版式、
   公式表格才交给重模型(OCR / 版面分析)。
3. **按需读,不整份塞**:大文档先给目录 / 概要,模型再按页、按段去取。

### MinerU

开源的文档解析(opendatalab),把 PDF / Office / 图片转成 Markdown + 结构化 JSON。两种用法:

- **云端 API(mineru.net)**:`Authorization: Bearer <token>`;本地文件先 `POST /api/v4/file-urls/batch` 要上传链接、
  `PUT` 上去(**不需要公网直链**),再轮询 `GET /api/v4/extract-results/batch/{batch_id}`;支持 PDF、DOC/DOCX、PPT/PPTX、
  XLS/XLSX、常见图片;单文件 200MB、200 页;选项 `is_ocr` / `enable_formula` / `enable_table` / `language` /
  `model_version`(pipeline / vlm)/ `page_ranges`;结果是一个 zip:`full.md`、`content_list.json`、`layout.json`、
  图片([接口文档](https://mineru.net/apiManage/docs))。
- **自建**:用户自己跑 MinerU 的 API 服务(要 GPU 和几个 G 的模型),插件填一个服务地址即可。**不把 MinerU 的模型
  打进 Mosael 安装包** —— 体积和显卡要求都不是每个用户该承担的。

## Decision(提议)

### 1. 素材多一种:文档(`document`)

- 认的扩展名:`pdf`、`docx` / `doc`、`pptx` / `ppt`、`xlsx` / `xls` / `csv`、`md` / `txt`、`html`、`epub`。
  `guess_kind` 改成**按白名单认**:视频只认视频,文档认文档,**都不是的拒收并说清楚**(不再兜底成视频)。
- 已经被错当成视频的文档由迁移改回 `document`、撤掉它们的代理转码(不写兼容分支)。
- 文档素材有缩略图(第一页 / 第一张幻灯片)、页数、幻灯片数、字数,素材库里有「文档」筛选。

### 2. 解析结果是素材的一份**派生物**,不是另一种东西

- 一次解析交出:`full.md`(全文 Markdown,按页 / 按幻灯片分段,段首有页码标记)、`pages.json`(每页的文字、标题、
  在 Markdown 里的位置)、抽出来的图片(文档里的插图 → 素材库里的图片,和原文档关联)、可选的**页面图**(每页渲一张,
  给视觉模型看版式)。
- 存在素材目录的 `extracted/<解析器>/` 下,库里一张 `asset_extractions`(素材、解析器、状态、页数、出错原因、时间)。
  **同一份文档可以有几份解析**(本地快解析 + MinerU 精解析),读的时候用最好的那份,界面上能看到是谁解析的、能重新解析。
- 解析是一个任务(`document_parse`):有进度、能取消,和转码、生成同一套任务总线。
- 「存成笔记」是一个**明确的动作**:把解析出的 Markdown 建成一篇笔记(插图换成素材引用),从此能在知识库里编辑、
  在画板上用文档格引用。不自动建 —— 文档是原件,笔记是加工品。

### 3. 解析器是一项**宿主能力** `document_parse`:内置的本地解析和插件同台

- **本地解析(内置,默认)**:后端直接带轻量纯 Python 库 —— Office 用 `markitdown`(docx→mammoth、pptx→python-pptx、
  xlsx→openpyxl,MIT)、PDF 文字层用 `pypdfium2` 抽文字并**渲每页图**。Mosael 不打包 LibreOffice;**本机装了**
  (`soffice` 在 PATH 或常见安装位置)就用它把 pptx / docx 转成 PDF 再渲页面图,没装就只有文字和插图,解析结果上说清楚
  「装了 LibreOffice 能看到每页版式」。管得了原生数字文档,管不了扫描件和复杂版式 —— 结果上如实标「文字很少,可能是
  扫描件,可以用 MinerU 重新解析」。
- **插件解析**:插件在包上和工具上声明 `provides: ["document_parse"]`,工具收 `{file: <format: asset>, options}`,
  把 `full.md`、`pages.json`、图片写进输出目录交回(现成的 `artifacts` + 流式进度);清单里写明 `accepts`(认哪些扩展名)。
- **MinerU 插件**(`plugins/bundled/mineru`,随包带、默认不启用):一个连接二选一 ——
  「云端(mineru.net,填 Token)」或「自建服务(填地址)」;选项对应 OCR、公式、表格、语言、模型版本。
  `effects: "external"`(文档会离开本机):智能体替人用它时开确认卡。
- **用哪一家**:和「素材外链」同一个规矩 —— 只用发起人自己的连接;**云端解析从不自动用**,除非他在
  「设置 → 文档解析」里定了默认;素材详情里「用 ×× 重新解析」随时可点。

### 4. 智能体、工作流、画板怎么用

- **智能体**:
  - `read_document(asset_id, pages?)`:给目录和概要;带页码范围给那几页的 Markdown(有上限,超了说还剩多少页)。
  - `view_document_pages(asset_id, pages)`:给那几页的**页面图**(视觉模型),看图表、版式、PPT 设计。
  - 附件标记 `[附件 asset_id=… 类型=document]` 进来时,短文档直接把全文放进上下文,长文档放目录,再按需取 ——
    和 Claude / OpenAI 的「文字 + 页面图、按需读」同一个思路。
  - 还没解析的先解析(本地的直接跑;云端的按上面的规矩)。
- **工作流**:节点「文档转 Markdown」(输出 `markdown`、`pages`、`image_asset_ids`),接写作、翻译、生成。
- **画板**:文档素材拖上来是一格文档格 —— 连进写作 / 生成格时喂的是解析出的全文;「存成笔记」在操作条上。

### 5. 插件架构的调整:能力从「各写一套」变成「一张能力表」

今天每加一项 `provides`,宿主要各写:清单校验里的特判、默认连接的设置页、调用时挑连接的逻辑、失败时说哪句话。
第四项(`document_parse`)再照抄一遍,第五项(OCR、转写引擎、TTS……)还要再抄。所以先收拢:

- `domain/capabilities`:**每项宿主能力登记一份契约** —— 名字、输入输出(JSON Schema,含文件进出)、只给宿主调还是
  也给智能体 / 工作流、要不要流式进度、**挑谁的规矩**(只用自己的连接 / 云端要显式默认 / 失败了回落到内置)、
  出错时各说什么下一步。
- **内置实现也是提供方**:本地解析登记成 `builtin:local`,和插件的连接放在同一个候选表里。调用方只写
  `capabilities.run("document_parse", user, asset, …)`,不关心是内置的还是哪个插件 —— 以后把本地解析拆成插件,
  调用方一行不改。
- 清单校验、「设置 → 默认提供方」(一页列所有能力:素材外链、文档解析……,每项选一个)、插件页的「它提供了什么」
  都从这张表生成。`public_url` 和 `generation` 迁到这张表上(行为不变,数据由迁移搬)。
- 插件文档里「替宿主做成什么」改成按能力列契约,新增能力只加一份契约,不改插件层。

## 分步落地(提议)

1. **文档素材**:`document` 种类、白名单判种类、迁移改回错判的、缩略图 / 页数、素材库筛选、前端上传认这些格式。
2. **能力表**:`domain/capabilities`,把 `public_url`、`generation` 搬上去;「设置 → 默认提供方」。
3. **本地解析 + 派生物**:`asset_extractions`、`document_parse` 任务、markitdown + pypdfium2、页面图。
4. **智能体读文档**:`read_document`、`view_document_pages`、附件进上下文的规则;工作流节点;画板文档格喂全文;存成笔记。
5. **MinerU 插件**:云端 + 自建两种连接,选项、进度、结果交回;「用 MinerU 重新解析」。
