/**
 * 把一段文字念出来。消息页脚上那个喇叭。
 *
 * **同一条路要服务三件事**:这里的播放、确认卡与提问的语音化、失败出声。对用户来说它们
 * 是同一个声音,所以音色配置只有一份(设置里的「语音对话」),端点也只有一个
 * (`POST /api/agent/speech`,不产出素材 —— 见那边的说明)。
 *
 * 几个刻意的选择:
 *
 * · **同一时刻只响一个。** 连点两条消息,两段语音叠在一起是听不清的;后点的接管,前一段停掉。
 * · **再点一下就停。** 念到一半发现不是想听的那条,总得能掐掉 —— 这也是后面"打断"要用的同一个开关。
 * · **没配音色不是错误。** 回 409 时给一句"去设置里选一个",而不是一个红色的失败。
 */

import React from "react";
import { Loader2, Square, Volume2 } from "lucide-react";
import { toast } from "sonner";

import { API_BASE, getAuthToken } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { playSpeech, stopSpeaking } from "@/components/agent/speechPlayback";
import { FOOTER_ACTION_CLASS } from "@/features/ai-studio/messageUsage";
import { cn } from "@/lib/utils";

export function SpeakButton({
  text,
  workspaceId,
  className,
}: {
  text: string;
  workspaceId?: string;
  className?: string;
}) {
  const t = useI18n();
  const [state, setState] = React.useState<"idle" | "loading" | "playing">("idle");
  const reset = React.useCallback(() => setState("idle"), []);

  React.useEffect(() => {
    // 组件没了(切会话、清空对话)声音也该停 —— 否则它会继续念一条已经不在屏幕上的消息。
    return () => {
      if (stateRef.current === "playing") stopSpeaking();
    };
  }, []);

  const stateRef = React.useRef(state);
  stateRef.current = state;

  async function play() {
    stopSpeaking();
    setState("loading");
    try {
      const token = getAuthToken();
      const response = await fetch(`${API_BASE}/api/agent/speech`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ text, workspace_id: workspaceId ?? "" }),
      });
      if (!response.ok) {
        const detail = (await response.json().catch(() => null))?.detail;
        // 409 = 还没选音色。那是个待办,不是故障 —— 说清楚下一步在哪。
        toast[response.status === 409 ? "message" : "error"](detail || t("speakFailed"));
        setState("idle");
        return;
      }
      setState("playing");
      // playSpeech 会接管前一段(见 speechPlayback):连点两条消息时,前一条自己停掉。
      await playSpeech(await response.blob());
      reset();
    } catch {
      toast.error(t("speakFailed"));
      setState("idle");
    }
  }

  const busy = state === "loading";
  const active = state === "playing";
  return (
    // 和「复制」同一套外形(FOOTER_ACTION_CLASS):图标 11px、带文字、同样的圆角与内边距。
    // 并排的两个动作长得不一样时,读起来像两个不同来处的东西。
    <button
      type="button"
      className={cn(FOOTER_ACTION_CLASS, className)}
      aria-label={active ? t("speakStop") : t("speak")}
      title={active ? t("speakStop") : t("speak")}
      disabled={busy || !text.trim()}
      onClick={() => (active ? stopSpeaking() : void play())}
    >
      {busy ? (
        <Loader2 size={11} className="animate-mosael-spin" />
      ) : active ? (
        <Square size={11} className="fill-current" />
      ) : (
        <Volume2 size={11} />
      )}
      {active ? t("speakStopLabel") : t("speakLabel")}
    </button>
  );
}
