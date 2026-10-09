import { useI18n } from "@/app/preferences";
import { CanvasInputModeMenu } from "@/components/app/CanvasInputModeMenu";
import { navigationBridge, useComfyNavigation } from "@/features/plugins/comfyNavigation";

/**
 * 内嵌 ComfyUI 画布的操控方式(见 comfyNavigation):挂在工作台的顶栏上(ComfyUI 的视图不在工作台里时,挂在内嵌浏览器的顶栏上)。
 * 样子和交互是画布那一份(CanvasInputModeMenu);存储只对这个连接 —— 说明的第二行写着,免得以为改了那台 ComfyUI 的设置。
 *
 * `size` 和挨着的那一排同高:工作台顶栏 `sm`(32px,和「保存」「运行」一样),内嵌浏览器顶栏 `xs`(28px,和前进后退、地址栏一样)。
 * 这版 ComfyUI 前端没有这个设置时按钮禁用,说明里写为什么。
 */
export function ComfyNavigationSwitch({
  connectionId,
  size = "sm",
  variant,
  className,
}: {
  connectionId: string;
  size?: "xs" | "sm";
  variant?: "ghost" | "outline";
  className?: string;
}) {
  const t = useI18n();
  const { mode, choose, supported } = useComfyNavigation(connectionId);
  if (!navigationBridge()) return null;
  return (
    <CanvasInputModeMenu
      mode={mode}
      onChange={choose}
      size={size}
      scope={t("comfyNavigationScope")}
      disabledReason={supported === false ? t("comfyNavigationUnsupported") : null}
      overNativeView
      variant={variant}
      className={className}
    />
  );
}
