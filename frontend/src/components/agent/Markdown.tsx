import React from "react";
import { Streamdown } from "streamdown";

import { codeHighlighter } from "@/components/agent/codeHighlighter";

import { useI18n } from "@/app/preferences";

/**
 * 代码块**不再接管 `pre`**。
 *
 * 此前这里自己画一个框、把内容当纯文本渲染,当时的理由写得很老实:「那套结构是为语法高亮
 * 准备的,而我们没装高亮插件,于是只剩下框」。现在插件装上了(见 codeHighlighter),
 * 再接管 `pre` 就等于把高亮体整个绕过去 —— 用户看到的仍是一片灰。
 *
 * 所以交还给 Streamdown 自己渲染,外观用下面那串 className 收:一个框、语言标签与复制按钮
 * 悬停才显现,和原来看齐。
 */

/**
 * 智能体正文的 Markdown 渲染。
 *
 * 排版规则集中在这一串 className 里:块级元素统一 10px 下缝(末块清零),表格拍平成裸表格,
 * 行内 code 是小药丸、代码块里的 code 则完全交给 {@link CodeCard}。
 */
export function AgentMarkdown({ children }: { children: string }) {
  const t = useI18n();
  return (
    <Streamdown
      className="min-w-0 max-w-full [&_:is(p,ul,ol,table)]:mx-0 [&_:is(p,ul,ol,table)]:mt-0 [&_:is(p,ul,ol,table)]:mb-2.5 [&_:is(p,ul,ol,table):last-child]:mb-0 [&_:is(h1,h2)]:mt-4 [&_:is(h1,h2)]:mb-2 [&_:is(h1,h2)]:text-[15px] [&_:is(h1,h2)]:font-[650] [&_:is(h1,h2)]:tracking-[-0.01em] [&_:is(h3,h4)]:mt-3 [&_:is(h3,h4)]:mb-1.5 [&_:is(h3,h4)]:text-ui-md [&_:is(h3,h4)]:font-[650] [&_:is(h1,h2,h3,h4):first-child]:mt-0 [&_table]:w-full [&_table]:border-collapse [&_table]:text-ui-sm [&_:is(th,td)]:border [&_:is(th,td)]:border-border [&_:is(th,td)]:px-2 [&_:is(th,td)]:py-1.5 [&_:is(th,td)]:text-left [&_th]:bg-secondary [&_th]:font-semibold [&_code]:rounded-sm [&_code]:bg-panel-inset [&_code]:px-1 [&_code]:py-px [&_code]:font-mono [&_code]:text-xs [&_pre_code]:rounded-none [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-[inherit] [&_:is(ul,ol)]:pl-[18px] [&_div:has(>div>table)]:my-2.5 [&_div:has(>div>table)]:rounded-none [&_div:has(>div>table)]:border-0 [&_div:has(>div>table)]:bg-transparent [&_div:has(>div>table)]:p-0 [&_div:has(>table)]:rounded-none [&_div:has(>table)]:border-0 [&_div:has(>table)]:bg-transparent"
      plugins={{ code: codeHighlighter }}
      controls={{ table: false, code: { copy: true, download: false } }}
      translations={{ copyCode: t("copy"), copied: t("copied") }}
    >
      {children}
    </Streamdown>
  );
}
