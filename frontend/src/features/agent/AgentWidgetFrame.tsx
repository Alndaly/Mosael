import React from "react";
import { AppWindow, Check, Copy, Maximize2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import {
  WIDGET_INITIAL_HEIGHT,
  WIDGET_SANDBOX,
  buildWidgetDocument,
  currentWidgetTheme,
  widgetHeightFrom,
} from "@/features/agent/agentWidget";
import type { AgentWidget } from "@/features/agent/turnOutputs";
import { cn } from "@/lib/utils";

/**
 * 沙箱 iframe 本身。安全边界整段写在 agentWidget.ts 的文件头,这里只照着做:
 * `sandbox` 只给 allow-scripts、文档开头有 CSP、只认这个框自己报的高度。
 *
 * 不写 `allow`(权限策略):不透明来源的框对摄像头、麦克风、定位这类能力**默认就没有**,写一份清单反倒是在
 * 暗示"清单外的给了"。`referrerPolicy="no-referrer"`:框里从 CDN 拉库时不带这一页的地址。
 */
// 同一颗组件在「实时流 → 落库消息」切换时会重挂。高度协商若从头再来,**视口相对**的内容
// (地图用 100%/vh 撑满框那种)会跟着框高回环收敛,一圈比一圈矮(用户实测:回答结束后
// 内嵌地图瘪成一条)。记住每颗组件上次谈好的高度,重挂从那儿接着谈。
const widgetHeightCache = new Map<string, number>();

function WidgetIframe({ srcDoc, title, cacheKey, fill = false }: { srcDoc: string; title: string; cacheKey: string; fill?: boolean }) {
  const frame = React.useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = React.useState(() => widgetHeightCache.get(cacheKey) ?? WIDGET_INITIAL_HEIGHT);
  React.useEffect(() => {
    if (fill) return;
    const onMessage = (event: MessageEvent) => {
      const next = widgetHeightFrom(event, frame.current?.contentWindow);
      if (next === null) return;
      setHeight((current) => {
        // 单次上报缩到六成以下,基本是「内容高度跟着框高走」的回环在收敛,不是内容真的变矮 —— 拒收,
        // 一颗地图才不会每次重挂都瘪一圈。内容真要变矮(面板收起)也是分几步报上来的。
        if (next < current * 0.6) return current;
        widgetHeightCache.set(cacheKey, next);
        return next;
      });
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [fill, cacheKey]);
  return (
    <iframe
      ref={frame}
      title={title}
      srcDoc={srcDoc}
      sandbox={WIDGET_SANDBOX}
      referrerPolicy="no-referrer"
      //: 全屏时不进 Tab 序:弹窗打开会把焦点给第一个可 Tab 的元素,那就是这个框 —— 焦点一进框,Esc 按在框里的文档上,
      //: 弹窗收不到,关不掉(真界面里撞到过)。这样焦点落在关闭钮上;框里照样能点、能拖。
      tabIndex={fill ? -1 : undefined}
      data-agent-widget-frame=""
      className={cn("block w-full border-0 bg-card", fill ? "h-full min-h-0" : "rounded-b-lg")}
      style={fill ? undefined : { height }}
    />
  );
}

/**
 * 智能体给的一块小界面,画在一轮回答的结果区里(`show_widget`,见 turnOutputs.turnWidgets)。
 *
 * 一张卡:头上一行是标题和两颗图钮(复制源码、展开),下面是框。框的高度跟着内容走(框里报上来,夹在上下限之间),
 * 再高的点「展开」看全屏 —— 展开时对话里那一份先卸下,同一时刻只跑一份脚本。
 */
export function AgentWidgetFrame({ widget }: { widget: AgentWidget }) {
  const t = useI18n();
  const [expanded, setExpanded] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const title = widget.title || t("agentWidgetUntitled");
  //: 主题在建文档时抄一次:换主题后已经画着的框不跟着变,下次渲染这一轮时才换 —— 框里的状态(拖过的地图)比颜色值钱。
  const srcDoc = React.useMemo(() => buildWidgetDocument(widget.html, currentWidgetTheme()), [widget.html]);
  React.useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);
  const copy = () => {
    void navigator.clipboard?.writeText(widget.html).then(() => setCopied(true));
  };

  return (
    <figure className="m-0 min-w-0 overflow-hidden rounded-lg border border-border" data-agent-widget={widget.id}>
      {/* cacheKey 用组件自己的 id:重挂(流式 → 落库)后高度从上次谈好的接着来 */}
      <figcaption className="flex h-8 min-w-0 items-center gap-1.5 border-b border-border pl-2.5 pr-1 text-ui-xs text-muted-foreground">
        <AppWindow size={13} className="flex-none" aria-hidden />
        <Truncate className="min-w-0 flex-1">{title}</Truncate>
        <IconButton label={copied ? t("copied") : t("agentWidgetCopySource")} size="icon-xs" onClick={copy}>
          {copied ? <Check /> : <Copy />}
        </IconButton>
        <IconButton label={t("agentWidgetExpand")} size="icon-xs" onClick={() => setExpanded(true)}>
          <Maximize2 />
        </IconButton>
      </figcaption>
      {!expanded && <WidgetIframe srcDoc={srcDoc} title={title} cacheKey={widget.id} />}
      <ModalShell
        open={expanded}
        onOpenChange={setExpanded}
        title={title}
        className="h-[90vh] w-[min(1200px,calc(100vw-48px))]"
        bodyClassName="flex flex-col p-0 [scrollbar-gutter:auto]"
      >
        <WidgetIframe srcDoc={srcDoc} title={title} cacheKey={widget.id} fill />
      </ModalShell>
    </figure>
  );
}
