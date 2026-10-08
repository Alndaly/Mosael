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
 * **给一个真能恢复的按钮**,而不是只告诉用户"出错了":这类失败多半是一次性的,但 `React.lazy` 会把失败缓存住,
 * 原地重试永远不会再去取 —— 所以代码块没取到时按钮是「重新加载」,整窗重新加载(见 components/app/errorBoundary
 * 的 `recover`)。`resetKey` 变化(比如用户自己切了一页)时也自动复位 —— 卡在错误态里出不去,和白屏差不了多少。
 */

import React from "react";
import { RefreshCcw } from "lucide-react";

import { translateNow, useI18n } from "@/app/preferences";
import { ErrorBoundary, isChunkLoadError, recover } from "@/components/app/errorBoundary";
import { Button } from "@/components/ui/button";

export { isChunkLoadError } from "@/components/app/errorBoundary";

/** 一页 / 整窗出错时那一屏:撑满再居中,写明哪一种错、留着原始报错、给一个按钮。 */
function FullScreenError({
  error,
  chunkLabel,
  crashLabel,
  retryLabel,
  onRetry,
}: {
  error: Error;
  chunkLabel: string;
  crashLabel: string;
  retryLabel: string;
  onRetry: () => void;
}) {
  return (
    /* **撑满这一页再居中。** 此前是 `grid min-h-0 place-items-center` —— `place-items-center`
       只在格子里居中,而格子本身没有高度,于是整块缩成内容高、贴在页面顶上。和 LoadingState
       同一套:自己撑满可用高度,内容用 `m-auto` 落在正中。 */
    <div role="alert" className="flex h-full min-h-0 w-full flex-col overflow-auto p-8">
      <div className="m-auto grid max-w-md shrink-0 justify-items-center gap-3 text-center">
        <p className="m-0 text-ui-md text-foreground">{isChunkLoadError(error) ? chunkLabel : crashLabel}</p>
        {/* 原始信息留着 —— 它是"这一块没取到"和"这一页自己崩了"的唯一区别。 */}
        <p className="m-0 text-ui-xs text-muted-foreground [overflow-wrap:anywhere]">{error.message}</p>
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCcw size={13} /> {retryLabel}
        </Button>
      </div>
    </div>
  );
}

/**
 * 页面那一层。代码块没取到时按钮是「重新加载」、点了整窗重新加载(原地复位救不回来,见 components/app/errorBoundary 的
 * `recover`);页面自己出错时是「重试」,原地复位。
 */
export function PageBoundary({
  children,
  resetKey,
  onRetry,
}: {
  children: React.ReactNode;
  /** 变化时自动复位。传当前页面即可。 */
  resetKey?: string;
  onRetry?: () => void;
}) {
  const t = useI18n();
  return (
    <ErrorBoundary
      resetKey={resetKey}
      fallback={(error, reset) => (
        <FullScreenError
          error={error}
          chunkLabel={t("pageLoadFailed")}
          crashLabel={t("pageCrashed")}
          retryLabel={isChunkLoadError(error) ? t("appReload") : t("retry")}
          onRetry={() => recover(error, reset, onRetry)}
        />
      )}
    >
      {children}
    </ErrorBoundary>
  );
}

/**
 * 整个窗口的错误边界 —— 页面那层(PageBoundary)外面:侧栏、顶栏、各个 Provider 出错时,整棵树卸掉,窗口只剩一片白,
 * 连报错都看不到。这一层兜住它:写明出错了、留着原始报错、给一个「重新加载」。
 *
 * 这时候 Provider 可能已经跟着卸掉了,文案用不带 hook 的 translateNow 取;外壳出的错重新渲染多半照样出,
 * 所以「重试」就是重新加载整页。
 *
 * 内嵌浏览器、工作台的顶栏也跟着卸掉了:亮着的原生网页视图没了它那一圈、还盖在这一页上(盖在一切 DOM 上),报错和「重新加载」
 * 都看不见 —— 接住错误时请主进程把它收起来(和「返回 Mosael」一样,视图本身还在)。
 */
export function AppBoundary({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary
      onCatch={() => void window.mosaelPublish?.hideView().catch(() => undefined)}
      fallback={(error) => (
        <FullScreenError
          error={error}
          chunkLabel={translateNow("appCrashed")}
          crashLabel={translateNow("appCrashed")}
          retryLabel={translateNow("appReload")}
          onRetry={() => window.location.reload()}
        />
      )}
    >
      {children}
    </ErrorBoundary>
  );
}
