/**
 * 一格本机路径(文件夹或文件):可以直接敲;桌面版连着本机后端时旁边多一个「选择…」,弹系统的选文件 / 选文件夹对话框,
 * 从格子里现在的值开始。选中的路径和敲进去的一样交给 `onChange` —— 后面怎么检查、确认,不因为是选的而不同。
 *
 * **只有路径对后端有意义时才给按钮**:选出来的是这台电脑上的路径。网页版没有系统对话框;桌面版连着别处的服务器
 * (登录页 / 设置里的服务器切换)时,这台电脑上的路径在那台机器上不存在 —— 这两种只留输入框。
 */
import React from "react";
import { toast } from "sonner";

import { isCustomServer } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** 能弹系统对话框、而且选出来的路径后端用得上时,就是那个对话框;否则 undefined(只给输入框)。 */
export function localPathPicker(): ((request: PickPathRequest) => Promise<string | null>) | undefined {
  if (typeof window === "undefined" || isCustomServer()) return undefined;
  return window.mosaelDesktop?.pickPath;
}

export function PathField({
  kind,
  label,
  value,
  onChange,
  placeholder,
  autoFocus,
  filters,
}: {
  kind: PickPathRequest["kind"];
  /** 这一格的名字:输入框的无障碍名,也是对话框的标题。 */
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  filters?: PickPathRequest["filters"];
}) {
  const t = useI18n();
  const pick = localPathPicker();
  const [picking, setPicking] = React.useState(false);

  const choose = async () => {
    if (!pick) return;
    setPicking(true);
    try {
      const picked = await pick({ kind, title: label, defaultPath: value.trim() || undefined, filters });
      if (picked) onChange(picked);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setPicking(false);
    }
  };

  return (
    <div className={cn(SETTINGS_FIELD_WIDTH, "flex items-center gap-2")}>
      <Input
        className="min-w-0 flex-1"
        aria-label={label}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
        autoFocus={autoFocus}
      />
      {pick && (
        <Button
          variant="outline"
          className="shrink-0"
          aria-label={t("pathFieldChooseLabel").replace("{label}", label)}
          loading={picking}
          onClick={() => void choose()}
        >
          {t("pathFieldChoose")}
        </Button>
      )}
    </div>
  );
}
