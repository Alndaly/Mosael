
import { createRoot } from "react-dom/client";

import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
// WenKai is also available as a global interface font in Appearance.
import "lxgw-wenkai-screen-webfont/lxgwwenkaigbscreen.css";
// React Flow 的样式表**必须进主包**,不能跟着某一页走。
//
// 它此前只在 WorkflowsView 里 import,而两个画布都用 React Flow(工作流、无限画布)。页面改成
// 按需加载之后,没进过工作流页就永远不会加载它 —— 于是直接打开无限画布时,整个画布没有 React Flow
// 的样式:pane 不成形、拖不动也点不了,右下角那行 "React Flow" 因为失去绝对定位跑到左上角。
// 而"这次有没有进过工作流页"是随机的,所以它表现成"有时候整个画布用不了"。
import "@xyflow/react/dist/style.css";
import "@/design/tokens.css";
import "./styles.css";
import { installWindowChrome } from "@/lib/windowChrome";

installWindowChrome();
void import("@/app/App").then(({ App }) => {
  createRoot(document.getElementById("root")!).render(<App />);
});
