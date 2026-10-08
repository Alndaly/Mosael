
import { createRoot } from "react-dom/client";

import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
// WenKai is also available as a global interface font in Appearance.
import "lxgw-wenkai-screen-webfont/lxgwwenkaigbscreen.css";
// 第三方组件的样式表(React Flow 等)**不在这里 import**:JS 里 import 的 CSS 不分层,会压过
// 我们所有的工具类。它们在 tokens.css 里以 `layer(vendor)` 引入 —— 那里有完整的说明。
import "@/design/tokens.css";
import "./styles.css";
import { AppBoundary } from "@/app/PageBoundary";
import { loadStartupMessages } from "@/app/preferences";
import { runLocalMigrations } from "@/lib/localMigrations";
import { captureInviteFromLocation, listenInviteDeepLinks } from "@/lib/inviteLinks";
import { installSaveShortcut } from "@/lib/saveShortcut";
import { installWindowChrome } from "@/lib/windowChrome";

// 本机存的设置先迁到新形状,再渲染:界面只认新形状(见 lib/localMigrations)
runLocalMigrations();
installWindowChrome();
// ⌘S 全应用一个行为:能存就存,不能存也不让浏览器弹「存储网页」(见 lib/saveShortcut)
installSaveShortcut();
// 打开的是一张邀请链接(`#/join/<码>`,ADR 0054):先把码收起来、地址换回首页,再让路由读地址。桌面端的深链在登录前也要接得住。
captureInviteFromLocation();
listenInviteDeepLinks();
// 外壳和当前语言的文案表并行取(文案表按语言分块,只取用得到的那一种,见 app/messageTables),都到了才画。
void Promise.all([import("@/app/App"), loadStartupMessages()]).then(([{ App }]) => {
  createRoot(document.getElementById("root")!).render(
    <AppBoundary>
      <App />
    </AppBoundary>,
  );
});
