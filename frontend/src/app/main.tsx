
import { createRoot } from "react-dom/client";

import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
// WenKai is also available as a global interface font in Appearance.
import "lxgw-wenkai-screen-webfont/lxgwwenkaigbscreen.css";
// 第三方组件的样式表(React Flow 等)**不在这里 import**:JS 里 import 的 CSS 不分层,会压过
// 我们所有的工具类。它们在 tokens.css 里以 `layer(vendor)` 引入 —— 那里有完整的说明。
import "@/design/tokens.css";
import "./styles.css";
import { installWindowChrome } from "@/lib/windowChrome";

installWindowChrome();
void import("@/app/App").then(({ App }) => {
  createRoot(document.getElementById("root")!).render(<App />);
});
