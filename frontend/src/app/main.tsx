import { createRoot } from "react-dom/client";

import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
// 中文正文字体:思源黑体(Noto Sans SC),取代系统 PingFang 回退。只引 regular/medium 两个
// 字重控制体积;fontsource 按 unicode-range 拆包,浏览器只下载用到的子集。
import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-sans-sc/500.css";
import "@/design/tokens.css";
import "./styles.css";
import { App } from "@/app/App";

createRoot(document.getElementById("root")!).render(<App />);
