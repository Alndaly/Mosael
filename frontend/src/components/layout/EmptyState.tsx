import React from "react";
import { ChevronDown } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { errorText, splitErrorText } from "@/api/errorMessage";
import { canReviveDesktopBackend, reviveDesktopBackend } from "@/lib/desktopBackend";

/**
 * 「这里还没有东西」的统一说法。
 *
 * **三个尺寸,不是三个组件**:整页用 `full`(默认),设置页那种"一节的正文空着"用 `section`,
 * 弹出层、窄侧栏、对话框里的小分区用 `compact`。此前小面板各自糊一行居中灰字 —— 三处三个
 * 样子,而读者从"长得不一样"读出的是「这里坏了」,不是「这里还没有东西」。
 *
 * `section` 这一档是补出来的:设置页拿 `full` 用,于是「还没有机器人」是 20px 粗体、配一个
 * 64px 的图标砖,而它上面那个真正的节标题也才 24px —— 一句"这里是空的"和整节的标题一样重,
 * 眼睛先看到的是空态。它比整页那一档轻一级:标题回到正文的字号、图标砖收到 44px。
 *
 * `body` 可以省:一句标题足够时不必硬凑第二句。有下一步动作就给 `action` —— 空状态最有价值的
 * 那一半是"接下来做什么",而不是"这里是空的"。
 */
export function EmptyState({
  icon,
  title,
  body,
  badge,
  action,
  size = "full",
  className,
}: {
  icon: React.ReactNode;
  title: string;
  body?: string;
  badge?: string;
  action?: React.ReactNode;
  size?: "full" | "section" | "compact";
  className?: string;
}) {
  const compact = size === "compact";
  const section = size === "section";
  return (
    <div
      className={cn(
        // `max-w` 是**上限不是宽度**,但它挡不住比它更窄的容器 —— 260px 的空态放进 258px 的
        // 侧栏就溢出 10px,而那 10px 会让整页能左右滑。`w-full` 让它先服从容器,
        // `break-words` 让里面的长 URL(报错文案里全是)断得开而不是硬撑。
        "empty-state m-auto grid w-full justify-items-center break-words text-center [overflow-wrap:anywhere]",
        compact &&
          "max-w-[260px] gap-1 px-3 py-4 [&_h2]:m-0 [&_h2]:text-ui-sm [&_h2]:font-[620] [&_p]:m-0 [&_p]:text-ui-xs [&_p]:leading-[1.5] [&_p]:text-muted-foreground",
        section &&
          "max-w-[380px] gap-2 px-5 py-6 [&_h2]:m-0 [&_h2]:mt-1 [&_h2]:text-ui-md [&_h2]:font-[600] [&_p]:m-0 [&_p]:max-w-[36ch] [&_p]:text-ui-sm [&_p]:leading-[1.6] [&_p]:text-muted-foreground",
        !compact && !section &&
          "max-w-[480px] gap-3 px-6 py-10 [&_h2]:mt-2 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:tracking-tight [&_p]:mb-3 [&_p]:mt-0 [&_p]:max-w-[40ch] [&_p]:text-ui-md [&_p]:leading-relaxed [&_p]:text-muted-foreground",
        className,
      )}
    >
      <div
        className={cn(
          "grid place-items-center bg-accent text-primary",
          compact && "h-8 w-8 rounded-lg",
          section && "h-11 w-11 rounded-xl [&_svg]:size-5",
          !compact && !section && "h-16 w-16 rounded-2xl [&_svg]:size-7",
        )}
      >
        {icon}
      </div>
      {badge && (
        <span className="rounded-full border border-border bg-secondary px-[9px] py-px text-ui-xs font-semibold text-muted-foreground">
          {badge}
        </span>
      )}
      <h2>{title}</h2>
      {body && <p>{body}</p>}
      {action}
    </div>
  );
}

/**
 * 「这一页的数据没取回来」的统一说法。
 *
 * **它和空态是两件事,而把前者显示成后者是在撒谎**:后端连不上时,画板页此前渲染的是
 * 「创意画板 0」加一个「新建画板」按钮 —— 用户看到的是"我一个画板都没有",而不是"没连上"。
 * 一个说"这里是空的"的界面,在真的空和取不到之间必须分得清,否则它在其中一种情况下必然骗人。
 *
 * 素材页和发布页本来就做对了,这里只是把那段照抄了五遍的 JSX 收成一处,让别的页也能接上。
 * `retry` 给的是 react-query 的 refetch —— 连回来之后不该逼用户刷新整页。
 */
export function PageLoadError({
  icon,
  error,
  onRetry,
  retrying,
  title,
  actions,
  size,
  className,
}: {
  icon: React.ReactNode;
  error: unknown;
  onRetry?: () => void;
  /** 重试发出去了、还没回来:按钮转圈,不让人连点。 */
  retrying?: boolean;
  /** 不给就是通用的「暂时无法加载」;说得出是什么没取回来就说(「模型库没读出来」)。 */
  title?: string;
  /** 「重试」旁边的下一步(「去检查连接设置」)—— 重试解决不了的那种失败,要告诉人去哪儿改。 */
  actions?: React.ReactNode;
  /** 主从布局的窄索引列里用 `compact`,整页用默认。 */
  size?: "full" | "section" | "compact";
  className?: string;
}) {
  const t = useI18n();
  //: 桌面版的后端连崩被认输时,「重试」先请主进程重拉它、等它就绪(见 lib/desktopBackend)。这段时间按钮转圈。
  const [reviving, setReviving] = React.useState(false);
  const retry = onRetry
    ? () => {
        if (!canReviveDesktopBackend()) {
          onRetry();
          return;
        }
        setReviving(true);
        void reviveDesktopBackend().then(() => {
          setReviving(false);
          onRetry();
        });
      }
    : undefined;
  //: 正文只说第一行那句人话;原文(errno、地址、对方回的正文)收进「详情」,要排查时展开看、能选中复制。
  const { summary, detail } = splitErrorText(errorText(error ?? ""));
  const buttons =
    retry || actions ? (
      <div className="flex flex-wrap justify-center gap-2">
        {retry && (
          <Button variant="secondary" loading={retrying || reviving} onClick={retry}>
            {t("retry")}
          </Button>
        )}
        {actions}
      </div>
    ) : null;
  return (
    <EmptyState
      icon={icon}
      title={title ?? t("pageLoadError")}
      body={summary}
      size={size}
      className={className}
      action={
        buttons || detail ? (
          <div className="grid w-full justify-items-center gap-3">
            {buttons}
            {detail && <ErrorDetails text={detail} />}
          </div>
        ) : undefined
      }
    />
  );
}

function ErrorDetails({ text }: { text: string }) {
  const t = useI18n();
  return (
    <Collapsible className="grid w-full justify-items-center gap-2">
      <CollapsibleTrigger asChild>
        {/* 行内动作:它是「重试」底下那句报错的附注,不和「重试」争 —— 此前是 sm 档、正文字号,和「重试」一样大。 */}
        <Button variant="inline" className="group">
          {t("errorDetails")}
          <ChevronDown className="transition-transform duration-100 group-data-[state=open]:rotate-180" />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="w-full">
        <pre className="m-0 max-h-40 w-full overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted/60 p-2.5 text-left font-mono text-ui-2xs leading-[1.55] text-muted-foreground">
          {text}
        </pre>
      </CollapsibleContent>
    </Collapsible>
  );
}
