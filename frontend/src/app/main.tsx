
import { createRoot } from "react-dom/client";

import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
// 中文界面字体:霞鹜文楷屏显版。取 gb(国标简体字集)而非全字集 —— 4.5MB vs 5.0MB,而本应用
// 是简体界面。这个包按 unicode-range 切了 97 片,运行时只加载实际出现的字形所在分片,不是一次
// 吞下整个字体。打进包而非依赖系统安装,换设备观感才一致。拉丁字符仍由 Inter 命中,见 tokens.css。
import "lxgw-wenkai-screen-webfont/lxgwwenkaigbscreen.css";
import "@/design/tokens.css";
import "./styles.css";
import { migrateLegacyLocalStorage } from "@/app/legacyStorage";
import { installWindowChrome } from "@/lib/windowChrome";

migrateLegacyLocalStorage(window.localStorage);
installWindowChrome();

// App and its API singletons are loaded only after the storage keys have moved. Static imports are
// evaluated before this module body, which would make the first upgraded launch read empty new keys.
void import("@/app/App").then(({ App }) => {
  createRoot(document.getElementById("root")!).render(<App />);
});
