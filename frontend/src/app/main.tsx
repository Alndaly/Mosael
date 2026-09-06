
import { createRoot } from "react-dom/client";

import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
// WenKai is also available as a global interface font in Appearance.
import "lxgw-wenkai-screen-webfont/lxgwwenkaigbscreen.css";
import "@/design/tokens.css";
import "./styles.css";
import { installWindowChrome } from "@/lib/windowChrome";

installWindowChrome();
void import("@/app/App").then(({ App }) => {
  createRoot(document.getElementById("root")!).render(<App />);
});
