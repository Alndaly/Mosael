// 内嵌浏览器浮层视图加载的那张页(frontend/float-layer.html):和主窗口同一套字体、样式,
// 主进程把外壳里量好的说明交过来(window.floatLayer.show),这里照原样画出来。见 electron/publish/floatLayer.ts。
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "lxgw-wenkai-screen-webfont/lxgwwenkaigbscreen.css";
import "@/design/tokens.css";
import "@/app/styles.css";
import "./floatLayer.css";

import { clearFloat, showFloat, type FloatPayload } from "./render";

declare global {
  interface Window {
    floatLayer?: { show(payload: FloatPayload): Promise<boolean>; hide(): void };
  }
}

const container = document.getElementById("float")!;

window.floatLayer = {
  show: (payload) => showFloat(document, container, payload),
  hide: () => clearFloat(container),
};
