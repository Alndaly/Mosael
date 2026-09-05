/**
 * 免提对话的浮标:整个应用右下角一颗,拖到哪儿它就待在哪儿。
 *
 * **为什么从工具行搬出来。** 免提是"手离开键盘"的模式 —— 你在剪时间线、在画板上摆东西,
 * 而输入框可能根本不在屏幕上(助手面板是可以收起来的)。一个跟着面板走的按钮,恰好在最需要
 * 它的时候不见了。浮标一直在,而且拖得走 —— 挡住东西时不必去设置里关掉它。
 *
 * **对哪个会话说话。** 和助手面板读同一个选中会话(agentSessionSelectionKey)—— AI 工作台、
 * 编辑器、工作流、画板共用一个对话池,浮标不该是第五个入口、开出第五条对话。
 *
 * **图标不是话筒。** 话筒说的是"录音",而这里表达的是"它在听 / 它在说" —— 是一段对话,
 * 不是一次录制。声波条(AudioLines)是语音助手的通用符号,四种状态共用它一个,靠颜色和
 * 动效区分:换四个不同图标的话,它就不再像"同一个东西的四种状态"。
 */

import React from "react";
import { AudioLines, Loader2, X } from "lucide-react";

import { api } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useVoiceLoop } from "@/components/agent/useVoiceLoop";
import { agentSessionSelectionKey } from "@/features/ai-studio/sessionSelection";
import { useFloatingPanel } from "@/features/workflows/useFloatingPanel";
import { cn } from "@/lib/utils";
import { useQuery, useQueryClient } from "@tanstack/react-query";

const DOCK_SIZE = 52;

type Message = { id: string; role: string; content: string; error: string | null };

export function VoiceDock({ workspaceId, onClose }: { workspaceId: string; onClose: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();

  // 选中会话存在 localStorage 里(和助手面板同一个键)。它会被别处改掉,所以跟着 storage 事件走。
  const sessionKey = agentSessionSelectionKey(workspaceId);
  const [sessionId, setSessionId] = React.useState(() => window.localStorage.getItem(sessionKey) || "");
  React.useEffect(() => {
    const sync = () => setSessionId(window.localStorage.getItem(sessionKey) || "");
    window.addEventListener("storage", sync);
    // 同一个标签页里改 localStorage 不触发 storage 事件,轮一下兜底 —— 面板切会话时浮标要跟上。
    const timer = window.setInterval(sync, 2000);
    return () => {
      window.removeEventListener("storage", sync);
      window.clearInterval(timer);
    };
  }, [sessionKey]);

  const live = useQuery({
    queryKey: ["agent-session", sessionId],
    queryFn: () => api<{ status: string }>(`/api/agent/sessions/${sessionId}`),
    enabled: Boolean(sessionId),
    refetchInterval: 1500,
  });
  const messages = useQuery({
    queryKey: ["agent-messages", sessionId],
    queryFn: () => api<Message[]>(`/api/agent/sessions/${sessionId}/messages`),
    enabled: Boolean(sessionId),
    refetchInterval: 2000,
  });

  const rows = messages.data ?? [];
  const reply = React.useMemo(() => {
    for (let index = rows.length - 1; index >= 0; index -= 1) {
      const row = rows[index];
      if (row.role === "assistant" && !row.error) return (row.content || "").trim();
    }
    return "";
  }, [rows]);
  const failure = rows.at(-1)?.role === "assistant" ? rows.at(-1)?.error || "" : "";

  const loop = useVoiceLoop({
    workspaceId,
    busy: live.data?.status === "running",
    reply,
    failure,
    onUtterance: async (text) => {
      let target = sessionId;
      if (!target) {
        // 还没有会话就开一条,并**写回同一个键** —— 这样面板打开时看到的就是这段对话,
        // 而不是"我刚才对着浮标说的话去哪儿了"。
        const created = await api<{ id: string }>("/api/agent/sessions", {
          method: "POST",
          body: JSON.stringify({ workspace_id: workspaceId }),
        });
        target = created.id;
        window.localStorage.setItem(sessionKey, target);
        setSessionId(target);
      }
      await api(`/api/agent/sessions/${target}/messages`, {
        method: "POST",
        body: JSON.stringify({ content: text }),
      });
      void qc.invalidateQueries({ queryKey: ["agent-messages", target] });
    },
  });

  // 拖动与位置记忆走面板那套 —— 里面那段"别让它被拖出屏幕外就再也抓不回来"是踩出来的。
  const { style, startDrag, focusProps } = useFloatingPanel({
    storageKey: "mosael.voice.dock.rect.v1",
    floating: true,
    minW: DOCK_SIZE,
    minH: DOCK_SIZE,
    preferredW: DOCK_SIZE,
    preferredH: DOCK_SIZE,
  });

  const label = loop.on ? t(`voiceMode_${loop.state}` as "voiceMode_listening") : t("voiceModeStart");
  return (
    <div
      className="fixed z-[70] select-none"
      style={style}
      {...focusProps}
      role="complementary"
      aria-label={t("voiceModeStart")}
    >
      <div
        className={cn(
          "group/dock relative grid size-[52px] cursor-grab place-items-center rounded-full border border-border-strong",
          "bg-panel/90 shadow-[var(--shadow-panel)] backdrop-blur-xl transition-colors active:cursor-grabbing",
          loop.on && "border-primary/60",
        )}
        onPointerDown={startDrag}
        title={label}
      >
        <button
          type="button"
          className="grid size-full cursor-pointer place-items-center rounded-full border-0 bg-transparent p-0"
          aria-label={label}
          // 拖动和点击都在这一颗上:startDrag 会区分"拖过"和"只是按了一下"(见 useFloatingPanel)。
          onClick={() => (loop.on ? loop.stop() : void loop.start())}
        >
          {loop.state === "thinking" ? (
            <Loader2 size={20} className="animate-mosael-spin text-primary" />
          ) : (
            <AudioLines
              size={20}
              className={cn(
                "transition-colors",
                loop.state === "off" && "text-muted-foreground",
                loop.state === "listening" && "text-primary/70",
                // 听你说 / 在说:同一个符号,靠脉动区分"轮到谁"。
                loop.state === "hearing" && "animate-pulse text-primary",
                loop.state === "speaking" && "animate-pulse text-foreground",
              )}
            />
          )}
        </button>
        {/* 关掉浮标本身:不必为了收起它去翻设置页。悬停才出现,常态下它只是一颗。 */}
        <button
          type="button"
          className="absolute -right-1 -top-1 hidden size-[18px] cursor-pointer place-items-center rounded-full border border-border-strong bg-panel text-muted-foreground hover:text-destructive group-hover/dock:grid"
          aria-label={t("voiceDockHide")}
          title={t("voiceDockHide")}
          onClick={(event) => {
            event.stopPropagation();
            loop.stop();
            onClose();
          }}
        >
          <X size={11} />
        </button>
      </div>
    </div>
  );
}
