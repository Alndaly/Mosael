export const desktop = {
  // ---- i18n 分区 F3(Electron 桌面壳):这一批新加的 key 放在这行下面 ----
  // 开发时主进程过期的提示(见 features/desktop/MainStaleNotice)。
  mainStaleText: "主进程代码已更新,重启后生效",
  mainStaleManual: "主进程代码已更新,重启 Mosael 后生效",
  mainStaleRestart: "重启",
  mainStaleDismiss: "先不重启",
  mainStaleFiles: "变了的:{files}",
  mainStaleBadgeHint: "点一下就重启,vite 和后端不受影响",
  mainStaleCannotRestart: "这次不是经 pnpm dev 拉起的,没法替你重启",
  // 路径格旁边的「选择…」:系统的选文件 / 选文件夹对话框(见 components/settings/PathField)。
  pathFieldChoose: "选择…",
  pathFieldChooseLabel: "选择「{label}」",
  // 外部打开的文件(「打开方式」/ 拖到图标上)怎么处理,见 app/preferencesContext 的 ExternalOpenBehavior。
  // 说明里**必须写清「打开预览」也会入库** —— 渲染层没法直接预览不在库里的本地文件,那条路的前半段就是入库。
  settingsExternalOpen: "打开外部文件",
  settingsExternalOpenDesc:
    "从访达 / 资源管理器的「打开方式」、或拖到程序坞 / 任务栏图标上的文件怎么办。入库:导入素材库后就停在那儿(此前的行为)。打开预览:同样导入,再多开一次预览 —— 文件仍然进了素材库;音频没有预览,只导入。改完从下一个打开的文件起生效。",
  settingsExternalOpenImport: "入库",
  settingsExternalOpenPreview: "打开预览",
} as const;
