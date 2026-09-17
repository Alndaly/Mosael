/** Bilingual highlights for major releases; publication status always comes from GitHub. */
export const releaseCopy: Record<string, { zh: string[]; en: string[] }> = {
  "v1.4.0": {
    zh: ["新增官方工作流「视频译配 · 字幕与配音」：逐句转写、逐句翻译、按**原时间码**铺译文字幕，再逐条配音并变速压回原段落长度；原声保留在自己的轨上，只是被压低。", "字幕配音也能在对话里让智能体做，确认卡会写清这一步影响几条字幕、会不会压回原长度、原声动不动 —— 它是花钱的动作。", "新增降噪：内置引擎先量噪声再下手，去掉底噪不动音乐；嘈杂环境可选人声提取。素材库、剪辑台、工作流节点和智能体都能用，产出新素材、原片不动。", "新增人声与背景音分离：素材库、剪辑台、工作流节点和智能体共用一个能力，产出两份新素材，原片不动；译配模板靠它只静音人声、保住背景音乐。", "设置页按用途重新分组；AI Studio 新增「音频」页做语音和播客；给字幕配音搬进剪辑台的「配音」页，范围跟着时间线选中走。", "3D 场景卡片有了缩略图：从场景数据直出的俯视平面，场景一改缩略图跟着变，不是一张会和数据脱节的截图。", "目录认不出的模型，参数可以自己写下来：手填的别名、经中转配的同一个模型，此前在生成界面上一个参数都没有；现在按能力分别指一份参数组，而且认不出时界面会说出这条通道发得出哪几项，不再沉默。", "修复配音压不住原声 —— 成片里两个人同时说话。原片在视频轨上时，闪避从来没生效过（实测 −0.03 dB，修后 −10.35 dB）。"],
    en: ["New official workflow \u201cTranslated dubbing with subtitles\u201d: transcribe and translate line by line, lay subtitles on the **original** timecodes, then dub each line and time-compress it back into its own slot. The original audio stays on its track, only ducked.", "The agent can dub subtitles from a conversation too. The confirmation card now states how many subtitles are affected, whether the dub is compressed back to length, and that the original audio is untouched \u2014 it is a paid action.", "New noise reduction: the built-in engine measures the noise before it acts and removes background hiss without touching music; voice isolation handles noisy rooms. Available from the media library, the editor, a workflow node and the agent, always as a new asset.", "New voice / background separation: the media library, editor, workflow node and agent share one capability that produces two new assets and leaves the source untouched; the dubbing template uses it to mute only the voice and keep the music.", "Settings are regrouped by purpose; AI Studio gains an Audio tab for speech and podcasts; subtitle dubbing moves to the editor\u2019s Voice tab and follows the timeline selection.", "3D scene cards have thumbnails: a top-down plan drawn from the scene data itself, so it follows edits instead of drifting from a stale screenshot.", "Models the built-in catalog does not recognise can now carry parameters you write yourself: hand-typed aliases and the same model behind a relay used to show no parameters at all. Point each capability at a parameter set \u2014 and when a model is unrecognised the screen now says which fields that channel can send instead of staying silent.", "Fixed dubbing failing to duck the original \u2014 two people talking at once in the export. When the source sits on a video track, ducking never applied (measured \u22120.03 dB; \u221210.35 dB after the fix)."],
  },
  "v1.3.1": {
    zh: ["智能体对话框支持 `@` 引用素材、笔记、画板与工作流：正文写名字，id 走结构化字段；发出去仍是可点开的胶囊。", "思考档位按供应商查表：关不掉的模型不再给「关闭」，发不出档位的连接说得出原因。", "修复深色下菜单分组线与页面同色而看不见 —— 菜单、命令面板、通知与任务面板一并恢复。", "生成页「引擎参数」重排为引擎／出片规格／输入素材／调参四块，标题行不再随滚动移出视野。"],
    en: ["The agent composer supports `@` references to assets, notes, boards and workflows: names in the text, ids in structured fields, and clickable chips after sending.", "Thinking levels now come from a per-vendor table: models that cannot stop thinking no longer offer \"Off\", and connections that cannot carry a level say why.", "Fixed menu separators being the same colour as the surface in dark mode — menus, the command palette and the notification and task panels all get their dividers back.", "The generation engine-settings panel is grouped into engine, output, inputs and tuning, with a header that no longer scrolls away."],
  },
  "v1.3.0": {
    zh: ["选项一多的下拉自动带搜索：模型、音色、字体、LUT、发布平台与工作流的上游输出。", "团队讨论改成右侧侧栏，画板与工作流共用；工作流页新增讨论中心。", "「在画布中查看」与加标记会避开右栏面板，不再跳到停靠的智能体底下。", "智能体输入框里的附件与笔记引用收成一排，带缩略图，点开即可预览。"],
    en: ["Long dropdowns now search: models, voices, fonts, LUTs, publishing platforms and upstream workflow outputs.", "Team discussions moved to a right-side sheet, shared by boards and workflows; workflows gained the discussion centre.", "Jumping to a comment or dropping a marker now avoids docked and floating side panels.", "Composer attachments and note references share one row, with thumbnails and click-to-preview."],
  },
  "v1.0.0": {
    zh: ["1.0 正式发布，提供 macOS Apple Silicon 与 Windows x64 安装包。", "统一磨砂界面、剪辑与媒体预览，内置中英文及手写字体。", "整合智能体语音、工作流与定时任务、插件连接和多执行器发布。", "更新 40 篇中英文指南与全部当前界面配图、GIF、录屏，README 加入错层截图展示。"],
    en: ["The stable 1.0 release is available for macOS Apple Silicon and Windows x64.", "Unified frosted interface, rebuilt editing and media previews, and bundled multilingual and handwritten fonts.", "Includes agent voice, workflows and scheduling, plugin connections and multi-worker publishing.", "Refreshed 40 bilingual guides and all current captures, GIFs and recordings, with a layered README showcase."],
  },
  "v1.0.0-beta5": {
    zh: ["统一半透明模糊弹窗与菜单，柔化边界，适配自定义背景。", "重构剪辑工作区与音视频预览，修复长标题、画布菜单定位和可视区域居中。", "新增全局中英文字体，包含 Caveat 与 Kalam 手写风格。", "全面更新中英文文档与明暗主题实拍，新增外观、定时任务指南和可暂停录屏。"],
    en: ["Unified frosted dialogs and menus, softened boundaries and preserved custom backgrounds.", "Rebuilt the editor and media previews; fixed long titles, canvas menus and visible-area centering.", "Added global Chinese/English font combinations, including Caveat and Kalam handwriting.", "Refreshed bilingual guides and light/dark captures, with Appearance and Scheduled Tasks guides and controllable recordings."],
  },
  "v1.0.0-beta4": {
    zh: ["修复百度网盘导入、上传时缺少工作区的问题，完善插件授权与参数说明。", "新增听写、语音回复和可打断的免提对话。", "修复任务取消、嵌套工作流、执行器失联，以及剪辑预览与导出不一致的问题。", "代码节点改用 Docker 隔离；自定义外部执行器需要升级租约协议。"],
    en: ["Fixed missing workspace context in Baidu Netdisk imports and uploads, plus plugin authorization and parameter descriptions.", "Added dictation, spoken replies and interruptible hands-free conversations.", "Fixed task cancellation, nested workflows, lost workers and differences between editor preview and export.", "Code nodes now require Docker isolation. Custom external workers must adopt the lease protocol."],
  },
  "v1.0.0-beta2": {
    zh: ["新增屏幕与摄像头同步录制、系统音频采集和悬浮录制控制。", "新增片段遮罩、投影、数据备份与诊断。", "加入工作流社区、完整视频生成与口播整理模板，以及逐节点运行历史。"],
    en: ["Added synchronized screen and camera recording, system audio and a floating recording controller.", "Added clip masks, shadows, data backup and diagnostics.", "Introduced workflow templates for video generation and transcript cleanup, plus per-node execution history."],
  },
  "v1.0.0-beta1": {
    zh: ["统一旧数据升级策略，改进画板自动保存与冲突处理。", "扩展发布检查，覆盖浏览器扩展和中英文官网。", "预发版独立标记，不替换最新正式版。"],
    en: ["Unified data upgrade handling and improved canvas autosave and conflict recovery.", "Extended release checks to cover the browser extension and bilingual website.", "Marked beta releases separately without replacing the latest stable release."],
  },
};
