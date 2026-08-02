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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type AgentSession = components["schemas"]["AgentSessionOut"];

const MODES = ["manual", "auto", "bypass"] as const;
type Mode = (typeof MODES)[number];

/**
 * 这次对话里,哪一类动作智能体可以不问就做。
 *
 * **常驻在输入框主行,不进「会话设置」弹层。** 那个弹层的定位是"配好就不再动的东西"(分析方式、
 * 思考档位),而模式恰恰相反:用户不知道自己此刻授权了什么,就等于没有授权。它必须一直在视线里。
 *
 * bypass 要多点一次:它不该像主题开关那样顺手就滑过去 —— 那一档里,智能体可以用你的账号公开发布、
 * 向外部服务发请求、在这台机器上跑代码,而这些后果不在这个应用里,撤不回来。
 *
 * 放行本身在**服务端**判定(domain/agent/autopilot)。这个组件只负责说清现在是哪一档、以及改它;
 * 此前"本会话始终允许"是浏览器 localStorage 里的一份自动批准,聊天面板一关组件就卸载,而 turn
 * 还在跑 —— 同一个"授权"的行为取决于某个 React 组件在不在。
 */
export function PermissionModePicker({ session }: { session: AgentSession | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [pendingBypass, setPendingBypass] = React.useState(false);

  const setMode = useMutation({
    mutationFn: (mode: Mode) =>
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
  const mode = (MODES as readonly string[]).includes(session.permission_mode)
    ? (session.permission_mode as Mode)
    : "manual";

  const label = (value: Mode) =>
    value === "auto" ? t("permModeAuto") : value === "bypass" ? t("permModeBypass") : t("permModeManual");
  const hint = (value: Mode) =>
    value === "auto"
      ? t("permModeAutoHint")
      : value === "bypass"
        ? t("permModeBypassHint")
        : t("permModeManualHint");
  const Icon = mode === "bypass" ? ShieldAlert : mode === "auto" ? ShieldCheck : ShieldQuestion;

  return (
    <>
      {/* key 随 value 重挂:Radix 对初始受控值不刷新触发器文本(与思考档位同一处理)。 */}
      <Select
        key={mode}
        value={mode}
        onValueChange={(next) => {
          if (next === "bypass") return setPendingBypass(true);
          setMode.mutate(next as Mode);
        }}
      >
        <SelectTrigger
          className={`h-7 w-auto gap-1.5 border-0 px-2 text-xs ${
            mode === "bypass"
              ? "text-destructive"
              : mode === "auto"
                ? "text-primary"
                : "text-muted-foreground"
          }`}
          aria-label={t("permModeLabel")}
          title={hint(mode)}
        >
          <span className="flex min-w-0 items-center gap-1.5">
            <Icon size={13} className="shrink-0" />
            <SelectValue />
          </span>
        </SelectTrigger>
        <SelectContent align="start" className="max-w-[300px]">
          {MODES.map((value) => (
            <SelectItem key={value} value={value}>
              <span className="grid gap-0.5">
                <span>{label(value)}</span>
                <span className="text-[11px] leading-snug text-muted-foreground">{hint(value)}</span>
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
              onClick={() => {
                setMode.mutate("bypass", { onSuccess: () => setPendingBypass(false) });
              }}
            >
              {t("permModeBypassConfirmCta")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
