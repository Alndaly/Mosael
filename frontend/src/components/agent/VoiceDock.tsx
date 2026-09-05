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
 * 不是一次录制。所以是声波条:四种状态共用同一组条,靠颜色和动效区分 —— 换四个不同图标的话,
 * 它就不再像"同一个东西的四种状态"。
 *
 * **一颗静止的圆点说不清任何事。** 语音是没有界面的交互:该我说还是该我听、它到底听没听见、
 * 是不是死了 —— 这些问题在文字聊天里由光标和滚动条回答,而这里只剩这一颗。所以它必须一直
 * 在动,并且**动得有含义**:条形跟着真实音量走(见 VoiceOrb),旁边一句话直说当前是哪个
 * 状态、上一句听到的是什么。听错的时候你当场就看得见错在哪个字,而不是等它答非所问。
 */

import React from "react";
import { X } from "lucide-react";

import { api } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useVoiceLoop } from "@/components/agent/useVoiceLoop";
import { useSelectedAgentSessionId } from "@/components/agent/useAgentNavigation";
import { VoiceOrb } from "@/components/agent/VoiceOrb";
import { agentSessionSelectionKey } from "@/features/ai-studio/sessionSelection";
import { useFloatingPanel } from "@/features/workflows/useFloatingPanel";
import { cn } from "@/lib/utils";
import { useQuery, useQueryClient } from "@tanstack/react-query";

const DOCK_SIZE = 52;

type Message = { id: string; role: string; content: string; error: string | null };

export function VoiceDock({ workspaceId, onClose }: { workspaceId: string; onClose: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();

  // 选中会话存在 localStorage 里(和助手面板同一个键)。读它的那点讲究抽在了 hook 里。
  const sessionKey = agentSessionSelectionKey(workspaceId);
  const selected = useSelectedAgentSessionId(workspaceId);
  const [sessionId, setSessionId] = React.useState(selected);
  React.useEffect(() => setSessionId(selected), [selected]);

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
  const { style, startDrag, wasDragged, focusProps } = useFloatingPanel({
    storageKey: "mosael.voice.dock.rect.v1",
    floating: true,
    minW: DOCK_SIZE,
    minH: DOCK_SIZE,
    preferredW: DOCK_SIZE,
    preferredH: DOCK_SIZE,
    // 整颗都是把手 —— 它本身就是一颗按钮,默认那条"控件不带着窗口跑"的规则会把它的
    // 全部表面都算成控件,于是一步也拖不动。
    dragAnywhere: true,
  });

  const label = loop.on ? t(`voiceMode_${loop.state}` as "voiceMode_listening") : t("voiceModeStart");

  //: 状态说明什么时候露出来。**换状态时自动露 2.4 秒**,而不是只在悬停时 —— 免提的前提
  //: 就是手和眼睛都在别处,一个要先把鼠标挪过去才肯解释自己的提示,恰好在唯一需要它的
  //: 时刻不说话。之后自己收起来,它平时该只是一颗。
  const [showCaption, setShowCaption] = React.useState(false);
  React.useEffect(() => {
    if (!loop.on) return;
    setShowCaption(true);
    const timer = window.setTimeout(() => setShowCaption(false), 2400);
    return () => window.clearTimeout(timer);
    // heard 也进依赖:听到新的一句要重新露一次,那是最该被看见的一条。
  }, [loop.state, loop.heard, loop.on]);

  //: 说明文字贴左边还是右边。浮标常被拖到右下角,那时贴右会被屏幕边切掉一半 ——
  //: 而"被切掉的解释"比没有解释更让人烦躁。
  const captionOnLeft = (style?.left ?? 0) > window.innerWidth / 2;
  const caption = loop.state === "hearing" || !loop.heard ? label : `${t("voiceDockHeard")}${loop.heard}`;

  return (
    <div
      className="group/dock fixed z-[70] select-none"
      style={style}
      {...focusProps}
      role="complementary"
      aria-label={t("voiceModeStart")}
      onMouseEnter={() => setShowCaption(true)}
      onMouseLeave={() => setShowCaption(false)}
    >
      <button
        type="button"
        className={cn(
          "relative grid size-[52px] cursor-grab touch-none place-items-center rounded-full p-0",
          "border border-border-strong bg-panel/90 shadow-[var(--shadow-panel)] backdrop-blur-xl",
          "transition-[border-color,box-shadow] active:cursor-grabbing",
          loop.on && "border-primary/60",
          // 听你说的时候多一圈:这是唯一"你的话正在被录"的时刻,值得比别的状态更显眼。
          loop.state === "hearing" && "ring-2 ring-primary/30",
        )}
        onPointerDown={startDrag}
        // 拖完手一松不该顺带开关一次免提 —— 你只是想把它挪开。wasDragged 读一次就清,
        // 所以键盘敲回车(没有 pointer 事件)照样按得动。
        onClick={() => {
          if (wasDragged()) return;
          if (loop.on) loop.stop();
          else void loop.start();
        }}
        aria-label={label}
        title={label}
      >
        <VoiceOrb state={loop.state} levelRef={loop.levelRef} />
      </button>

      {/* 说明:当前在干什么,或者上一句听到了什么。 */}
      <div
        className={cn(
          "pointer-events-none absolute top-1/2 -translate-y-1/2 whitespace-nowrap rounded-full",
          "border border-border-strong bg-panel/95 px-2.5 py-1 text-ui-sm text-foreground",
          "shadow-[var(--shadow-panel)] backdrop-blur-xl transition-opacity duration-200",
          // 听到的原话可能很长,给个上限并省略 —— 一条横穿屏幕的提示比不显示更糟。
          "max-w-[260px] overflow-hidden text-ellipsis",
          captionOnLeft ? "right-[60px]" : "left-[60px]",
          showCaption ? "opacity-100" : "opacity-0",
        )}
        aria-live="polite"
      >
        {caption}
      </div>

      {/* 关掉浮标本身:不必为了收起它去翻设置页。悬停才出现,常态下它只是一颗。
          **放在那颗之外**:按钮里套按钮读屏会把两个念成一个,而且点它会连带触发外面
          那一下开关 —— 于是"收起来"变成了"先开始对话再收起来"。 */}
      <button
        type="button"
        data-no-drag
        className="absolute -right-1 -top-1 z-[1] hidden size-[18px] cursor-pointer place-items-center rounded-full border border-border-strong bg-panel text-muted-foreground hover:text-destructive group-hover/dock:grid"
        aria-label={t("voiceDockHide")}
        title={t("voiceDockHide")}
        onClick={() => {
          loop.stop();
          onClose();
        }}
      >
        <X size={11} />
      </button>
    </div>
  );
}
