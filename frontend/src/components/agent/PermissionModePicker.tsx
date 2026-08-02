import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { cn } from "@/lib/utils";

type AgentSession = components["schemas"]["AgentSessionOut"];

export const PERMISSION_MODES = ["manual", "auto", "bypass"] as const;
export type PermissionMode = (typeof PERMISSION_MODES)[number];

/** 当前档位;认不出来的值一律按最保守的那档显示。 */
export function permissionModeOf(session: AgentSession | null | undefined): PermissionMode {
  const value = session?.permission_mode ?? "manual";
  return (PERMISSION_MODES as readonly string[]).includes(value) ? (value as PermissionMode) : "manual";
}

export const PERMISSION_MODE_ICON = {
  manual: ShieldQuestion,
  auto: ShieldCheck,
  bypass: ShieldAlert,
} as const;

/**
 * 这次对话里,哪一类动作智能体可以不问就做。
 *
 * 放在「会话设置」弹层里,和思考档位、分析方式并列 —— 它是每次对话开头定一次的东西。**但非默认
 * 档必须在收起状态下也看得见**:用户不知道自己此刻授权了什么,就等于没有授权。所以设置按钮上挂
 * 一个随档变色的点(见 SessionSettingsMenu),bypass 用最重的样式。
 *
 * bypass 要多点一次:那一档里智能体可以用你的账号公开发布、向外部服务发请求、在这台机器上跑代码,
 * 后果不在这个应用里、撤不回来 —— 不该像主题开关那样顺手滑过去。
 *
 * 放行本身在**服务端**判定(domain/agent/autopilot):此前「本会话始终允许」是浏览器 localStorage
 * 里的一段自动批准,聊天面板一关组件就卸载,而 turn 还在跑。
 */
export function PermissionModePicker({ session }: { session: AgentSession | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [pendingBypass, setPendingBypass] = React.useState(false);

  const setMode = useMutation({
    mutationFn: (mode: PermissionMode) =>
      api(`/api/agent/sessions/${session!.id}`, {
        method: "PATCH",
        body: JSON.stringify({ permission_mode: mode }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agent-session", session?.id] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions"] });
    },
  });

  if (!session) return null;
  const mode = permissionModeOf(session);
  const Icon = PERMISSION_MODE_ICON[mode];

  return (
    <>
      {/* key 随 value 重挂:Radix 对初始受控值不刷新触发器文本(与思考档位同一处理)。 */}
      <Select
        key={mode}
        value={mode}
        onValueChange={(next) => {
          if (next === "bypass") return setPendingBypass(true);
          setMode.mutate(next as PermissionMode);
        }}
      >
        <SelectTrigger
          className="h-8 w-full justify-between gap-1.5 px-2.5 text-xs text-muted-foreground"
          aria-label={t("permModeLabel")}
        >
          {/* 不用 SelectValue:它会把选中项的**全部内容**克隆进触发器,而选项里带着一行说明 ——
              于是触发器变成两行、把整条工具栏撑高。触发器只要档位名。 */}
          <span className="flex min-w-0 items-center gap-1.5">
            <Icon size={13} className={cn("shrink-0", ACCENT[mode])} />
            <span className="truncate">{t(LABEL[mode])}</span>
          </span>
        </SelectTrigger>
        <SelectContent>
          {PERMISSION_MODES.map((value) => (
            <SelectItem
              key={value}
              value={value}
              // 放开共享原语里的单行截断:它给选项内容加了 `truncate`(含 white-space: nowrap),
              // 而这里每个选项是"名字 + 一行说明"两行 —— 不放开的话说明会被裁成「…对外请…」。
              className="items-start py-2 [&>span:last-child]:overflow-visible [&>span:last-child]:whitespace-normal"
            >
              <span className="grid gap-0.5">
                <span className={value === "bypass" ? "text-destructive" : undefined}>{t(LABEL[value])}</span>
                <span className="text-[11px] leading-snug text-muted-foreground">{t(HINT[value])}</span>
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* 二次确认:这一档放开的是撤不回来的动作,不该一次点击就滑过去。 */}
      <Dialog open={pendingBypass} onOpenChange={setPendingBypass}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert size={16} className="text-destructive" /> {t("permModeBypassConfirmTitle")}
            </DialogTitle>
            <DialogDescription>{t("permModeBypassConfirmBody")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingBypass(false)}>
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              loading={setMode.isPending}
              onClick={() => setMode.mutate("bypass", { onSuccess: () => setPendingBypass(false) })}
            >
              {t("permModeBypassConfirmCta")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

const LABEL = { manual: "permModeManual", auto: "permModeAuto", bypass: "permModeBypass" } as const;
const HINT = {
  manual: "permModeManualHint",
  auto: "permModeAutoHint",
  bypass: "permModeBypassHint",
} as const;
export const ACCENT = { manual: "", auto: "text-primary", bypass: "text-destructive" } as const;
