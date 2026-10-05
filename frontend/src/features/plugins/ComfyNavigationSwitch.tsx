import { Info } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { CONTROL_HEIGHT, CONTROL_SQUARE } from "@/components/ui/control-size";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { Hint } from "@/components/ui/tooltip";
import { navigationBridge, useComfyNavigation, type ComfyNavigation } from "@/features/plugins/comfyNavigation";
import { cn } from "@/lib/utils";

/**
 * 两档:和它挨着的那一排控件同高、同字号 —— 工作台的顶栏是 `sm`(32px,和「保存」「运行」一样),内嵌浏览器的顶栏是
 * `xs`(28px,和前进后退、地址栏一样)。分段的样子用全应用那一套(SEGMENTED_LIST / segmentedTriggerClass),外框比
 * 选中的那一格多出 2px 的内边距,所以外框是那一档的高、里面每一格矮 4px。
 */
const SIZES = {
  xs: { list: cn(CONTROL_HEIGHT.xs, "min-h-0 p-0.5"), item: "min-h-0 h-6 px-2 text-ui-xs", icon: CONTROL_SQUARE.xs },
  sm: { list: cn(CONTROL_HEIGHT.sm, "min-h-0 p-0.5"), item: "min-h-0 h-7 px-2.5", icon: CONTROL_SQUARE.sm },
} as const;

/**
 * 内嵌 ComfyUI 画布的操控方式:「触控板 / 鼠标」两格(见 comfyNavigation)。挂在内嵌浏览器的顶栏(「在编辑器里打开」那个视图)
 * 和工作台的顶栏上。只在 Mosael 里这个视图生效 —— 说明里写着,免得以为改了那台 ComfyUI 的设置。
 *
 * 这版 ComfyUI 前端没有这个设置时开关藏起来,留一个说明为什么的小图标。
 */
export function ComfyNavigationSwitch({
  connectionId,
  size = "sm",
  className,
}: {
  connectionId: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const t = useI18n();
  const { mode, choose, supported } = useComfyNavigation(connectionId);
  if (!navigationBridge()) return null;
  const scale = SIZES[size];
  if (supported === false) {
    return (
      <Hint label={t("comfyNavigationUnsupported")}>
        <span
          role="note"
          aria-label={t("comfyNavigationUnsupported")}
          className={cn("[-webkit-app-region:no-drag] inline-flex shrink-0 items-center justify-center text-muted-foreground", scale.icon,
                        className)}
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
        data-control-size={size}
        className={cn("[-webkit-app-region:no-drag]", SEGMENTED_LIST, scale.list, className)}
      >
        {options.map((one) => (
          <button
            key={one.value}
            type="button"
            role="radio"
            aria-checked={mode === one.value}
            className={cn(segmentedTriggerClass(mode === one.value), scale.item)}
            onClick={() => choose(one.value)}
          >
            {one.label}
          </button>
        ))}
      </div>
    </Hint>
  );
}
