import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

const Select = SelectPrimitive.Root;

/** 空值时必须有占位提醒:调用方没给 placeholder 就用全局默认「请选择」。 */
function SelectValue({ placeholder, ...props }: React.ComponentProps<typeof SelectPrimitive.Value>) {
  const t = useI18n();
  return <SelectPrimitive.Value placeholder={placeholder ?? t("selectPlaceholder")} {...props} />;
}

function SelectTrigger({ className, children, ...props }: React.ComponentProps<typeof SelectPrimitive.Trigger>) {
  return (
    <SelectPrimitive.Trigger
      className={cn(
        "inline-flex h-8 max-w-full min-w-0 items-center justify-between gap-1.5 rounded-md border border-border bg-panel px-2.5 text-[13px]",
        "text-foreground outline-none transition-colors hover:border-border-strong",
        "focus-visible:border-primary data-[placeholder]:text-muted-foreground [&>span]:min-w-0 [&>span]:truncate",
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown size={12} className="shrink-0 text-muted-foreground" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

function SelectContent({ className, children, ...props }: React.ComponentProps<typeof SelectPrimitive.Content>) {
  const t = useI18n();
  // 没有任何可选项时给出空态提示,避免弹出一个空白盒子。
  const empty = React.Children.toArray(children).filter(Boolean).length === 0;
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        position="popper"
        sideOffset={4}
        className={cn(
          "z-[120] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border border-border-strong bg-popover p-1",
          "max-h-[min(280px,var(--radix-select-content-available-height))] overflow-y-auto",
          className,
        )}
        {...props}
      >
        <SelectPrimitive.Viewport>
          {empty ? (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">{t("selectEmpty")}</div>
          ) : (
            children
          )}
        </SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

function SelectItem({ className, children, ...props }: React.ComponentProps<typeof SelectPrimitive.Item>) {
  return (
    <SelectPrimitive.Item
      className={cn(
        "flex cursor-pointer select-none items-center gap-2 rounded-[4px] px-2 py-1.5 text-[13px] text-foreground outline-none",
        "data-[highlighted]:bg-secondary data-[state=checked]:font-semibold",
        className,
      )}
      {...props}
    >
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator className="ml-auto">
        <Check size={12} className="text-primary" />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  );
}

export { Select, SelectContent, SelectItem, SelectTrigger, SelectValue };
