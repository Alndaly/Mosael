import { Info } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Hint } from "@/components/ui/tooltip";
import { navigationBridge, useComfyNavigation, type ComfyNavigation } from "@/features/plugins/comfyNavigation";
import { cn } from "@/lib/utils";

/**
 * 内嵌 ComfyUI 画布的操控方式:「触控板 / 鼠标」两格(见 comfyNavigation)。挂在内嵌浏览器的顶栏(「在编辑器里打开」那个视图)
 * 和工作台的顶栏上。只在 Mosael 里这个视图生效 —— 说明里写着,免得以为改了那台 ComfyUI 的设置。
 *
 * 这版 ComfyUI 前端没有这个设置时开关藏起来,留一个说明为什么的小图标。
 */
export function ComfyNavigationSwitch({ connectionId, className }: { connectionId: string; className?: string }) {
  const t = useI18n();
  const { mode, choose, supported } = useComfyNavigation(connectionId);
  if (!navigationBridge()) return null;
  if (supported === false) {
    return (
      <Hint label={t("comfyNavigationUnsupported")}>
        <span
          role="note"
          aria-label={t("comfyNavigationUnsupported")}
          className={cn("[-webkit-app-region:no-drag] inline-flex size-7 shrink-0 items-center justify-center text-muted-foreground", className)}
        >
          <Info size={14} aria-hidden />
        </span>
      </Hint>
    );
  }
  const options: { value: ComfyNavigation; label: string }[] = [
    { value: "trackpad", label: t("comfyNavigationTrackpad") },
    { value: "mouse", label: t("comfyNavigationMouse") },
  ];
  return (
    <Hint label={t("comfyNavigationHint")}>
      <div
        role="radiogroup"
        aria-label={t("comfyNavigation")}
        className={cn(
          "[-webkit-app-region:no-drag] inline-flex h-7 shrink-0 items-center gap-0.5 rounded-md border border-border p-0.5",
          className,
        )}
      >
        {options.map((one) => (
          <button
            key={one.value}
            type="button"
            role="radio"
            aria-checked={mode === one.value}
            className={cn(
              "inline-flex h-full cursor-pointer items-center whitespace-nowrap rounded-[5px] border-0 px-2 text-ui-xs",
              mode === one.value ? "bg-accent text-primary" : "bg-transparent text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
            onClick={() => choose(one.value)}
          >
            {one.label}
          </button>
        ))}
      </div>
    </Hint>
  );
}
