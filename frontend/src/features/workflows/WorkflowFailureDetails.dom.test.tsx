/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 浏览器节点失败之后,人最想知道的是**当时页面长什么样**。
 *
 * 错误文案已经能说清等的是什么、等了多久、当时停在哪一页,但站点改版之后光有网址还是不够:
 * 那一刻屏幕上是登录墙、是验证码,还是页面压根没跳过去?这一栏就是答那个问题的。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { WorkflowFailureDetails } from "@/features/workflows/WorkflowFailureDetails";

describe("失败现场", () => {
  it("浏览器失败时画出截图,并说清这一步在找什么", () => {
    render(
      <WorkflowFailureDetails
        details={{
          action: "wait",
          selector: "#login",
          page_url: "https://x.test/login",
          screenshot: "data:image/png;base64,AAAA",
        }}
      />,
    );
    expect(screen.getByRole("img")).toHaveAttribute("src", "data:image/png;base64,AAAA");
    expect(screen.getByText("#login")).toBeInTheDocument();
    expect(screen.getByText("https://x.test/login")).toBeInTheDocument();
  });

  it("没截到图时,现场的其余部分照常显示", () => {
    // 会话已经关掉、执行器没响应……都只意味着"这次没有图",不该把整栏一起吞掉。
    render(<WorkflowFailureDetails details={{ action: "click", selector: ".go" }} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText(".go")).toBeInTheDocument();
    // 认得出来的现场不该再退回那坨原始 JSON。
    expect(screen.queryByText(/"action"/)).toBeNull();
  });

  it("不是图片的 screenshot 一律不当图片渲染", () => {
    // details 来自任务记录,而记录里可以是任何东西;`javascript:` 这类值绝不能进 <img src>。
    render(<WorkflowFailureDetails details={{ action: "click", screenshot: "javascript:alert(1)" }} />);
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("LLM 那一族的现场照旧", () => {
    render(<WorkflowFailureDetails details={{ model: "gpt-5.2", raw_response: "{oops" }} />);
    expect(screen.getByText("gpt-5.2")).toBeInTheDocument();
    expect(screen.getByText("{oops")).toBeInTheDocument();
  });
});
