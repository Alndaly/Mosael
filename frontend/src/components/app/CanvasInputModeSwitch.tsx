import { Mouse, Touchpad } from "lucide-react";
import { usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { useCanvasInputMode } from "./canvasInputMode";

/** One click switches navigation without opening a menu over the canvas. */
export function CanvasInputModeSwitch() {
  const [mode, setMode] = useCanvasInputMode();
  const { locale } = usePreferences();
  const trackpad = mode === "trackpad";
  const label =
    locale === "en-US"
      ? trackpad
        ? "Trackpad mode · Switch to mouse"
        : "Mouse mode · Switch to trackpad"
      : trackpad
        ? "触控板模式 · 点击切换为鼠标"
        : "鼠标模式 · 点击切换为触控板";
  const Icon = trackpad ? Touchpad : Mouse;
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      data-canvas-input-mode={mode}
      aria-label={label}
      title={label}
      onClick={() => setMode(trackpad ? "mouse" : "trackpad")}
      className="nodrag nopan nowheel shrink-0 self-center p-0 text-muted-foreground hover:text-foreground"
    >
      <Icon aria-hidden="true" />
    </Button>
  );
}
