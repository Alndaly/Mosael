export const community = {
  // ---- i18n 分区 F4(社区,ADR 0026):这一批新加的 key 放在这行下面 ----
  // 社区分享的「在 Mosael 中打开」:预览再导入(深链 mosael://import?share=…)。
  shareImportTitle: "导入社区分享",
  shareImportLoading: "正在读取分享…",
  shareImportAuthor: "作者",
  shareImportKind: "类型",
  shareImportSize: "大小",
  shareImportKindWorkflow: "工作流",
  shareImportKindBoard: "画板",
  shareImportDownloads: "已被下载 {n} 次",
  shareImportConfirm: "导入到工作区",
  shareImportImporting: "正在导入…",
  shareImportFailed: "读取分享失败",
  shareImportNotFound: "这个分享不存在或已被删除。",
  shareImportNotFoundFix: "检查链接是否完整;也可以到官网社区重新找一份。",
  shareImportOffline: "连不上 MosaelCloud。",
  shareImportOfflineFix: "检查网络或代理后重试。",
  shareImportInvalid: "这份内容不是可用的工作流分享。",
  shareImportInvalidFix: "确认链接来自工作流分享;画板分享目前不支持自动导入，可以在官网直接下载文件。",
  shareImportOtherFix: "稍后重试;一直不行就到官网直接下载文件，再在工作流页手动导入。",
  shareImportBoardUnsupported: "画板分享暂不支持自动导入。先在官网下载文件，再到画板页手动导入。",
  shareImportDone: "已导入「{name}」。",
} as const;
