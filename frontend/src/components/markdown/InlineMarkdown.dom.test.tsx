/** @vitest-environment jsdom */
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { render } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import { InlineMarkdown } from "./InlineMarkdown";

describe("InlineMarkdown", () => {
  it("记号渲染成元素,字面里不剩 ** 和反引号", () => {
    const { container } = render(
      <small>
        <InlineMarkdown text="把一份素材传上去,交回一条**限时直链**;代码是 `export default` 一个组件" />
      </small>,
    );
    expect(container.querySelector("strong")?.textContent).toBe("限时直链");
    expect(container.querySelector("code")?.textContent).toBe("export default");
    expect(container.textContent).not.toMatch(/\*\*|`/);
    // 只出行内元素:放进 <small>/<button> 不产生块级嵌套。
    expect(container.querySelector("div, p")).toBeNull();
  });

  it("链接只认 http(s);关掉链接时只留文字", () => {
    const { container, rerender } = render(<InlineMarkdown text="见 [文档](https://example.com) 或 [这个](javascript:alert(1))" />);
    const anchors = container.querySelectorAll("a");
    expect(anchors).toHaveLength(1);
    expect(anchors[0].getAttribute("href")).toBe("https://example.com/");
    expect(anchors[0].getAttribute("target")).toBe("_blank");
    expect(container.textContent).toBe("见 文档 或 这个");

    rerender(<InlineMarkdown text="见 [文档](https://example.com)" links={false} />);
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toBe("见 文档");
  });

  it("空一行是一个换行", () => {
    const { container } = render(<InlineMarkdown text={"第一段\n\n第二段"} />);
    expect(container.querySelectorAll("br")).toHaveLength(1);
  });
});

/**
 * 棘轮:数据里的说明文字(`description` / `help` / `summary`)不再直接当 JSX 子节点渲染,
 * 也不再原样拼进要显示或要搜索的字符串 —— 要么 `<InlineMarkdown>`,要么 `toPlainText`。
 *
 * 例外逐条写明理由;新加一条例外之前先想想它是不是真的该原样显示。
 */
const SRC = join(import.meta.dirname, "../..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "generated" ? [] : sourceFiles(full);
    return /\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name) ? [full] : [];
  });
}

const ALLOWED = new Set([
  // 用户自己写的发布正文,要原样发到平台上 —— 按 markdown 渲染反而是在骗人。
  "features/publish/PublishView.tsx {task.description}",
  // 调试追踪:看的就是原文。
  "features/agent/trace/TraceView.tsx {event.summary}",
  "features/agent/trace/TraceView.tsx ${event.summary}",
  // 附进发给智能体的消息正文里,不是显示给人看的。
  "features/agent/CanvasAgentChat.tsx ${noteAttach.summary}",
  "features/ai-studio/ChatWorkspace.tsx ${noteAttach.summary}",
  // 通用下拉:调用方传进来的已经是纯文本(节点面板那边先过了 toPlainText)。
  "components/ui/searchable-select.tsx {item.description}",
  "components/ui/option-picker.tsx description={one.description}",
]);

// `<AgentMarkdown>{…}</AgentMarkdown>` 是块级的那条出口(模型写的整段摘要),同样算过了关。
const DIRECT = /(?<![=$\w]|<AgentMarkdown>)\{\s*[\w?.]+\.(?:description|help|summary)\s*\}/g;
const INTERPOLATED = /\$\{[\w?.]+\.(?:description|help|summary)\}/g;
// 原样交给另一个组件的 prop(`<SettingsRow description={field.help}>`),那个组件只会把它当纯文本放。
const PASSED = /(?:description|title|aria-label)=\{[\w?.]+\.(?:description|help|summary)\}/g;

it("数据里的说明文字只经 InlineMarkdown / toPlainText 上界面", () => {
  const offenders = sourceFiles(SRC).flatMap((file) => {
    const code = readFileSync(file, "utf8");
    const path = relative(SRC, file);
    return [...code.matchAll(DIRECT), ...code.matchAll(INTERPOLATED), ...code.matchAll(PASSED)]
      .map((match) => `${path} ${match[0].replace(/\s+/g, "")}`)
      .filter((key) => !ALLOWED.has(key));
  });
  expect(offenders).toEqual([]);
});
