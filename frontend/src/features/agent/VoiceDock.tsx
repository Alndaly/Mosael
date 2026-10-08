/**
 * 免提对话的浮标:整个应用右下角一颗,拖到哪儿它就待在哪儿。
 *
 * **为什么从工具行搬出来。** 免提是"手离开键盘"的模式 —— 你在剪时间线、在画板上摆东西,
 * 而输入框可能根本不在屏幕上(助手面板是可以收起来的)。一个跟着面板走的按钮,恰好在最需要
 * 它的时候不见了。浮标一直在,而且拖得走 —— 挡住东西时不必去设置里关掉它。
 *
 * **对哪段对话说话。** 眼下这一处的当前对话(ADR 0044 拍板 7):在有助手面板的页面(面板收没收起来都算),是那一页的
 * 当前对话;别处(素材、发布、设置……)是 AI Studio 的当前对话。那一处还是草稿就在那一处建一段 —— 和面板发第一句话一样。
 * 浮标不是另一个入口,不另开一段对话。
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
import { toast } from "sonner";

import { getAgentSession, listAgentMessages, sendAgentMessage } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useVoiceLoop } from "@/features/agent/useVoiceLoop";
import { useActivePlace } from "@/features/agent/activePlace";
import { useCurrentAgentSession } from "@/features/agent/currentAgentSession";
import { placePayload } from "@/features/agent/places";
import { VoiceOrb } from "@/features/agent/VoiceOrb";
import { useFloatingPanel } from "@/components/app/useFloatingPanel";
import { InChromeStatusSlot, useChromeStatusSlot } from "@/components/app/chromeStatusSlot";
import { useNativeViewInFront } from "@/lib/nativeView";
import { IconButton } from "@/components/ui/icon-button";
import { cn } from "@/lib/utils";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { transcriptPolling, useTranscriptFollowsSession } from "@/features/agent/transcriptFollowsSession";

const DOCK_SIZE = 52;

export function VoiceDock({ workspaceId, onClose }: { workspaceId: string; onClose: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();

  //: 眼下这一处(页面登记的,见 activePlace):浮标跟着你走,不再对你离开的那一处说话。
  const place = useActivePlace();
  const current = useCurrentAgentSession(workspaceId, place);
  const sessionId = current.session?.id ?? "";

  const live = useQuery({
    queryKey: ["agent-session", sessionId],
    queryFn: () => getAgentSession(sessionId),
    enabled: Boolean(sessionId),
    refetchInterval: 1500,
  });
  //: 和面板同一条:消息只在跑着的时候轮询,空闲时跟着会话变化重取(见 transcriptFollowsSession)。
  const messages = useQuery({
    queryKey: ["agent-messages", sessionId],
    queryFn: () => listAgentMessages(sessionId),
    enabled: Boolean(sessionId),
    refetchInterval: transcriptPolling(live.data?.status === "running"),
  });
  useTranscriptFollowsSession(sessionId, live.data);

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
      // 对着这一处的当前对话说;还是草稿就在这一处建一段 —— 建出来的就是面板接下来显示的那段,
      // 而不是"我刚才对着浮标说的话去哪儿了"。这一处是同事共享来只能看的那段,就说清楚
      // (ensure 会拒,不替他另建一段 —— 那句话该发在哪儿由他定)。
      if (current.readOnly) {
        toast.error(t("chatSessionReadOnly"));
        return;
      }
      const target = (await current.ensure()).id;
      await sendAgentMessage(target, { content: text, place: placePayload(place) });
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
  //: 时刻不说话。之后自己收起来,它平时该只是一颗。悬停时说的是同一件事,走全应用那一条
  //: 悬停说明(名字 + 上一句听到了什么),不再另露一份这个气泡。
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
  const toggle = () => {
    if (loop.on) loop.stop();
    else void loop.start();
  };

  //: 内嵌浏览器、工作台的画布在前台时(ADR 0051 D37):浮标拖到哪儿都可能落在网页底下,收成外壳顶栏上的一个图标 —— 同一个
  //: 免提循环,说话照常;听到的那一句写在悬停说明里。视图收起,回到原来拖到的位置。
  const chromeSlot = useChromeStatusSlot();
  const overNativeView = useNativeViewInFront();
  if (overNativeView && chromeSlot) {
    return (
      <InChromeStatusSlot slot={chromeSlot}>
        <IconButton
          variant="outline"
          size={chromeSlot.size === "xs" ? "icon-xs" : "icon-sm"}
          data-voice-dock-in-chrome=""
          className={cn(loop.on && "border-primary/60", loop.state === "hearing" && "ring-2 ring-primary/30")}
          onClick={toggle}
          label={label}
          hint={loop.heard ? `${t("voiceDockHeard")}${loop.heard}` : undefined}
        >
          <VoiceOrb state={loop.state} levelRef={loop.levelRef} />
        </IconButton>
      </InChromeStatusSlot>
    );
  }

  return (
    <div
      className="group/dock fixed z-[70] select-none"
      style={style}
      {...focusProps}
      role="complementary"
      aria-label={t("voiceModeStart")}
    >
      <IconButton
        unstyled
        className={cn(
          "relative grid size-[52px] cursor-grab touch-none place-items-center rounded-full p-0",
          "border border-floating-border bg-panel/90 shadow-[var(--shadow-panel)] backdrop-blur-xl",
          "transition-[border-color,box-shadow] active:cursor-grabbing",
          loop.on && "border-primary/60",
          // 听你说的时候多一圈:这是唯一"你的话正在被录"的时刻,值得比别的状态更显眼。
          loop.state === "hearing" && "ring-2 ring-primary/30",
        )}
        onPointerDown={startDrag}
        // 拖完手一松不该顺带开关一次免提 —— 你只是想把它挪开。wasDragged 读一次就清,
        // 所以键盘敲回车(没有 pointer 事件)照样按得动。
        onClick={() => {
          if (!wasDragged()) toggle();
        }}
        label={label}
        hint={loop.heard ? `${t("voiceDockHeard")}${loop.heard}` : undefined}
        tooltipSide={captionOnLeft ? "left" : "right"}
      >
        <VoiceOrb state={loop.state} levelRef={loop.levelRef} />
      </IconButton>

      {/* 说明:当前在干什么,或者上一句听到了什么。 */}
      <div
        className={cn(
          "pointer-events-none absolute top-1/2 -translate-y-1/2 whitespace-nowrap rounded-full",
          "border border-floating-border bg-panel/95 px-2.5 py-1 text-ui-sm text-foreground",
          "shadow-[var(--shadow-panel)] backdrop-blur-xl transition-opacity duration-160",
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
      <IconButton
        unstyled
        data-no-drag
        className="absolute -right-1 -top-1 z-[1] hidden size-[18px] cursor-pointer place-items-center rounded-full border border-floating-border bg-panel text-muted-foreground hover:text-destructive group-hover/dock:grid"
        label={t("voiceDockHide")}
        onClick={() => {
          loop.stop();
          onClose();
        }}
      >
        <X size={11} />
      </IconButton>
    </div>
  );
}
