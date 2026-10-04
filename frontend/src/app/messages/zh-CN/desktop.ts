export const desktop = {
  // ---- i18n 分区 F3(Electron 桌面壳):这一批新加的 key 放在这行下面 ----
  // 开发时主进程过期的提示(见 features/desktop/MainStaleNotice)。
  mainStaleText: "主进程代码已更新,重启后生效",
  mainStaleManual: "主进程代码已更新,重启 Mosael 后生效",
  mainStaleRestart: "重启",
  mainStaleDismiss: "先不重启",
  mainStaleFiles: "变了的:{files}",
} as const;
