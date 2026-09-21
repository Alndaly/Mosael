/**
 * 页面这一块的错误边界 —— 主要为**按需加载**兜底。
 *
 * 页面改成 `React.lazy` 之后多了一种此前不存在的失败:那一块 JS 没取到。取不到的原因可以是
 * 磁盘/网络的一次抖动,也可以是应用更新后旧页面还指着已经不存在的文件名。而 `React.lazy` 在
 * 加载失败时是**往上抛**的 —— 上面只有一层 Suspense,Suspense 不接错误,于是整棵树卸掉,
 * 用户看到一个**永久的白屏**,连回上一页都做不到,只能重启。
 *
 * 这不是理论风险:同一次改动已经因为"样式表跟着页面走丢了"出过一次线上问题(见
 * design/vendorStyles.test.ts)。按需加载省下来的 4 MB 值得,但它带来的新失败要自己兜住。
 *
 * **重试是有意义的**:这类失败多半是一次性的,重新 import 就好。所以这里给一个按钮,而不是
 * 只告诉用户"出错了"。`resetKey` 变化(比如用户自己切了一页)时也自动复位 —— 卡在错误态里
 * 出不去,和白屏差不了多少。
 */

import React from "react";
import { RefreshCcw } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";

interface Props {
  children: React.ReactNode;
  /** 变化时自动复位。传当前页面即可。 */
  resetKey?: string;
  onRetry?: () => void;
  label: string;
  retryLabel: string;
}

interface State {
  error: Error | null;
}

class Boundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(previous: Props): void {
    // 换了一页就别再顶着上一页的错误 —— 否则用户被锁在这一屏,和白屏一样走不掉。
    if (previous.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render(): React.ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      /* **撑满这一页再居中。** 此前是 `grid min-h-0 place-items-center` —— `place-items-center`
         只在格子里居中,而格子本身没有高度,于是整块缩成内容高、贴在页面顶上。和 LoadingState
         同一套:自己撑满可用高度,内容用 `m-auto` 落在正中。 */
      <div role="alert" className="flex h-full min-h-0 w-full flex-col overflow-auto p-8">
        <div className="m-auto grid max-w-md shrink-0 justify-items-center gap-3 text-center">
          <p className="m-0 text-ui-md text-foreground">{this.props.label}</p>
          {/* 原始信息留着 —— 它是"这一块没取到"和"这一页自己崩了"的唯一区别。 */}
          <p className="m-0 text-ui-xs text-muted-foreground [overflow-wrap:anywhere]">
            {this.state.error.message}
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              this.setState({ error: null });
              this.props.onRetry?.();
            }}
          >
            <RefreshCcw size={13} /> {this.props.retryLabel}
          </Button>
        </div>
      </div>
    );
  }
}

/** 文案要在函数组件里取,所以外面再包一层。 */
export function PageBoundary({
  children,
  resetKey,
  onRetry,
}: {
  children: React.ReactNode;
  resetKey?: string;
  onRetry?: () => void;
}) {
  const t = useI18n();
  return (
    <Boundary resetKey={resetKey} onRetry={onRetry} label={t("pageLoadFailed")} retryLabel={t("retry")}>
      {children}
    </Boundary>
  );
}
