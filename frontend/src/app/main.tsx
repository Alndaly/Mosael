
import { createRoot } from "react-dom/client";

import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
// Retain the bundled poem typeface for custom CSS; UI uses the native Chinese sans stack.
import "lxgw-wenkai-screen-webfont/lxgwwenkaigbscreen.css";
import "@/design/tokens.css";
import "./styles.css";
import { installWindowChrome } from "@/lib/windowChrome";

installWindowChrome();
void import("@/app/App").then(({ App }) => {
  createRoot(document.getElementById("root")!).render(<App />);
});
