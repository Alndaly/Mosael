import React from "react";

import { codeHighlighter } from "@/components/agent/codeHighlighter";
import { cn } from "@/lib/utils";

/**
 * 一段带高亮的代码/数据。**给 Markdown 之外的地方用** —— 工具调用的参数与结果、
 * 确认卡的载荷、插件输出,这些在界面上长得和代码块一模一样,却一直是一片灰。
 *
 * 复用对话里那同一个高亮器(codeHighlighter),而不是另写一套配色:同一个应用里
 * "什么是字符串、什么是键"不该有两种颜色。
 *
 * 高亮器是懒加载的,所以这里先渲染纯文本,拿到 token 之后再换上 —— 和 Streamdown
 * 的做法一致(它的插件契约本来就是"没准备好就返回 null,好了走回调")。
 */
export function HighlightedCode({
  code,
  language = "json",
  className,
}: {
  code: string;
  language?: string;
  className?: string;
}) {
  const [tokens, setTokens] = React.useState<TokenLine[] | null>(null);

  React.useEffect(() => {
    let alive = true;
    const take = (result: { tokens: TokenLine[] }) => {
      if (alive) setTokens(result.tokens);
    };
    // 语言不在支持列表里就老实显示纯文本,不猜。
    if (!codeHighlighter.supportsLanguage(language as never)) {
      setTokens(null);
      return;
    }
    const immediate = codeHighlighter.highlight({ code, language: language as never, themes: codeHighlighter.getThemes() }, take);
    if (immediate) take(immediate as { tokens: TokenLine[] });
    else setTokens(null);
    return () => {
      alive = false;
    };
  }, [code, language]);

  return (
    <pre className={cn("m-0 overflow-auto whitespace-pre-wrap font-mono leading-[1.5] [word-break:break-word]", className)}>
      {tokens
        ? tokens.map((line, index) => (
            <React.Fragment key={index}>
              {line.map((token, position) => (
                <span
                  key={position}
                  // 亮色走 --sdm-c,暗色走 --shiki-dark —— 和 Streamdown 给 Markdown
                  // 代码块用的是同一套变量约定(见 codeHighlighter 里那段说明)。
                  className="text-[var(--sdm-c,inherit)] dark:text-[var(--shiki-dark,var(--sdm-c,inherit))]"
                  style={tokenStyle(token)}
                >
                  {token.content}
                </span>
              ))}
              {index < tokens.length - 1 ? "\n" : null}
            </React.Fragment>
          ))
        : code}
    </pre>
  );
}

type Token = { content: string; color?: string; htmlStyle?: Record<string, string> };
type TokenLine = Token[];

/**
 * 把 shiki 的 token 配色搬成两个 CSS 变量,**并且把 `color` 从内联样式里摘掉**。
 *
 * 摘掉这一步是关键。双主题模式下 shiki 的 `htmlStyle` 长这样:
 *
 *     { color: "#24292e", "--shiki-dark": "#E1E4E8" }
 *
 * 整个摊进 `style` 的话,那个内联 `color` 会**压过上面两个 Tailwind 类** —— 内联样式赢过
 * 任何基于 class 的规则。于是 `--shiki-dark` 明明设上了却没人读,深色模式下拿到的是浅色
 * 主题的字色:实测 34 个 token 全部低于 4.5 对比度,最差 1.17(#24292e 印在 #141218 上,
 * 基本看不见)。浅色模式下碰巧看着是对的 —— 内联色正好就是浅色,所以这个 bug 一直没暴露。
 *
 * 亮色值优先取 `token.color`;双主题模式下它是空的,那就从 htmlStyle 里取。
 */
function tokenStyle(token: Token): React.CSSProperties {
  const { color, ...rest } = token.htmlStyle ?? {};
  return { "--sdm-c": token.color ?? color, ...rest } as React.CSSProperties;
}
