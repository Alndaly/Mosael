import React from "react";

import { messagesFor } from "@/app/messageTables";
import { PreferencesContext } from "@/app/preferencesContext";

/**
 * 弹窗、侧板右上角那颗 × 给读屏的名字。此前写死成英文的 "Close",中文界面里读屏念英文。
 *
 * 读的是偏好的 context 本身,不走 useI18n:没挂偏好的地方(组件测试、偏好就位之前)useI18n 会抛错,
 * 而弹窗到处都有 —— 那时按默认的界面语言(中文)说。文案表按语言分块、启动时先取好(见 app/messageTables),
 * 这里不静态引整份 `app/messages`,免得把两种语言的正文拖进首屏。
 */
export function useCloseLabel(): string {
  const preferences = React.useContext(PreferencesContext);
  return preferences ? preferences.t("close") : messagesFor("zh-CN").close;
}
