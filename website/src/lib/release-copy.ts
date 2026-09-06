/** Bilingual highlights for major releases; publication status always comes from GitHub. */
export const releaseCopy: Record<string, { zh: string[]; en: string[] }> = {
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
