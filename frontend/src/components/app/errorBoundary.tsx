/**
 * 错误边界的通用部分:接住、记下、复位,以及「这一块代码没取到」怎么认。
 *
 * 三层各用它一次:整个窗口(app/PageBoundary 的 AppBoundary)、一页(PageBoundary)、页里或窗口上的**一块**
 * (这里的 SectionBoundary)。此前只有前两层 —— 常驻的浮层(确认中心、免提浮标、内嵌浏览器的顶栏、ComfyUI 工作台)
 * 渲染出错,整个窗口换成「Mosael 出错了」;嵌在画板、剪辑、笔记、工作流里的助手面板出错,整页被换掉,而画布本身好好的。
 * 它们渲染的都是外面来的数据(模型的工具结果、确认卡的载荷、ComfyUI 的画布状态),出错只该换掉自己。
 */

import React from "react";
import { RefreshCcw, X } from "lucide-react";
import { toast } from "sonner";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";

/**
 * 是不是「那一块代码没取到」。各家浏览器的说法不一样(Chromium / Safari / Firefox),打包器
 * 包一层时是 ChunkLoadError。**只有这一种**重新加载多半就好;页面自己抛的错重新加载照样抛,告诉人
 * 「断了一下、重新加载就好」是在误导(剪辑页一个 context 找不到时就这样说过)。
 */
export function isChunkLoadError(error: Error): boolean {
  return (
    error.name === "ChunkLoadError" ||
    /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS/i.test(error.message)
  );
}

/**
 * 从错误里恢复。
 *
 * **代码块没取到时只能整窗重新加载**,原地复位没有用:`React.lazy` 在 import 失败后把失败**缓存**在那个懒组件上,
 * 之后每次渲染直接重抛,不会再去取 —— 而懒组件是模块级常量,活到窗口刷新为止(实测:放行网络后点「重试」,
 * 服务端收到的请求数是 0;切走再回来也是 0)。应用更新后旧窗口指着的文件名本来就不存在了,也只有重新加载能拿到新的。
 * 失败的那一块本来就没画出来,没有可丢的状态;别处的编辑由各自的自动保存兜着 —— 和整窗那一层同一个做法。
 *
 * 其余的错(组件自己抛的)原地复位,再给调用方一个机会做点别的(`onRetry`)。
 */
export function recover(error: Error, reset: () => void, onRetry?: () => void): void {
  if (isChunkLoadError(error)) {
    window.location.reload();
    return;
  }
  reset();
  onRetry?.();
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
  /** 变化时自动复位。 */
  resetKey?: unknown;
  /** 接住错误的那一刻。 */
  onCatch?: (error: Error) => void;
  fallback: (error: Error, reset: () => void) => React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error): void {
    this.props.onCatch?.(error);
  }

  componentDidUpdate(previous: ErrorBoundaryProps): void {
    // 换了一页 / 换了一段会话就别再顶着上一次的错误 —— 否则人被锁在这一屏,和白屏一样走不掉。
    if (!Object.is(previous.resetKey, this.props.resetKey) && this.state.error) {
      this.setState({ error: null });
    }
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  render(): React.ReactNode {
    if (!this.state.error) return this.props.children;
    return this.props.fallback(this.state.error, this.reset);
  }
}

/**
 * **一块**界面的错误边界:出错只换掉自己。
 *
 * - `inline`(默认):原地换成一句「这一块出错了」、原始报错和「重试」(代码块没取到时是「重新加载」);给了 `onClose`
 *   就再给一个「关闭」—— 助手面板出错时,人多半想先把它收起来接着干活。
 * - `quiet`:不占地方,只弹一条提示(原始报错在提示的说明里;代码块没取到时提示上带「重新加载」)。给浮在窗口上的那些用:
 *   确认中心、免提浮标、内嵌浏览器的顶栏 —— 它们没有一块「自己的地方」可以摆一张错误卡,`resetKey` 一变(换了一页、浏览器视图
 *   重新亮起)就重新挂上。
 */
export function SectionBoundary({
  children,
  mode = "inline",
  resetKey,
  onCatch,
  onClose,
  className,
}: {
  children: React.ReactNode;
  mode?: "inline" | "quiet";
  resetKey?: unknown;
  onCatch?: (error: Error) => void;
  onClose?: () => void;
  /** inline 那张错误卡外层的样式(默认撑满所在的格子、内容居中)。 */
  className?: string;
}) {
  const t = useI18n();
  const caught = (error: Error) => {
    if (mode === "quiet") {
      //: 这一块的代码没取到时,提示上带「重新加载」:懒组件把失败缓存住了,网络回来之后再点开它照样是同一个错
      //: (在桌面版里实测:工作台那一块取失败一次,同一个窗口里再「在工作台里打开」还是收起 + 同一条提示,请求数 0)。
      //: 多留一会儿:这一块常常是从一个开着的弹窗里点开的(工作流库里「在工作台里打开」),弹窗开着时提示上的按钮点不到,
      //: 人得先关掉弹窗。
      const reload = isChunkLoadError(error)
        ? { action: { label: t("appReload"), onClick: () => window.location.reload() }, duration: 20_000 }
        : {};
      toast.error(t("sectionCrashedQuiet"), { description: error.message, ...reload });
    }
    onCatch?.(error);
  };
  return (
    <ErrorBoundary
      resetKey={resetKey}
      onCatch={caught}
      fallback={(error, reset) =>
        mode === "quiet" ? null : (
          <div role="alert" data-section-crashed="" className={className ?? "flex h-full min-h-0 w-full flex-col overflow-auto p-4"}>
            <div className="m-auto grid max-w-sm shrink-0 justify-items-center gap-2 text-center">
              <p className="m-0 text-ui-sm text-foreground">{isChunkLoadError(error) ? t("pageLoadFailed") : t("sectionCrashed")}</p>
              <p className="m-0 text-ui-xs text-muted-foreground [overflow-wrap:anywhere]">{error.message}</p>
              <div className="flex flex-wrap justify-center gap-2">
                <Button size="sm" variant="outline" onClick={() => recover(error, reset)}>
                  <RefreshCcw size={13} /> {isChunkLoadError(error) ? t("appReload") : t("retry")}
                </Button>
                {onClose && (
                  <Button size="sm" variant="ghost" onClick={onClose}>
                    <X size={13} /> {t("close")}
                  </Button>
                )}
              </div>
            </div>
          </div>
        )
      }
    >
      {children}
    </ErrorBoundary>
  );
}
