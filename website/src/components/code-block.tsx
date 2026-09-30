"use client";

import * as React from "react";
import { Check, Copy, WrapText } from "lucide-react";

import { cn } from "@/lib/utils";

export type CodeBlockLabels = { copy: string; copied: string; wrapOn: string; wrapOff: string };

/** 不值得标出来的「语言」:没写语言的代码块由 mdx-options 记成 plaintext。 */
const UNLABELED = new Set(["plaintext", "text", "txt"]);

/**
 * 正文里的代码块:顶上一条窄栏,左边是语言,右边是「自动换行」与「复制」。
 *
 * 放在顶栏而不是悬浮在代码右上角:长的第一行会被悬浮按钮挡住,而命令行恰恰常常只有一行。
 *
 * **复制按行取**:高亮之后每一行是一个 `[data-line]`,代码框又是 grid 布局 —— 直接读 innerText 会在
 * 行与行之间多出空行,读 textContent 又依赖行间那个换行字符还在不在。按行取、用 `\n` 接起来,
 * 两种情况下拿到的都是原文。
 *
 * 换行开关只管这一块,不记忆:长命令想看全就点一下,默认仍是不换行(缩进和对齐才看得清)。
 */
export function CodeBlock({ labels, className, children, ...props }: React.ComponentProps<"pre"> & { labels: CodeBlockLabels }) {
  const ref = React.useRef<HTMLPreElement>(null);
  const [wrap, setWrap] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const language = String((props as Record<string, unknown>)["data-language"] ?? "");

  React.useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    const node = ref.current;
    if (!node) return;
    const lines = node.querySelectorAll("[data-line]");
    const text = lines.length ? Array.from(lines, (line) => line.textContent ?? "").join("\n") : (node.textContent ?? "");
    try {
      await navigator.clipboard.writeText(text.replace(/\n+$/, ""));
      setCopied(true);
    } catch {
      // 剪贴板被拒(非安全上下文、权限)时不假装成功 —— 按钮保持原样,人自己选中复制。
    }
  };

  const button =
    "inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring";

  return (
    <div data-code-block className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex min-h-9 items-center justify-between gap-2 border-b border-border/70 py-1 pr-1.5 pl-4 font-sans">
        <span className="font-mono text-[0.6875rem] tracking-wide text-muted-foreground lowercase">
          {UNLABELED.has(language) ? "" : language}
        </span>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            className={cn(button, wrap && "bg-muted text-foreground")}
            aria-pressed={wrap}
            aria-label={wrap ? labels.wrapOff : labels.wrapOn}
            title={wrap ? labels.wrapOff : labels.wrapOn}
            onClick={() => setWrap((on) => !on)}
          >
            <WrapText className="size-3.5" aria-hidden />
          </button>
          <button type="button" className={button} aria-label={copied ? labels.copied : labels.copy} title={copied ? labels.copied : labels.copy} onClick={copy}>
            {copied ? <Check className="size-3.5 text-primary" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
          </button>
          {/* 读屏软件要听到「已复制」:图标换了它看不见。 */}
          <span className="sr-only" aria-live="polite">
            {copied ? labels.copied : ""}
          </span>
        </div>
      </div>
      <pre
        ref={ref}
        {...props}
        data-wrap={wrap ? "true" : undefined}
        className={cn(
          "m-0 rounded-none border-0 bg-transparent",
          wrap && "overflow-x-hidden break-words whitespace-pre-wrap",
          // 折下来的那一截往里缩两格(悬挂缩进),一眼看得出它接的是上一行,不是新的一行代码。
          wrap && "[&_[data-line]]:pl-[2ch] [&_[data-line]]:-indent-[2ch]",
          className,
        )}
      >
        {children}
      </pre>
    </div>
  );
}
