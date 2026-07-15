import { createRoot } from "react-dom/client";

import "@/design/tokens.css";
import "./styles.css";
import { App } from "@/app/App";

createRoot(document.getElementById("root")!).render(<App />);
