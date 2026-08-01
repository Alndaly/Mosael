import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Film } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type AgentSession = components["schemas"]["AgentSessionOut"];

const MODES = ["auto", "native", "frames"] as const;

/**
 * 视频分析方式(会话级):auto=自动(有 Gemini/Qwen-VL/Kimi 就原生直读整段视频,否则抽帧+转写)、
 * native=强制原生、frames=强制抽帧+转写。写回会话后由系统提示强约束 analyze_asset 的 mode。
 * 仅在有会话时显示。
 */
export function AnalysisModePicker({ session }: { session: AgentSession | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const setMode = useMutation({
    mutationFn: (mode: string) =>
      api(`/api/agent/sessions/${session!.id}`, {
        method: "PATCH",
        body: JSON.stringify({ analysis_video_mode: mode }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agent-session", session?.id] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions"] });
    },
  });
  if (!session) return null;
  const value = (MODES as readonly string[]).includes(session.analysis_video_mode) ? session.analysis_video_mode : "auto";
  const label = (mode: string) =>
    mode === "native" ? t("analysisModeNative") : mode === "frames" ? t("analysisModeFrames") : t("analysisModeAuto");
  return (
    // key 随 value 重挂,规避 Radix 对初始受控值不刷新触发器文本的问题。
    <Select key={value} value={value} onValueChange={(next) => setMode.mutate(next)}>
      <SelectTrigger className="h-8 w-full justify-between gap-1.5 px-2.5 text-xs text-muted-foreground" aria-label={t("analysisModeLabel")} title={t("analysisModeHint")}>
        <span className="flex min-w-0 items-center gap-1.5">
          <Film size={13} className="shrink-0 opacity-70" />
          <SelectValue />
        </span>
      </SelectTrigger>
      <SelectContent className="max-w-none">
        {MODES.map((mode) => (
          <SelectItem key={mode} value={mode}>
            {label(mode)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
