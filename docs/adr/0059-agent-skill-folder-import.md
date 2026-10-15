# ADR 0059:照别家规范写的技能文件夹直接导入;对话里附上的压缩包 / 文件夹由后端解开分流

## Status

Accepted — 2026-10-14。维护者拍板:别家规范(OpenAI Codex 的技能约定)写的技能文件夹应该**原样**拖进来就能用,
不改 SKILL.md;对话输入框里附上的压缩包 / 文件夹不该在浏览器里瞎猜,交给后端解开、认出是什么、各走各的路。

## Context

技能是带 `SKILL.md` 的文件夹(ADR 0040)。在此之前只有一条入口:设置页选 zip 压缩包,后端解开、暂存、人审完才装。
两个缺口:

1. **别家规范的技能**。OpenAI Codex 的约定里,技能文件夹里有一份 `agents/openai.yaml`(`interface` 下写显示名、
   短说明、默认开场话),SKILL.md 里没有 Mosael 自己的 `metadata.mosael-title`。原样拿进来,目录里整排都是目录名
   而不是人起的显示名。
2. **对话里附上的压缩包 / 文件夹**。输入框只认散文件:图片、音视频、文档进素材库,文本读进上下文,压缩包直接拒绝。
   人手里现成的东西(技能压缩包、一文件夹的参考资料)要先自己解开、拣出要的、一个个附,才说得清一件事。

浏览器也不是解包的地方:压缩炸弹、路径穿越、符号链接、系统垃圾(`__MACOSX`、`.DS_Store`)的防线如果在前端
再写一份,和后端那份迟早不一致。

## Decision

### 1. 解包只在一处,技能导入和对话附件共用

格式包 `mosael_formats.agent_skill` 把解 zip 抽成两个函数,两处调用方(技能导入、对话附件)挡的是**同一套**:

- `read_archive_files(data)` → `{路径: 内容}`:成员数封顶(`MAX_SKILL_FILES × MAX_SKILLS_PER_IMPORT`)、总字节封顶
  (`MAX_IMPORT_UPLOAD_BYTES`,20MB)、路径穿越(`../`、绝对路径)和符号链接成员直接拒绝;
- `clean_files(files)`:规整路径、丢掉系统垃圾 —— 垃圾单子是 `JUNK_NAMES`(`.DS_Store`、`Thumbs.db`、`desktop.ini`)/
  `JUNK_DIRS`(`__MACOSX`、`.git`)/ `._` 开头的 AppleDouble;
- `contains_skill(files)`:里面**任何一个地方**有 `SKILL.md` 就算技能包 —— 分流只看这一条。

文件夹走平行的第二条路:浏览器把每个文件连同相对路径(从最顶上那层文件夹名开始,像 `webkitRelativePath`)传上来,
后端 `_read_folder` 按同序的两列收,总字节和个数同一组上限。前端在 `lib/folderFiles.ts` 先按同一张垃圾单子丢一遍
系统垃圾、先量一遍总量(超了不传,不让人传完 20MB 才被拒)。

### 2. `agents/openai.yaml` 只出显示名,不改 SKILL.md

`read_agent_interface(data)` 读 `agents/openai.yaml` 的 `interface` 三项,和 SKILL.md 的头**同一套 YAML 子集**
(同样挡锚点、别名);读不出来、写得不对就是空的 —— 一个技能不能因为它导不进来。

显示名一处定(`catalog` 的 `display_name_of` / `SkillDoc.display_title`):SKILL.md 的 `metadata.mosael-title` 优先,
没写用 `agents/openai.yaml` 的 `interface.display_name`,都没有是文件夹名。目录、设置页、导入预览、对话里的
「发现 N 个技能」卡用的都是这一个。**SKILL.md 一个字不动**:导入原样落地,别家的技能升了级照样原样覆盖。

### 3. 新接口 `POST /workspaces/{id}/agent-bundles`

对话输入框附上的一个 `.zip`(`archive` 字段)或一个文件夹(`files` + 同序 `paths`,`source_name` 是包名 / 文件夹名)。
同步端点:解包、入库都不在事件循环上做。返回 `AgentBundleOut{source_name, skill_import, assets, skipped}`:

- **有 SKILL.md → 走技能导入的同一套**:`skills.use_cases.stage_import` 暂存,回暂存 id 和全文,什么都还没装。
  对话里出一张「发现 N 个技能,安装到工作区?」的卡,点开是**设置页同一个**导入审阅(SkillImportDialog,
  同一份暂存、同一套校验和撞名处理),人看过全文、点了才装;「忽略」只是收起卡。不另写一套校验和审阅。
- **不是技能包 → 图片进素材库、文本合订成一份 Markdown 进素材库**:
  - 图片(按内容判 mime,`image/*`,SVG 除外 —— 它是文字)一张张进素材库,和 📎 附图片同一条路,上限 20 张
    (`MAX_BUNDLE_IMAGES`);
  - 文本文件(按内容判 `is_text`,不按扩展名)按包里的路径排好,**合订成一份 Markdown 文档**进素材库:开头一张目录,
    每个文件一节、标题是包里的路径、内容原样放在比内容里最长一串反引号再长一截的围栏里。这和附一份 .md 同一条路:
    后端本地解析,短的全文、长的按目录放进上下文,智能体用 `read_document` 按段读。上限 `MAX_BUNDLE_TEXT_FILES`
    (= `MAX_SKILL_FILES`,200 个),单个文件上限 `MAX_FILE_BYTES`(2MB);
  - 其余(二进制、太大、超个数)不收,逐个列为 `skipped`(`unsupported` / `too_large` / `too_many`),前端在输入卡里
    逐个列出是哪个、为什么 —— 不静默丢掉;合订本末尾也写一句,模型知道少了什么。

前端这一半(`composerAttachments` / `ComposerAttachMenu` / `ComposerBundleNotes`):📎 变成两行的菜单(「文件…」/
「文件夹…」,浏览器选择框一次只能选一种);拖进来的文件夹在 drop 那一刻用 `webkitGetAsEntry` 一层层读出来
(事件一过 items 就作废);三个入口(选 / 拖 / 粘贴)汇进同一个 accept,压缩包照走。进了素材库的出现在附件条
(随消息发出);「没收的文件」卡是这条消息的事,发出去 / 换一处就收起;「发现技能」的卡留着,直到装了或点忽略 ——
先说一句「装好后帮我…」再去装是常有的事。

### 4. 测试夹具用维护者的两个真技能

`backend/tests/test_agent_skill_folder_import.py` 的夹具是维护者的两个真技能,文件夹名**照原样**带中文和空格 —
— 路径里非 ASCII、带空格的输入从测试第一天就是常态,不是事后补的兼容。

## Consequences

- 别家规范(Codex)的技能:拖进对话或选进设置页,显示名对、全文可审、原样落地;升自己的级不用先过 Mosael 的格式。
- 对话附件多了一条会「消化」的入口:压缩包 / 文件夹不再是「读不了」,但消化的结果有三种,其中两种(技能、
  合订本)是素材库 / 技能目录里的新东西 —— 发消息之前那张卡和那条附件条是它们唯一的露面处。
- 解包防线在格式包一处,以后加第三条消费压缩包的路(备份恢复?批量素材?)直接调 `read_archive_files` /
  `clean_files`,不存在「前端那份忘了挡」的问题。
- 不支持 rar / 7z:浏览器和后端都没有现成的解法,技能导入也只认 zip;要看得先解成 zip 或文件夹。
- 非技能包里超过 20 张图 / 200 个文本文件的部分被「too_many」拒掉 —— 整个仓库那种该让智能体自己去读,不是一口
  塞进对话。
