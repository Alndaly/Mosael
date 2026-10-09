import * as React from "react";
import { ChevronDown, Mouse, Touchpad } from "lucide-react";

import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import type { CanvasInputMode } from "@/components/app/canvasInputMode";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { StepNativeViewAside } from "@/components/ui/nativeViewAside";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const MODES: { value: CanvasInputMode; icon: typeof Touchpad; label: MessageKey; description: MessageKey }[] = [
  { value: "trackpad", icon: Touchpad, label: "canvasInputTrackpad", description: "canvasInputTrackpadDesc" },
  { value: "mouse", icon: Mouse, label: "canvasInputMouse", description: "canvasInputMouseDesc" },
];

/**
 * 画布怎么操控(触控板 / 鼠标)的**那一个**样子:一颗小图标按钮,图标是现在这一种,旁边一个小下拉箭头;点开是两项的菜单,
 * 每项有图标、名字和一句说明,现在那一项打勾。按钮上的说明写「画布操控方式:现在是 X」。
 *
 * 此前同一件事有两种做法:ComfyUI 工作台顶栏是一段「触控板 | 鼠标」分段控件,在「保存」「运行」旁边占了一大块;画板、
 * 工作流、3D 场景是一颗点一下就切换的图标按钮,看不出现在是哪种、点了会变成哪种。存储照旧各走各的(工作台的只对那个连接,
 * 其余是全局的 canvasInputMode,见两个包装:CanvasInputModeSwitch、ComfyNavigationSwitch),这里只管外观和交互。
 * 棘轮:`design/canvasInputMode.test.ts` —— 四处都用它,不再出第三种写法。
 *
 * - 菜单从 portal 出去,不在画布里;按钮带 `nodrag nopan nowheel`,在画布的工具条上点它不会拖动 / 平移 / 缩放画布。
 * - 键盘:按钮上回车 / 空格打开,方向键在两项间走,回车选,Esc 关(焦点回到按钮)。
 * - `overNativeView`:按钮在内嵌网页的外壳上(工作台的顶栏、内嵌浏览器的顶栏),菜单会落在原生网页视图上 —— 原生视图盖在一切
 *   DOM 上,菜单开着时请它让开(先铺一张冻结的画面,见 nativeViewAside),和工作台里打开的弹窗同一个做法。
 * - `disabledReason`:切不了(这版 ComfyUI 前端没有这个设置)时按钮禁用,说明里写为什么。
 */
export function CanvasInputModeMenu({
  mode,
  onChange,
  size = "sm",
  scope,
  descriptions,
  disabledReason,
  overNativeView = false,
  variant = "ghost",
  labeled = false,
  className,
}: {
  mode: CanvasInputMode;
  onChange: (mode: CanvasInputMode) => void;
  /** 和它挨着的那一排控件同高:工具条、工作台顶栏 32px(sm),内嵌浏览器顶栏 28px(xs)。 */
  size?: "xs" | "sm";
  /** 说明的第二行:这个设置管到哪(全局 / 只这个连接)。 */
  scope?: string;
  /** 换掉某一项的说明(3D 场景里鼠标是拖动旋转,不是平移)。 */
  descriptions?: Partial<Record<CanvasInputMode, string>>;
  disabledReason?: string | null;
  overNativeView?: boolean;
  /** 挨着的那排是什么,它就是什么:画布工具条、内嵌浏览器顶栏的图标堆用 ghost(默认);
      工作台顶栏挨着「保存」「运行」那两颗带框的,用 outline。 */
  variant?: "ghost" | "outline";
  /** 图标旁边写上现在那一种的名字(「触控板 / 鼠标」):挨着「图标+文字」的按钮排时用,
      画布上的图标堆里照旧只给图标。 */
  labeled?: boolean;
  className?: string;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const current = MODES.find((one) => one.value === mode) ?? MODES[0];
  const Icon = current.icon;
  const label = disabledReason ? t("canvasInputMode") : t("canvasInputCurrent").replace("{mode}", t(current.label));
  return (
    <Popover open={open && !disabledReason} onOpenChange={setOpen}>
      {labeled ? (
        //: 悬停说明在最外层:PopoverTrigger(asChild)的直接孩子必须是能接 ref 的按钮,Hint 隔着就收不到点击。
        <Hint label={label} hint={disabledReason ? null : scope} disabledReason={disabledReason ? disabledReason : undefined}>
          <PopoverTrigger asChild>
            <Button
              variant={variant}
              size={size}
              disabled={Boolean(disabledReason)}
              aria-haspopup="menu"
              data-canvas-input-trigger=""
              data-canvas-input-mode={mode}
              className={cn("nodrag nopan nowheel [-webkit-app-region:no-drag] shrink-0", className)}
            >
              <Icon aria-hidden />
              {t(current.label)}
              <ChevronDown aria-hidden className="size-3! opacity-70" />
            </Button>
          </PopoverTrigger>
        </Hint>
      ) : (
        <PopoverTrigger asChild>
          <IconButton
            variant={variant}
            size={size}
            label={label}
            hint={disabledReason ? null : scope}
            disabled={Boolean(disabledReason)}
            disabledReason={disabledReason}
            aria-haspopup="menu"
            data-canvas-input-trigger=""
            data-canvas-input-mode={mode}
            className={cn(
              //: 和工具条上别的图标同一个颜色(此前那颗是次要色,比旁边的图标淡一截,像是点不了);下拉箭头淡一档,主次在图标上
              "nodrag nopan nowheel [-webkit-app-region:no-drag] shrink-0 gap-0.5 px-1.5",
              className,
            )}
          >
            <Icon aria-hidden />
            <ChevronDown aria-hidden className="size-3! opacity-70" />
          </IconButton>
        </PopoverTrigger>
      )}
      <MenuContent label={t("canvasInputMode")} align="end" className="nodrag nopan nowheel">
        {overNativeView && <StepNativeViewAside />}
        {MODES.map((one) => (
          <MenuItem
            key={one.value}
            role="menuitemradio"
            data-canvas-input-option={one.value}
            checked={one.value === mode}
            icon={<one.icon />}
            label={t(one.label)}
            description={descriptions?.[one.value] ?? t(one.description)}
            onClick={() => {
              onChange(one.value);
              setOpen(false);
            }}
          />
        ))}
      </MenuContent>
    </Popover>
  );
}
