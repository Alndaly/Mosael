import React from "react";
import { Film } from "lucide-react";

import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Hint } from "@/components/ui/tooltip";
import { useSessionSettings } from "@/features/agent/currentAgentSession";
import type { AgentPlace } from "@/features/agent/places";

type AgentSession = components["schemas"]["AgentSessionOut"];

const MODES = ["auto", "native", "frames"] as const;

/**
 * 视频分析方式(会话级):auto=当前 API Key 模型有原生 Adapter 就直读整段,否则抽帧+转写；
 * OAuth Gateway 的 auto 固定走抽帧。native=强制原生(OAuth 会明确拒绝),frames=强制抽帧+转写。
 * 写回会话后由服务端按令牌绑定的 session 强制执行；系统提示只负责让模型提前知道。
 * 草稿上没选过时按新会话的默认值(auto)显示;选了记在草稿上,建会话时一起带上(见 useSessionSettings)。
 */
export function AnalysisModePicker({ workspaceId, place, session }: { workspaceId: string; place: AgentPlace; session: AgentSession | null }) {
  const t = useI18n();
  const { settings, update: setMode } = useSessionSettings(workspaceId, place, session);
  const value = settings.analysis_video_mode && (MODES as readonly string[]).includes(settings.analysis_video_mode) ? settings.analysis_video_mode : "auto";
  const label = (mode: string) =>
    mode === "native" ? t("analysisModeNative") : mode === "frames" ? t("analysisModeFrames") : t("analysisModeAuto");
  return (
    // key 随 value 重挂,规避 Radix 对初始受控值不刷新触发器文本的问题。
    <Select key={value} value={value} onValueChange={(next) => setMode.mutate({ analysis_video_mode: next })}>
      <Hint label={t("analysisModeHint")}>
        <SelectTrigger size="sm" className="w-full" aria-label={t("analysisModeLabel")}>
          <span className="flex min-w-0 items-center gap-1.5">
            <Film className="size-3.5 shrink-0 opacity-70" />
            <SelectValue />
          </span>
        </SelectTrigger>
      </Hint>
      <SelectContent>
        {MODES.map((mode) => (
          <SelectItem key={mode} value={mode}>
            {label(mode)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
