export const desktop = {
  // ---- i18n 分区 F3(Electron 桌面壳):这一批新加的 key 放在这行下面 ----
  // 开发时主进程过期的提示(见 features/desktop/MainStaleNotice)。
  mainStaleText: "The main process code changed; restart to apply it",
  mainStaleManual: "The main process code changed; restart Mosael to apply it",
  mainStaleRestart: "Restart",
  mainStaleDismiss: "Not now",
  mainStaleFiles: "Changed: {files}",
  mainStaleBadgeHint: "Click to restart; vite and the backend keep running",
  mainStaleCannotRestart: "Mosael wasn't started by pnpm dev, so it can't restart itself",
} as const;
