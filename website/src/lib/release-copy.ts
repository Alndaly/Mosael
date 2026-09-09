/** Bilingual highlights for major releases; publication status always comes from GitHub. */
export const releaseCopy: Record<string, { zh: string[]; en: string[] }> = {
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
